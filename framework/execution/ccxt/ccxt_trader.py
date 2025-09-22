"""
CCXT-based trader with comprehensive error handling and state management
"""
import time
import ccxt
import pandas as pd
from datetime import datetime, date
from typing import Dict, Optional, Any, List
import logging
from enum import Enum
from dataclasses import dataclass, asdict

from .state_persistence import StateStore
from framework.utils.postgres_state_store import PostgreSQLStateStore
from framework.utils.simple_state_store import SimpleStateStore
from .position_sync import PositionSynchronizer
from .data_manager import DataManager
from framework.utils.latency_monitor import measure_api_latency
from framework.utils.logger import get_logger
from framework.monitoring.alert_system import AlertSystem
from framework.risk.fixed_position_size_manager import FixedPositionSizeManager
from framework.risk.fixed_risk_manager import FixedRiskManager
from framework.risk.strategy_position_size_manager import StrategyPositionSizeManager


class OrderStatus(Enum):
    PENDING = "pending"
    PLACED = "placed"
    PARTIAL = "partial"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    size: float
    order_type: str
    status: OrderStatus
    timestamp: str
    exchange_order_id: Optional[str] = None
    filled_size: float = 0.0
    average_price: float = 0.0
    error: Optional[str] = None


class CCXTTrader:
    """Production-ready CCXT trader with comprehensive error handling"""
    
    def __init__(self, config):
        self.config = config
        self.logger = get_logger("TradingBot.ccxt_trader")
        
        # State management - PostgreSQL with file fallback
        self.logger.info(
            "Initializing state store...",
            extra={
                'exchange': self.config.exchange_name.upper(),
                'initial_capital': self.config.initial_capital
            }
        )
        
        # Try PostgreSQL first, fallback to file storage
        try:
            self.state_store = PostgreSQLStateStore(
                exchange=self.config.exchange_name.upper(),
                instance_id=f"trader_{self.config.exchange_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            storage_type = 'PostgreSQL'
        except Exception as e:
            self.logger.warning(
                f"Failed to initialize PostgreSQL state store: {e}, falling back to file storage",
                extra={'error': str(e)}
            )
            self.state_store = SimpleStateStore(exchange=self.config.exchange_name.upper())
            storage_type = 'SimpleFileStore'
        
        # Log state store info
        self.logger.info(
            "State store initialized",
            extra={
                'storage_type': storage_type,
                'exchange': self.config.exchange_name.upper()
            }
        )
        
        # Safety settings (need these before _initialize_exchange)
        self.emergency_stop = False
        self.max_retries = 3
        self.retry_delays = [1, 5, 15]  # Exponential backoff
        self.daily_loss_limit = config.initial_capital * 0.02  # 2% daily loss limit
        
        # State
        self.positions = {}
        self.orders = {}
        self.daily_pnl = 0.0
        self.initial_balance = None
        
        # Legacy position sizing setting (now handled by risk manager)
        self.max_position_pct = config.max_position_size
        
        # Alert system
        self.alert_system = AlertSystem(config)
        
        # Initialize risk manager
        self.risk_manager = self._initialize_risk_manager(config)
        
        # Database logger
        from framework.utils.async_db_logger import get_db_logger
        try:
            self.db_logger = get_db_logger()
            self.db_logging_enabled = True
            self.logger.info("Database logging enabled")
        except Exception as e:
            self.logger.warning(f"Failed to initialize database logger: {e}")
            self.db_logger = None
            self.db_logging_enabled = False
        
        # Try to acquire lock
        # Use date-based lock ID to allow same-day restarts but prevent parallel executions
        lock_id = f"trader_{config.exchange_name}_{config.timeframe}_{date.today().isoformat()}"
        if not self.state_store.acquire_lock(lock_id):
            raise RuntimeError("Another instance is already running!")
        self.lock_id = lock_id
        
        # Initialize exchange
        self._initialize_exchange()
        
        # Components
        self.data_manager = DataManager(
            max_bars=500,
            cache_duration=60  # Will be updated after initialization
        )
        self.position_sync = PositionSynchronizer(self.exchange, self.logger)
        
        # Update cache duration after data_manager is created
        cache_duration = self._get_cache_duration()
        self.data_manager.cache_duration = cache_duration
        
        # Get initial balance now that position_sync is created
        self._set_initial_balance()
        
        # Recovery
        self._recover_state()
        
        # Note: Database logging is available in async_db_logger.py but disabled
        # to avoid complexity. State persistence works via trading.trading_state table.
        
    def __del__(self):
        """Cleanup on destruction"""
        if hasattr(self, 'state_store') and hasattr(self, 'lock_id'):
            self.state_store.release_lock(self.lock_id)
    
    def _initialize_risk_manager(self, config):
        """Initialize risk manager based on configuration"""
        risk_manager_type = getattr(config, 'risk_manager_type', 'fixed_position')
        risk_manager_params = getattr(config, 'risk_manager_params', {})
        
        if risk_manager_type == "fixed_position":
            risk_manager = FixedPositionSizeManager(
                position_size=risk_manager_params.get('position_size', 0.1)
            )
        elif risk_manager_type == "fixed_risk":
            risk_manager = FixedRiskManager(
                risk_percent=risk_manager_params.get('risk_percent', 0.01),
                default_stop_distance=risk_manager_params.get('default_stop_distance', 0.02)
            )
        elif risk_manager_type == "strategy_position":
            risk_manager = StrategyPositionSizeManager(
                max_position_size=risk_manager_params.get('max_position_size', 1.0),
                min_position_size=risk_manager_params.get('min_position_size', 0.001),
                apply_safety_limits=risk_manager_params.get('apply_safety_limits', True)
            )
        else:
            # Default to fixed position size
            self.logger.warning(f"Unknown risk manager type: {risk_manager_type}, using fixed_position")
            risk_manager = FixedPositionSizeManager(position_size=0.1)
        
        self.logger.info(f"Risk Manager: {risk_manager.get_description()}")
        return risk_manager
    
    def _initialize_async_db_logger(self):
        """Initialize async database logger in background"""
        async def init_db_logger():
            try:
                self.logger.info("Initializing async database logger...")
                self.db_logger = await get_async_db_logger()
                self.db_logging_enabled = True
                self.logger.info("Async database logging enabled")
            except Exception as e:
                self.logger.warning(f"Failed to initialize async database logger: {e}")
                self.db_logger = None
                self.db_logging_enabled = False
        
        # Start initialization in background
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            self._db_logger_task = loop.create_task(init_db_logger())
        except RuntimeError:
            # No event loop running, database logging will be disabled
            self.logger.warning("No event loop available for async database logging")
            self.db_logger = None
            self.db_logging_enabled = False
    
    def _log_to_db_async(self, coro):
        """Helper to execute database logging coroutines"""
        if not self.db_logging_enabled or not self.db_logger:
            return
            
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            # Fire and forget - don't wait for completion
            loop.create_task(coro)
        except Exception as e:
            self.logger.debug(f"Failed to schedule database logging: {e}")
            
    def _initialize_exchange(self):
        """Initialize exchange with comprehensive error handling"""
        for attempt in range(self.max_retries):
            try:
                exchange_class = getattr(ccxt, self.config.exchange_name)
                
                # Connection info (no sensitive data)
                self.logger.info(
                    "Initializing exchange connection",
                    extra={
                        'exchange': self.config.exchange_name,
                        'sandbox_mode': self.config.use_sandbox,
                        'trading_type': getattr(self.config, 'trading_type', 'spot'),
                        'api_key_provided': bool(self.config.api_key and self.config.api_key != ''),
                        'api_secret_provided': bool(self.config.api_secret and self.config.api_secret != '')
                    }
                )
                
                # Exchange configuration
                exchange_config = {
                    'enableRateLimit': True,
                    'rateLimit': 1000,  # ms between requests
                    'timeout': 30000,
                    'options': {
                        'defaultType': getattr(self.config, 'trading_type', 'spot'),  # spot or future
                        'adjustForTimeDifference': True,
                    }
                }
                
                # Add credentials if provided
                if self.config.api_key and self.config.api_key != "":
                    exchange_config['apiKey'] = self.config.api_key
                    exchange_config['secret'] = self.config.api_secret
                    
                # Enable sandbox mode if configured
                if self.config.use_sandbox:
                    exchange_config['sandbox'] = True
                    # For Binance futures testnet, we need to set the correct URLs
                    if self.config.exchange_name == 'binance' and self.config.trading_type == 'future':
                        exchange_config['urls'] = {
                            'api': {
                                'public': 'https://testnet.binancefuture.com/fapi/v1',
                                'private': 'https://testnet.binancefuture.com/fapi/v1'
                            },
                            'test': {
                                'public': 'https://testnet.binancefuture.com/fapi/v1',
                                'private': 'https://testnet.binancefuture.com/fapi/v1'
                            }
                        }
                    
                self.exchange = exchange_class(exchange_config)
                
                # Test connection and load markets
                self.markets = self.exchange.load_markets()
                
                self.logger.info(
                    f"Exchange initialized: {self.config.exchange_name} "
                    f"{'SANDBOX' if self.config.use_sandbox else 'LIVE'} mode, "
                    f"{len(self.markets)} markets loaded"
                )
                
                # Exchange initialized successfully
                # Initial balance will be set after position_sync is created
                    
                return
                
            except Exception as e:
                self.logger.error(f"Exchange init attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delays[attempt])
                else:
                    raise
                    
    def _set_initial_balance(self):
        """Set initial balance after position_sync is available"""
        try:
            if self.config.api_key:
                account_info = self.position_sync.get_account_info()
                self.initial_balance = account_info.get('total_balance_usdt', self.config.initial_capital)
                self.logger.info(
                    "Account balance retrieved",
                    extra={
                        'initial_balance_usdt': self.initial_balance,
                        'balance_source': 'exchange_api'
                    }
                )
                
                # Log initial balance to database
                self.logger.info(
                    "Updating initial account balance in database...",
                    extra={
                        'initial_balance': self.initial_balance,
                        'db_logging_enabled': self.db_logging_enabled
                    }
                )
                self._update_account_balance_db()
            else:
                self.initial_balance = self.config.initial_capital
                self.logger.info(
                    "Using config capital",
                    extra={
                        'initial_balance_usdt': self.initial_balance,
                        'balance_source': 'config'
                    }
                )
        except Exception as e:
            self.logger.warning(
                "Could not get initial balance from exchange",
                extra={
                    'error': str(e),
                    'fallback_balance': self.config.initial_capital
                }
            )
            self.initial_balance = self.config.initial_capital
                    
    def _recover_state(self):
        """Recover from saved state and sync with exchange"""
        try:
            # Load saved state
            saved_positions = self.state_store.load_positions()
            saved_orders = self.state_store.load_orders()
            
            # Load today's P&L
            today = date.today().isoformat()
            self.daily_pnl = self.state_store.load_daily_pnl(today)
            
            self.logger.info(f"Loaded state: {len(saved_positions)} positions, {len(saved_orders)} orders")
            
            # Sync positions with exchange
            self.logger.info("Synchronizing positions with exchange...")
            self.positions = self.position_sync.sync_positions(
                self.config.symbols,
                saved_positions
            )
            
            # Log discovered positions
            active_positions = {k: v for k, v in self.positions.items() if abs(v.get('size', 0)) > 0.0001}
            if active_positions:
                self.logger.warning(f"Found {len(active_positions)} existing positions:")
                for symbol, pos in active_positions.items():
                    side = pos.get('side', 'unknown')
                    size = pos.get('size', 0)
                    entry_price = pos.get('entry_price', 'unknown')
                    self.logger.warning(f"  {symbol}: {side} {abs(size)} @ {entry_price}")
            else:
                self.logger.info("No existing positions found")
            
            # Restore orders (only keeping recent ones)
            self.orders = saved_orders
            
            self.logger.info(f"State recovery complete: {len(active_positions)} active positions")
            
        except Exception as e:
            self.logger.error(f"State recovery failed: {e}")
            # Continue with empty state
            self.positions = {}
            self.orders = {}
            
    def run_trading_cycle(self, symbol: str, strategy):
        """Enhanced trading cycle with error recovery"""
        try:
            # Safety checks
            if self.emergency_stop:
                self.logger.error("Emergency stop active - no trading")
                return
                
            if abs(self.daily_pnl) > self.daily_loss_limit:
                self.logger.error(f"Daily loss limit reached: {self.daily_pnl}")
                self.emergency_stop = True
                alert_message = f"*** EMERGENCY STOP: Daily loss limit reached!\nDaily P&L: {self.daily_pnl:.2f} USDT\nLimit: {self.daily_loss_limit:.2f} USDT\nTrading halted."
                self.alert_system.send_alert(alert_message, "error")
                return
                
            # Get data with retry
            df = self._get_data_with_retry(symbol)
            if df is None or len(df) < strategy.min_bars_required:
                self.logger.warning(f"Insufficient data for {symbol}")
                return
                
            # Generate signals
            signals = strategy.generate_signals(df)
            latest_signal = signals['signal'].iloc[-1]  # Extract just the signal value

            self.logger.info("Latest signal", extra={'signal': latest_signal})
            
            # Get current market state
            ticker = self._fetch_ticker_with_retry(symbol)
            if ticker is None:
                return
                
            current_price = ticker['last']
            
            # Log current price with structured data
            self.logger.info(
                "Current market price",
                extra={
                    'symbol': symbol,
                    'current_price': current_price,
                    'bid': ticker.get('bid'),
                    'ask': ticker.get('ask'),
                    'volume': ticker.get('baseVolume'),
                    'timestamp': ticker.get('timestamp')
                }
            )
            
            # Get or sync position
            current_position = self._get_or_sync_position(symbol)
            
            # Debug log the current position
            self.logger.debug(
                "Current position retrieved",
                extra={
                    'symbol': symbol,
                    'current_position': current_position
                }
            )
            
            # Determine action
            action = self._determine_action(
                current_position, latest_signal, current_price, strategy
            )
            
            # Debug log the action decision
            self.logger.debug(
                "Action determined",
                extra={
                    'symbol': symbol,
                    'action': action,
                    'will_execute': action['type'] != 'hold'
                }
            )
            
            # Execute if needed
            if action['type'] != 'hold':
                self.logger.debug(
                    "Executing action",
                    extra={
                        'symbol': symbol,
                        'action': action,
                        'current_price': current_price
                    }
                )
                self._execute_action_safe(symbol, action, current_price, strategy)
            else:
                self.logger.debug(
                    "Holding position, no action to execute",
                    extra={'symbol': symbol}
                )
                
            # Save state after each cycle
            self._save_current_state()
            
        except ccxt.RateLimitExceeded:
            self.logger.error(f"Rate limit exceeded for {symbol}")
            time.sleep(60)
        except ccxt.NetworkError as e:
            self.logger.error(f"Network error for {symbol}: {e}")
            time.sleep(5)
        except Exception as e:
            self.logger.error(f"Unexpected error for {symbol}: {e}", exc_info=True)
            
    def _get_data_with_retry(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get data with retry logic"""
        for attempt in range(self.max_retries):
            try:
                return self.data_manager.get_data_for_signals(
                    symbol, self.exchange, self.config.timeframe
                )
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"Data fetch attempt {attempt + 1} failed: {e}")
                    time.sleep(self.retry_delays[attempt])
                else:
                    self.logger.error(f"Failed to get data after {self.max_retries} attempts")
                    return None
                    
    @measure_api_latency('ccxt_fetch_ticker', 'GET')
    def _fetch_ticker_with_retry(self, symbol: str) -> Optional[dict]:
        """Fetch ticker with retry logic"""
        for attempt in range(self.max_retries):
            try:
                return self.exchange.fetch_ticker(symbol)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delays[attempt])
                else:
                    self.logger.error(f"Failed to fetch ticker after {self.max_retries} attempts")
                    return None
                    
    def _get_or_sync_position(self, symbol: str) -> dict:
        """Get position, syncing with exchange if needed"""
        if symbol not in self.positions:
            # Try to sync this specific position
            try:
                balance = self.exchange.fetch_balance()
                base = symbol.split('/')[0]
                
                if base in balance and balance[base]['total'] > 0.0001:
                    self.positions[symbol] = {
                        'size': balance[base]['total'],
                        'entry_price': None,
                        'side': 'long',
                        'synchronized': True
                    }
                    self.logger.info(f"Found untracked position: {symbol} size={balance[base]['total']}")
                else:
                    self.positions[symbol] = {'size': 0, 'entry_price': None}
                    
            except Exception as e:
                self.logger.error(f"Failed to sync position for {symbol}: {e}")
                return {'size': 0}
                
        return self.positions.get(symbol, {'size': 0})
        
    def _determine_action(self, position: dict, signal: float, current_price: float, strategy) -> dict:
        """Determine what action to take based on position and signal"""
        position_size = position.get('size', 0)
        strategy_name = self.config.strategy_name
        
        # Debug logging at the start
        self.logger.debug(
            "Determining action",
            extra={
                'strategy_name': strategy_name,
                'position_size': position_size,
                'signal': signal,
                'current_price': current_price,
                'position_dict': position
            }
        )
        
        # Normal strategy logic
        self.logger.debug(
            "Processing normal strategy logic",
            extra={
                'position_size': position_size,
                'signal': signal,
                'allow_short': getattr(self.config, 'allow_short', False)
            }
        )
        
        # No position
        if position_size == 0 or position_size < 0.0001:
            self.logger.debug("No position, checking for entry signals")
            if signal > 0:
                size = self._calculate_position_size(current_price, strategy)
                action = {'type': 'open_long', 'size': size}
                self.logger.debug(
                    "Normal strategy action: opening long position",
                    extra={'action': action}
                )
                return action
            elif signal < 0 and self.config.allow_short:  # Only if shorting is allowed
                size = self._calculate_position_size(current_price, strategy)
                action = {'type': 'open_short', 'size': -size}
                self.logger.debug(
                    "Normal strategy action: opening short position",
                    extra={'action': action}
                )
                return action
            else:
                self.logger.debug(
                    "No entry signal or shorting not allowed",
                    extra={
                        'signal': signal,
                        'allow_short': getattr(self.config, 'allow_short', False)
                    }
                )
                
        # Long position
        elif position_size > 0:
            self.logger.debug("Have long position, checking for exit signals")
            if signal <= 0:  # Exit signal
                action = {'type': 'close_long', 'size': -position_size}
                self.logger.debug(
                    "Normal strategy action: closing long position (exit signal)",
                    extra={'action': action}
                )
                return action
            elif self._should_stop_loss(position, current_price):
                action = {'type': 'stop_loss', 'size': -position_size}
                self.logger.debug(
                    "Normal strategy action: stop loss triggered",
                    extra={'action': action}
                )
                return action
            else:
                self.logger.debug("Long position held, no exit signal")
                
        # Short position
        elif position_size < 0:
            self.logger.debug("Have short position, checking for exit signals")
            if signal >= 0:  # Exit signal
                action = {'type': 'close_short', 'size': -position_size}
                self.logger.debug(
                    "Normal strategy action: closing short position (exit signal)",
                    extra={'action': action}
                )
                return action
            elif self._should_stop_loss(position, current_price):
                action = {'type': 'stop_loss', 'size': -position_size}
                self.logger.debug(
                    "Normal strategy action: short stop loss triggered",
                    extra={'action': action}
                )
                return action
            else:
                self.logger.debug("Short position held, no exit signal")
                
        final_action = {'type': 'hold', 'size': 0}
        self.logger.debug(
            "Final action: holding",
            extra={'action': final_action}
        )
        return final_action
        
    def _calculate_position_size(self, current_price: float, strategy, stop_loss: float = None) -> float:
        """Calculate position size based on risk management rules"""
        # Get account balance
        try:
            account_info = self.position_sync.get_account_info()
            available_balance = account_info.get('balances', {}).get('USDT', {}).get('free', 0)
            if available_balance == 0:
                # Fallback to total USDT balance
                available_balance = account_info.get('total_balance_usdt', self.config.initial_capital * 0.1)
        except Exception as e:
            self.logger.warning(f"Could not get balance, using fallback: {e}")
            available_balance = self.config.initial_capital * 0.1  # Conservative fallback
            
        # Use risk manager for position sizing
        signal = 1  # For position sizing calculation
        position_size_ratio = self.risk_manager.calculate_position_size(
            signal=signal,
            current_price=current_price,
            equity=available_balance
        )
        
        # Convert ratio to actual quantity
        position_value = available_balance * position_size_ratio
        position_size = position_value / current_price
            
        return position_size
        
    def _should_stop_loss(self, position: dict, current_price: float) -> bool:
        """Check if stop loss should be triggered"""
        if not position.get('entry_price'):
            return False
            
        entry_price = position['entry_price']
        position_size = position['size']
        
        if position_size > 0:  # Long position
            loss_pct = (entry_price - current_price) / entry_price
        else:  # Short position
            loss_pct = (current_price - entry_price) / entry_price
            
        return loss_pct >= self.config.stop_loss_pct
        
    def _execute_action_safe(self, symbol: str, action: dict, current_price: float, strategy):
        """Execute action with comprehensive error handling"""
        order_id = f"{symbol}_{action['type']}_{int(time.time())}"
        
        try:
            # Pre-execution validation
            if not self._validate_order(symbol, action['size'], current_price):
                return
                
            # Create order tracking
            order = Order(
                id=order_id,
                symbol=symbol,
                side='buy' if action['size'] > 0 else 'sell',
                size=abs(action['size']),
                order_type='market',
                status=OrderStatus.PENDING,
                timestamp=datetime.now().isoformat()
            )
            self.orders[order_id] = asdict(order)
            
            # Execute order
            exchange_order = self._place_order_with_retry(symbol, action['size'])
            
            if exchange_order:
                # Update order tracking
                self.orders[order_id]['exchange_order_id'] = exchange_order['id']
                self.orders[order_id]['status'] = OrderStatus.PLACED.value
                
                # Log to database
                if self.db_logging_enabled:
                    try:
                        self.db_logger.log_trade(
                            trade_id=exchange_order['id'],
                            symbol=symbol,
                            side=order.side,
                            quantity=order.size,
                            price=exchange_order.get('price', current_price),
                            status='pending',
                            order_type='market',
                            strategy_name=self.config.strategy_name,
                            exchange=self.config.exchange_name,
                            metadata={
                                'internal_order_id': order_id,
                                'action': action,
                                'current_price': current_price
                            }
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to log trade to database: {e}")
                
                # Wait for fill
                filled_order = self._wait_for_fill(exchange_order['id'], symbol)
                
                if filled_order:
                    # Update position
                    self._update_position_from_order(symbol, filled_order, action['type'])
                    self.orders[order_id]['status'] = OrderStatus.FILLED.value
                    self.orders[order_id]['filled_size'] = filled_order.get('filled', filled_order.get('amount'))
                    self.orders[order_id]['average_price'] = filled_order.get('average', filled_order.get('price'))
                    
                    # Update database with filled order
                    if self.db_logging_enabled and filled_order is not None:
                        try:
                            # Extract fee information safely
                            fee_info = filled_order.get('fee', {}) or {}
                            commission = fee_info.get('cost', 0) if fee_info else 0
                            commission_asset = fee_info.get('currency') if fee_info else None
                            
                            self.db_logger.log_trade(
                                trade_id=exchange_order['id'],
                                symbol=symbol,
                                side=order.side,
                                quantity=filled_order.get('filled', order.size),
                                price=filled_order.get('average', current_price),
                                status='filled',
                                order_type='market',
                                strategy=getattr(self.config, 'strategy_name', None),
                                fee=commission,
                                fee_currency=commission_asset,
                                executed_at=datetime.now(),
                                metadata={
                                    'internal_order_id': order_id,
                                    'action': action,
                                    'filled_order': filled_order,
                                    'exchange': self.config.exchange_name
                                }
                            )
                            
                            # Update account balance after trade
                            self._update_account_balance_db()
                        except Exception as e:
                            self.logger.warning(f"Failed to update trade in database: {e}")
                    
                    self.logger.info(
                        f"Order filled: {action['type']} {symbol} "
                        f"size={filled_order.get('filled')} @ {filled_order.get('average')}"
                    )
                else:
                    self.orders[order_id]['status'] = OrderStatus.FAILED.value
                    
        except Exception as e:
            self.logger.error(f"Order execution failed: {e}")
            self.orders[order_id]['status'] = OrderStatus.FAILED.value
            self.orders[order_id]['error'] = str(e)
            
    def _validate_order(self, symbol: str, size: float, current_price: float) -> bool:
        """Validate order before execution"""
        try:
            # Check market info
            market = self.markets.get(symbol)
            if not market:
                self.logger.error(f"Market {symbol} not found")
                return False
                
            # Check minimum order size
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0)
            if abs(size) < min_amount:
                self.logger.error(f"Order size {abs(size)} below minimum {min_amount}")
                return False
                
            # Check precision
            amount_precision = market.get('precision', {}).get('amount', 8)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Order validation failed: {e}")
            return False
            
    @measure_api_latency('ccxt_place_order', 'POST')
    def _place_order_with_retry(self, symbol: str, size: float) -> Optional[dict]:
        """Place order with retry and error handling"""
        for attempt in range(self.max_retries):
            try:
                if size > 0:
                    order = self.exchange.create_market_buy_order(symbol, size)
                else:
                    order = self.exchange.create_market_sell_order(symbol, abs(size))
                    
                self.logger.info(f"Order placed: {order['id']} for {symbol}")
                return order
                
            except ccxt.InsufficientFunds as e:
                self.logger.error(f"Insufficient funds: {e}")
                return None
                
            except ccxt.InvalidOrder as e:
                self.logger.error(f"Invalid order: {e}")
                return None
                
            except ccxt.ExchangeNotAvailable as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"Exchange unavailable, retrying...")
                    time.sleep(self.retry_delays[attempt])
                else:
                    return None
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"Order attempt {attempt + 1} failed: {e}")
                    time.sleep(self.retry_delays[attempt])
                else:
                    return None
                    
    @measure_api_latency('ccxt_fetch_order', 'GET')
    def _wait_for_fill(self, order_id: str, symbol: str, timeout: int = 30) -> Optional[dict]:
        """Wait for order to fill with timeout"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                order = self.exchange.fetch_order(order_id, symbol)
                
                if order['status'] == 'closed':
                    return order
                elif order['status'] == 'canceled':
                    self.logger.warning(f"Order {order_id} was cancelled")
                    return None
                    
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error checking order status: {e}")
                time.sleep(2)
                
        self.logger.error(f"Order {order_id} timeout after {timeout}s")
        return None
        
    def _update_position_from_order(self, symbol: str, order: dict, action_type: str):
        """Update position based on filled order"""
        filled_size = order.get('filled', order.get('amount', 0))
        average_price = order.get('average', order.get('price', 0))
        
        if symbol not in self.positions:
            self.positions[symbol] = {'size': 0, 'entry_price': None}
            
        current_position = self.positions[symbol]
        
        if action_type in ['open_long', 'open_short']:
            # New position
            position_size = filled_size if 'long' in action_type else -filled_size
            self.positions[symbol] = {
                'size': position_size,
                'entry_price': average_price,
                'side': 'long' if 'long' in action_type else 'short',
                'entry_time': datetime.now().isoformat()
            }
            
            # Log position to database
            if self.db_logging_enabled:
                try:
                    self.db_logger.update_position(
                        symbol=symbol,
                        quantity=position_size,
                        entry_price=average_price,
                        side='long' if 'long' in action_type else 'short',
                        strategy=getattr(self.config, 'strategy_name', None),
                        metadata={
                            'action_type': action_type,
                            'entry_time': datetime.now().isoformat(),
                            'exchange': self.config.exchange_name
                        }
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to log position to database: {e}")
            
            # Send trade alert
            side_text = "LONG" if 'long' in action_type else "SHORT"
            alert_message = f"🎯 Trade Executed: {side_text} {symbol}\nSize: {filled_size:.6f}\nPrice: ${average_price:.2f}\nExchange: {self.config.exchange_name.upper()}"
            self.alert_system.send_alert(alert_message, "info")
        else:
            # Closing position - calculate P&L
            if current_position.get('entry_price'):
                if current_position['size'] > 0:  # Was long
                    pnl = (average_price - current_position['entry_price']) * filled_size
                else:  # Was short
                    pnl = (current_position['entry_price'] - average_price) * filled_size
                    
                # Consider fees
                fee_amount = filled_size * average_price * self.config.commission
                net_pnl = pnl - fee_amount
                
                self.daily_pnl += net_pnl
                self.logger.info(f"Position closed: P&L = {net_pnl:.2f} USDT")
                
                # Send position close alert
                pnl_indicator = "PROFIT" if net_pnl > 0 else "LOSS"
                alert_message = f"Position Closed ({pnl_indicator}): {symbol}\nSize: {filled_size:.6f}\nClose Price: ${average_price:.2f}\nP&L: {net_pnl:.2f} USDT\nDaily P&L: {self.daily_pnl:.2f} USDT"
                alert_level = "info" if net_pnl > 0 else "warning" if net_pnl > -100 else "error"
                self.alert_system.send_alert(alert_message, alert_level)
                
            # Clear position
            self.positions[symbol] = {'size': 0, 'entry_price': None}
            
            # Log position close to database
            if self.db_logging_enabled:
                try:
                    self.db_logger.update_position(
                        symbol=symbol,
                        quantity=0,
                        entry_price=current_position.get('entry_price', average_price),
                        side=current_position.get('side', 'long'),
                        strategy=getattr(self.config, 'strategy_name', None),
                        metadata={
                            'action_type': action_type,
                            'close_time': datetime.now().isoformat(),
                            'close_price': average_price,
                            'pnl': net_pnl if 'net_pnl' in locals() else 0,
                            'exchange': self.config.exchange_name
                        }
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to log position close to database: {e}")
            
    def _save_current_state(self):
        """Save current state to disk"""
        try:
            self.logger.debug(
                "Saving current state...",
                extra={
                    'positions_count': len(self.positions),
                    'orders_count': len(self.orders),
                    'daily_pnl': self.daily_pnl,
                    'storage_backend': getattr(self.state_store, 'get_storage_info', lambda: {'primary_store': 'SimpleFileStore'})().get('primary_store')
                }
            )
            
            self.state_store.save_positions(self.positions)
            self.state_store.save_orders(self.orders)
            self.state_store.save_daily_pnl(date.today().isoformat(), self.daily_pnl)
            
            # Save checkpoint
            checkpoint = {
                'positions': self.positions,
                'orders': self.orders,
                'daily_pnl': self.daily_pnl,
                'emergency_stop': self.emergency_stop,
                'timestamp': datetime.now().isoformat()
            }
            self.state_store.save_checkpoint(checkpoint)
            
            self.logger.debug(
                "State saved successfully",
                extra={
                    'storage_backend': getattr(self.state_store, 'get_storage_info', lambda: {'primary_store': 'SimpleFileStore'})().get('primary_store')
                }
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to save state",
                extra={
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'storage_backend': getattr(self.state_store, 'get_storage_info', lambda: {'primary_store': 'SimpleFileStore'})().get('primary_store')
                }
            )
            
    def _get_cache_duration(self) -> int:
        """Get appropriate cache duration based on timeframe"""
        # Convert timeframe to seconds and use half of it for cache
        timeframe_seconds = self.data_manager.get_timeframe_seconds(self.config.timeframe)
        return max(60, timeframe_seconds // 2)  # At least 60 seconds
        
    def _update_account_balance_db(self):
        """Update account balance in database"""
        if not self.db_logging_enabled:
            self.logger.debug(
                "Database logging disabled, skipping balance update",
                extra={'db_logging_enabled': self.db_logging_enabled}
            )
            return
            
        try:
            # Get current account info
            account_info = self.position_sync.get_account_info()
            self.logger.debug(
                "Retrieved account info for balance update",
                extra={
                    'account_info_keys': list(account_info.keys()),
                    'balances_count': len(account_info.get('balances', {}))
                }
            )
            
            # Update USDT balance (primary trading currency)
            usdt_balance = account_info.get('balances', {}).get('USDT', {})
            if usdt_balance:
                self.logger.debug(
                    "Updating USDT balance in database",
                    extra={
                        'usdt_free': usdt_balance.get('free', 0),
                        'usdt_used': usdt_balance.get('used', 0),
                        'usdt_total': usdt_balance.get('total', 0)
                    }
                )
                self.db_logger.log_balance(
                    account_id=self.config.exchange_name,
                    total_balance=usdt_balance.get('total', 0),
                    free_balance=usdt_balance.get('free', 0),
                    used_balance=usdt_balance.get('used', 0),
                    currency='USDT',
                    metadata={'exchange': self.config.exchange_name}
                )
            
            # Update other significant balances
            for asset, balance in account_info.get('balances', {}).items():
                if asset != 'USDT' and balance.get('total', 0) > 0.001:  # Only log non-zero balances
                    self.logger.debug(
                        "Updating non-USDT balance in database",
                        extra={
                            'asset': asset,
                            'free': balance.get('free', 0),
                            'used': balance.get('used', 0),
                            'total': balance.get('total', 0)
                        }
                    )
                    self.db_logger.log_balance(
                        account_id=self.config.exchange_name,
                        total_balance=balance.get('total', 0),
                        free_balance=balance.get('free', 0),
                        used_balance=balance.get('used', 0),
                        currency=asset,
                        metadata={'exchange': self.config.exchange_name}
                    )
                    
        except Exception as e:
            self.logger.error(
                "Failed to update account balance in database",
                extra={
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'db_logging_enabled': self.db_logging_enabled
                }
            )
        
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get current performance summary"""
        try:
            account_info = self.position_sync.get_account_info()
            current_balance = account_info.get('total_balance_usdt', self.initial_balance)
            
            return {
                "initial_balance": self.initial_balance,
                "current_balance": current_balance,
                "daily_pnl": self.daily_pnl,
                "total_pnl": current_balance - self.initial_balance if self.initial_balance else 0,
                "open_positions": len([p for p in self.positions.values() if p.get('size', 0) != 0]),
                "emergency_stop": self.emergency_stop,
                "mode": "SANDBOX" if self.config.use_sandbox else "LIVE"
            }
        except Exception as e:
            self.logger.error(f"Failed to get performance summary: {e}")
            return {}