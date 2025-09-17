"""
IBKR trader implementation with comprehensive risk management integration.
"""

import asyncio
import time
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd

from ib_async import IB, Stock, Forex, MarketOrder, LimitOrder, Order, Trade, Position, AccountValue
from framework.utils.logger import get_logger
from framework.utils.simple_state_store import SimpleStateStore
from framework.monitoring.alert_system import AlertSystem
from framework.risk.fixed_position_size_manager import FixedPositionSizeManager
from framework.risk.fixed_risk_manager import FixedRiskManager
from framework.risk.strategy_position_size_manager import StrategyPositionSizeManager
from .ibkr_config import IBKRConfig, IBKRAccountType, IBKRMarketDataType
from .ibkr_connection import IBKRConnectionManager


class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ERROR = "error"


class IBKRTrader:
    """
    Professional IBKR trader with risk management integration.
    
    Features:
    - Risk management integration (fixed position, fixed risk, strategy-based)
    - Position synchronization with IBKR accounts
    - Order management with real-time status tracking
    - Market data integration (real-time, delayed, historical)
    - Paper and live trading support
    - State persistence and recovery
    - Alert system integration
    - Comprehensive error handling and reconnection
    """
    
    def __init__(self, config):
        """Initialize IBKR trader with configuration"""
        self.config = config
        self.logger = get_logger(f"{__name__}.{config.exchange_name}")
        
        # IBKR-specific configuration
        self.ibkr_config = IBKRConfig.from_env()
        
        # Connection manager
        self.connection = IBKRConnectionManager(self.ibkr_config)
        self.ib = self.connection.ib
        
        # State management
        self.state_store = SimpleStateStore(f"ibkr_{config.exchange_name}_{config.timeframe}")
        self.positions = {}
        self.orders = {}
        
        # Risk management
        self.risk_manager = self._initialize_risk_manager(config)
        self.daily_pnl = 0.0
        self.initial_balance = None
        self.emergency_stop = False
        self.daily_loss_limit = getattr(config, 'daily_loss_limit', 1000.0)
        
        # Alert system
        self.alert_system = AlertSystem(config)
        
        # Market data cache
        self.market_data_cache = {}
        self.last_data_update = {}
        
        # Order tracking
        self.pending_orders = {}
        self.order_counter = 0
        
        self.logger.info(f"IBKR trader initialized: {self.ibkr_config}")
        self.logger.info(f"Risk Manager: {self.risk_manager.get_description()}")
    
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
            self.logger.warning(f"Unknown risk manager type: {risk_manager_type}, using fixed_position")
            risk_manager = FixedPositionSizeManager(position_size=0.1)
        
        return risk_manager
    
    async def initialize(self) -> bool:
        """Initialize IBKR trader and establish connection"""
        try:
            # Connect to IBKR
            if not await self.connection.connect():
                self.logger.error("Failed to connect to IBKR")
                return False
            
            # Set market data type
            await self._set_market_data_type()
            
            # Load state
            await self._load_state()
            
            # Synchronize positions
            await self._sync_positions()
            
            # Get account information
            await self._update_account_info()
            
            self.logger.info("IBKR trader initialization complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize IBKR trader: {e}")
            return False
    
    async def _set_market_data_type(self):
        """Set market data type for subscriptions"""
        try:
            self.ib.reqMarketDataType(self.ibkr_config.market_data_type.value)
            self.logger.info(f"Market data type set to: {self.ibkr_config.market_data_type.name}")
            await asyncio.sleep(0.1)  # Allow request to process
        except Exception as e:
            self.logger.error(f"Failed to set market data type: {e}")
    
    async def _load_state(self):
        """Load trader state from storage"""
        try:
            state = self.state_store.load_state()
            if state:
                self.positions = state.get('positions', {})
                self.orders = state.get('orders', {})
                self.daily_pnl = state.get('daily_pnl', 0.0)
                self.logger.info(f"State loaded: {len(self.positions)} positions, {len(self.orders)} orders")
            else:
                self.logger.info("No previous state found")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
    
    async def _save_state(self):
        """Save trader state to storage"""
        try:
            state = {
                'positions': self.positions,
                'orders': self.orders,
                'daily_pnl': self.daily_pnl,
                'timestamp': time.time()
            }
            self.state_store.save_state(state)
            self.logger.debug("State saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
    
    async def _sync_positions(self):
        """Synchronize positions with IBKR account"""
        try:
            await self.connection.rate_limit()
            positions = self.ib.positions()
            
            self.logger.info(f"Synchronizing {len(positions)} positions from IBKR")
            
            for pos in positions:
                if abs(pos.position) > 0:  # Only active positions
                    symbol = self._contract_to_symbol(pos.contract)
                    
                    self.positions[symbol] = {
                        'size': float(pos.position),
                        'entry_price': float(pos.avgCost) if pos.avgCost else 0.0,
                        'market_value': float(pos.marketValue) if pos.marketValue else 0.0,
                        'unrealized_pnl': float(pos.unrealizedPNL) if pos.unrealizedPNL else 0.0,
                        'contract': pos.contract,
                        'last_update': time.time()
                    }
                    
                    self.logger.info(f"Position sync: {symbol} size={pos.position} avgCost={pos.avgCost}")
            
            await self._save_state()
            
        except Exception as e:
            self.logger.error(f"Failed to sync positions: {e}")
    
    async def _update_account_info(self):
        """Update account information and balance"""
        try:
            await self.connection.rate_limit()
            
            # Request account updates
            if self.ibkr_config.account_id:
                account_id = self.ibkr_config.account_id
            else:
                accounts = self.ib.managedAccounts()
                account_id = accounts[0] if accounts else None
            
            if not account_id:
                self.logger.error("No account ID available")
                return
            
            # Get account values
            account_values = self.ib.accountValues(account=account_id)
            
            for av in account_values:
                if av.tag == 'NetLiquidation' and av.currency == 'USD':
                    balance = float(av.value)
                    if self.initial_balance is None:
                        self.initial_balance = balance
                        self.logger.info(f"Initial balance set: ${balance:,.2f}")
                    break
            
        except Exception as e:
            self.logger.error(f"Failed to update account info: {e}")
    
    def _contract_to_symbol(self, contract) -> str:
        """Convert IBKR contract to symbol string"""
        if contract.secType == 'FOREX':
            return f"{contract.symbol}/{contract.currency}"
        else:
            return contract.symbol
    
    def _symbol_to_contract(self, symbol: str):
        """Convert symbol to IBKR contract"""
        # Handle forex pairs
        if '/' in symbol:
            base, quote = symbol.split('/')
            return Forex(f"{base}{quote}")
        else:
            # Default to stock
            return Stock(symbol, 'SMART', 'USD')
    
    async def get_market_data(self, symbol: str, timeframe: str, lookback: int = 100) -> Optional[pd.DataFrame]:
        """
        Get historical market data from IBKR
        
        Args:
            symbol: Trading symbol
            timeframe: Data timeframe (1m, 5m, 15m, 1h, 4h, 1D)
            lookback: Number of bars to retrieve
            
        Returns:
            DataFrame with OHLCV data or None if failed
        """
        try:
            await self.connection.rate_limit()
            
            # Check cache
            cache_key = f"{symbol}_{timeframe}"
            now = time.time()
            
            if (cache_key in self.market_data_cache and 
                cache_key in self.last_data_update and
                now - self.last_data_update[cache_key] < 30):  # 30 second cache
                return self.market_data_cache[cache_key]
            
            # Create contract
            contract = self._symbol_to_contract(symbol)
            
            # Request historical data
            duration = f"{lookback} D" if timeframe in ['1D', '4h'] else f"{lookback * 2} H"
            bar_size = self._timeframe_to_bar_size(timeframe)
            
            bars = self.ib.reqHistoricalData(
                contract=contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='MIDPOINT',
                useRTH=True,
                formatDate=1,
                timeout=self.ibkr_config.historical_data_timeout
            )
            
            if not bars:
                self.logger.warning(f"No historical data received for {symbol}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame([{
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close),
                'volume': int(bar.volume)
            } for bar in bars])
            
            # Set datetime index
            df.index = pd.to_datetime([bar.date for bar in bars])
            df.index.name = 'datetime'
            
            # Cache the data
            self.market_data_cache[cache_key] = df
            self.last_data_update[cache_key] = now
            
            return df.tail(lookback)  # Return only requested number of bars
            
        except Exception as e:
            self.logger.error(f"Failed to get market data for {symbol}: {e}")
            return None
    
    def _timeframe_to_bar_size(self, timeframe: str) -> str:
        """Convert timeframe to IBKR bar size"""
        mapping = {
            '1m': '1 min',
            '5m': '5 mins',
            '15m': '15 mins',
            '30m': '30 mins',
            '1h': '1 hour',
            '4h': '4 hours',
            '1D': '1 day'
        }
        return mapping.get(timeframe, '1 min')
    
    async def execute_trade(self, symbol: str, signal: int, current_price: float, strategy) -> bool:
        """
        Execute trade based on strategy signal
        
        Args:
            symbol: Trading symbol
            signal: Trading signal (1=buy, -1=sell, 0=hold)
            current_price: Current market price
            strategy: Strategy instance
            
        Returns:
            bool: True if trade executed successfully
        """
        try:
            if self.emergency_stop:
                self.logger.warning("Emergency stop active - no new trades")
                return False
            
            # Check daily loss limit
            if abs(self.daily_pnl) > self.daily_loss_limit:
                self.logger.error(f"Daily loss limit reached: {self.daily_pnl}")
                self.emergency_stop = True
                if self.alert_system:
                    alert_message = f"*** EMERGENCY STOP: Daily loss limit reached!\nDaily P&L: {self.daily_pnl:.2f} USD\nLimit: {self.daily_loss_limit:.2f} USD\nTrading halted."
                    self.alert_system.send_alert(alert_message, "error")
                return False
            
            current_position = self.positions.get(symbol, {'size': 0, 'entry_price': None})
            position_size = current_position['size']
            
            # Determine action
            action = self._determine_action(current_position, signal, current_price, strategy)
            
            if action['action'] == 'hold':
                return True
            
            # Execute the order
            return await self._execute_order(symbol, action, current_price)
            
        except Exception as e:
            self.logger.error(f"Failed to execute trade for {symbol}: {e}")
            return False
    
    def _determine_action(self, position: dict, signal: float, current_price: float, strategy) -> dict:
        """Determine what action to take based on position and signal"""
        position_size = position.get('size', 0)
        strategy_name = self.config.strategy_name
        
        # No position - enter based on signal
        if position_size == 0:
            if signal == 1:
                return {'action': 'buy', 'reason': f'{strategy_name}: Buy signal'}
            elif signal == -1:
                return {'action': 'sell', 'reason': f'{strategy_name}: Sell signal'}
            else:
                return {'action': 'hold', 'reason': 'No signal'}
        
        # Long position
        elif position_size > 0:
            if signal == -1:
                return {'action': 'sell', 'reason': f'{strategy_name}: Exit long position'}
            elif signal == 1:
                return {'action': 'hold', 'reason': 'Already long'}
            else:
                return {'action': 'hold', 'reason': 'Holding long position'}
        
        # Short position
        elif position_size < 0:
            if signal == 1:
                return {'action': 'buy', 'reason': f'{strategy_name}: Cover short position'}
            elif signal == -1:
                return {'action': 'hold', 'reason': 'Already short'}
            else:
                return {'action': 'hold', 'reason': 'Holding short position'}
        
        return {'action': 'hold', 'reason': 'Unknown state'}
    
    async def _execute_order(self, symbol: str, action: dict, current_price: float) -> bool:
        """Execute an order through IBKR"""
        try:
            contract = self._symbol_to_contract(symbol)
            
            # Calculate position size
            if action['action'] in ['buy', 'sell']:
                current_position = self.positions.get(symbol, {'size': 0})
                
                if current_position['size'] == 0:  # Opening position
                    quantity = await self._calculate_position_size(symbol, current_price)
                    if action['action'] == 'sell':
                        quantity = -quantity  # Short position
                else:  # Closing position
                    quantity = -current_position['size']  # Close full position
                
                if abs(quantity) < 0.001:  # Minimum position size
                    self.logger.warning(f"Position size too small: {quantity}")
                    return False
                
                # Create order
                order = MarketOrder('BUY' if quantity > 0 else 'SELL', abs(quantity))
                
                # Submit order
                await self.connection.rate_limit()
                trade = self.ib.placeOrder(contract, order)
                
                # Track order
                order_id = f"ibkr_{int(time.time())}_{self.order_counter}"
                self.order_counter += 1
                
                self.pending_orders[order_id] = {
                    'trade': trade,
                    'symbol': symbol,
                    'action': action['action'],
                    'quantity': quantity,
                    'price': current_price,
                    'timestamp': time.time(),
                    'reason': action['reason']
                }
                
                self.logger.info(f"Order submitted: {action['action']} {abs(quantity)} {symbol} @ ${current_price:.2f} - {action['reason']}")
                
                # Wait for order status
                await asyncio.sleep(0.5)
                await self._check_order_status(order_id)
                
                await self._save_state()
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to execute order: {e}")
            return False
    
    async def _calculate_position_size(self, symbol: str, current_price: float) -> float:
        """Calculate position size using risk manager"""
        try:
            # Get account balance
            if self.initial_balance:
                available_balance = self.initial_balance
            else:
                available_balance = self.config.initial_capital
            
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
            
        except Exception as e:
            self.logger.error(f"Failed to calculate position size: {e}")
            return 0.0
    
    async def _check_order_status(self, order_id: str):
        """Check and update order status"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order_info = self.pending_orders[order_id]
            trade = order_info['trade']
            
            # Check if order is filled
            if trade.orderStatus.status == 'Filled':
                filled_qty = trade.orderStatus.filled
                avg_price = trade.orderStatus.avgFillPrice
                
                # Update position
                symbol = order_info['symbol']
                if symbol not in self.positions:
                    self.positions[symbol] = {'size': 0, 'entry_price': None}
                
                old_size = self.positions[symbol]['size']
                new_size = old_size + (filled_qty if order_info['action'] == 'buy' else -filled_qty)
                
                if abs(new_size) < 0.001:  # Position closed
                    # Calculate PnL
                    if old_size != 0 and self.positions[symbol]['entry_price']:
                        pnl = (avg_price - self.positions[symbol]['entry_price']) * abs(old_size)
                        if old_size < 0:  # Short position
                            pnl = -pnl
                        self.daily_pnl += pnl
                        
                        pnl_indicator = "PROFIT" if pnl > 0 else "LOSS"
                        self.logger.info(f"Position closed: {symbol} P&L = {pnl_indicator} ${pnl:.2f}")
                    
                    self.positions[symbol] = {'size': 0, 'entry_price': None}
                else:
                    # Position opened/modified
                    if abs(old_size) < 0.001:  # New position
                        self.positions[symbol]['entry_price'] = avg_price
                    self.positions[symbol]['size'] = new_size
                
                # Remove from pending orders
                del self.pending_orders[order_id]
                
                self.logger.info(f"Order filled: {order_info['action']} {filled_qty} {symbol} @ ${avg_price:.2f}")
                
            elif trade.orderStatus.status in ['Cancelled', 'ApiCancelled']:
                self.logger.warning(f"Order cancelled: {order_id}")
                del self.pending_orders[order_id]
                
        except Exception as e:
            self.logger.error(f"Failed to check order status: {e}")
    
    async def cleanup(self):
        """Cleanup trader resources"""
        try:
            await self._save_state()
            await self.connection.disconnect()
            self.logger.info("IBKR trader cleanup complete")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def get_positions(self) -> Dict[str, Dict]:
        """Get current positions"""
        return self.positions.copy()
    
    def get_balance(self) -> float:
        """Get current account balance"""
        return self.initial_balance or self.config.initial_capital
    
    def get_daily_pnl(self) -> float:
        """Get daily P&L"""
        return self.daily_pnl
    
    def is_emergency_stop(self) -> bool:
        """Check if emergency stop is active"""
        return self.emergency_stop