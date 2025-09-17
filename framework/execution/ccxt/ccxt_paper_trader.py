"""
CCXT Paper Trader - Real market data with simulated trading
"""
import time
import ccxt
import pandas as pd
from datetime import datetime, date
from typing import Dict, Optional, Any, List
import logging
from enum import Enum
from dataclasses import dataclass, asdict

from framework.utils.simple_state_store import SimpleStateStore
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


class CCXTPaperTrader:
    """Paper trader using CCXT for real market data with simulated trading"""
    
    def __init__(self, config):
        self.config = config
        self.logger = get_logger("TradingBot.paper_trader")
        
        # State management
        self.logger.info(
            "Initializing paper trader state store...",
            extra={
                'exchange': self.config.exchange_name.upper(),
                'initial_capital': self.config.initial_capital
            }
        )
        self.state_store = SimpleStateStore(exchange=self.config.exchange_name.upper())
        
        # Safety settings
        self.emergency_stop = False
        self.max_retries = 3
        self.retry_delays = [1, 5, 15]
        self.daily_loss_limit = config.initial_capital * 0.02  # 2% daily loss limit
        
        # Virtual portfolio state
        self.positions = {}
        self.orders = {}
        self.daily_pnl = 0.0
        self.initial_balance = config.initial_capital
        self.current_balance = config.initial_capital
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        
        # Legacy position sizing setting (now handled by risk manager)
        self.max_position_pct = config.max_position_size
        
        # Alert system
        self.alert_system = AlertSystem(config)
        
        # Trading mode configuration
        self.trading_type = getattr(config, 'trading_type', 'future')
        self.allow_shorting = getattr(config, 'allow_shorting', True)
        
        # Commission and slippage simulation
        self.commission_rate = getattr(config, 'commission', 0.001)
        self.slippage_rate = getattr(config, 'slippage', 0.0005)
        
        # Initialize risk manager
        self.risk_manager = self._initialize_risk_manager(config)
        
        # Try to acquire lock
        lock_id = f"paper_trader_{config.exchange_name}_{config.timeframe}_{date.today().isoformat()}"
        if not self.state_store.acquire_lock(lock_id):
            raise RuntimeError("Another paper trader instance is already running!")
        self.lock_id = lock_id
        
        # Initialize exchange connection (for data only)
        self._initialize_exchange()
        
        # Load previous state
        self._load_state()
        
        self.logger.info(f"Paper trader initialized with ${self.initial_balance:.2f} virtual capital")
    
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
    
    def _initialize_exchange(self):
        """Initialize CCXT exchange for market data (no API keys needed)"""
        for attempt in range(self.max_retries):
            try:
                self.logger.info(
                    "Connecting to exchange for market data...",
                    extra={
                        'exchange': self.config.exchange_name,
                        'attempt': attempt + 1
                    }
                )
                
                # Initialize exchange without API keys (for market data only)
                exchange_class = getattr(ccxt, self.config.exchange_name.lower())
                self.exchange = exchange_class({
                    'sandbox': self.config.use_sandbox,
                    'enableRateLimit': True,
                    'timeout': 30000,
                })
                
                # Load markets
                self.exchange.load_markets()
                
                self.logger.info(
                    f"Exchange connected: {self.config.exchange_name} "
                    f"{'SANDBOX' if self.config.use_sandbox else 'LIVE'} mode, "
                    f"{len(self.exchange.markets)} markets loaded"
                )
                return
                
            except Exception as e:
                self.logger.error(f"Exchange connection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delays[attempt])
                else:
                    raise ConnectionError(f"Failed to connect to {self.config.exchange_name} after {self.max_retries} attempts")
    
    def _load_state(self):
        """Load previous paper trading state"""
        try:
            # Load positions
            saved_positions = self.state_store.load_positions()
            self.positions = saved_positions if saved_positions else {}
            
            # Load orders
            saved_orders = self.state_store.load_orders()
            self.orders = saved_orders if saved_orders else {}
            
            # Load daily P&L
            today = date.today().isoformat()
            self.daily_pnl = self.state_store.load_daily_pnl(today)
            
            self.logger.info(
                f"Loaded state: {len(self.positions)} positions, {len(self.orders)} orders, "
                f"daily P&L: ${self.daily_pnl:.2f}"
            )
            
        except Exception as e:
            self.logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Save current paper trading state"""
        try:
            self.state_store.save_positions(self.positions)
            self.state_store.save_orders(self.orders)
            
            today = date.today().isoformat()
            self.state_store.save_daily_pnl(today, self.daily_pnl)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
    
    def get_market_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Get real market data from CCXT"""
        try:
            # Fetch OHLCV data
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            if not ohlcv:
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
            
        except Exception as e:
            self.logger.error(f"Failed to fetch market data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_current_price(self, symbol: str) -> float:
        """Get current market price"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            self.logger.error(f"Failed to get current price for {symbol}: {e}")
            return 0.0
    
    def run_trading_cycle(self, symbol: str, strategy):
        """Run one trading cycle with paper trading simulation"""
        try:
            # Safety checks
            if self.emergency_stop:
                self.logger.error("Emergency stop active - no trading")
                return
                
            if abs(self.daily_pnl) > self.daily_loss_limit:
                self.logger.error(f"Daily loss limit reached: {self.daily_pnl}")
                self.emergency_stop = True
                if self.alert_system:
                    alert_message = f"*** EMERGENCY STOP: Daily loss limit reached!\nDaily P&L: {self.daily_pnl:.2f} USDT\nLimit: {self.daily_loss_limit:.2f} USDT\nTrading halted."
                    self.alert_system.send_alert(alert_message, "error")
                return
            
            # Get market data - use strategy's minimum requirement for deterministic behavior
            bars_needed = max(strategy.min_bars_required, 20)  # At least 20 for context
            df = self.get_market_data(symbol, self.config.timeframe, bars_needed)
            if df is None or len(df) < strategy.min_bars_required:
                self.logger.warning(f"Insufficient data for {symbol}")
                return
            
            # Generate signals
            signals = strategy.generate_signals(df)
            if signals.empty or 'signal' not in signals.columns:
                self.logger.warning(f"No signals generated for {symbol}")
                return
                
            latest_signal = signals['signal'].iloc[-1]
            current_price = self.get_current_price(symbol)
            
            # Log current status
            self.logger.info(
                "Current market data",
                extra={
                    'symbol': symbol,
                    'current_price': current_price,
                    'signal': latest_signal,
                    'balance': self.current_balance,
                    'daily_pnl': self.daily_pnl
                }
            )
            
            # Execute paper trading logic
            self._execute_paper_trade(symbol, latest_signal, current_price)
            
            # Update P&L
            self._update_unrealized_pnl()
            
            # Save state
            self._save_state()
            
        except Exception as e:
            self.logger.error(f"Trading cycle error for {symbol}: {e}", exc_info=True)
    
    def _execute_paper_trade(self, symbol: str, signal: int, current_price: float):
        """Execute simulated trade based on signal"""
        position = self.positions.get(symbol, {'size': 0, 'entry_price': None})
        current_size = position['size']
        
        if signal == 1:  # Buy signal
            if current_size == 0:  # No position - open long
                self._simulate_buy(symbol, current_price)
            elif current_size < 0:  # Short position - close short
                self._simulate_buy_to_cover(symbol, current_price)
        elif signal == -1:  # Sell signal
            if current_size > 0:  # Long position - close long
                self._simulate_sell(symbol, current_price)
            elif current_size == 0 and self.allow_shorting:  # No position - open short
                self._simulate_short(symbol, current_price)
            elif current_size == 0 and not self.allow_shorting:
                self.logger.info(f"Short signal ignored for {symbol} - shorting disabled ({self.trading_type} mode)")
    
    def _simulate_buy(self, symbol: str, price: float):
        """Simulate buying a position"""
        # Calculate position size using risk manager
        total_equity = self.current_balance + self.unrealized_pnl
        position_size_ratio = self.risk_manager.calculate_position_size(
            signal=1,
            current_price=price,
            equity=total_equity
        )
        
        # Convert ratio to actual quantity
        position_value = total_equity * position_size_ratio
        quantity = position_value / price
        
        # Apply slippage
        execution_price = price * (1 + self.slippage_rate)
        
        # Calculate costs
        total_cost = quantity * execution_price
        commission = total_cost * self.commission_rate
        total_with_commission = total_cost + commission
        
        if total_with_commission > self.current_balance:
            self.logger.warning(f"Insufficient balance for {symbol} purchase")
            return
        
        # Execute simulated trade
        self.positions[symbol] = {
            'size': quantity,
            'entry_price': execution_price,
            'timestamp': datetime.now().isoformat()
        }
        
        self.current_balance -= total_with_commission
        
        # Log trade
        self.logger.info(
            f"PAPER BOUGHT {quantity:.6f} {symbol} @ ${execution_price:.2f} "
            f"(Commission: ${commission:.2f})"
        )
        
        # Send alert
        if self.alert_system:
            alert_message = f"🎯 Paper Trade: LONG {symbol}\nSize: {quantity:.6f}\nPrice: ${execution_price:.2f}\nBalance: ${self.current_balance:.2f}"
            self.alert_system.send_alert(alert_message, "info")
    
    def _simulate_sell(self, symbol: str, price: float):
        """Simulate selling a position"""
        position = self.positions.get(symbol)
        if not position or position['size'] == 0:
            return
        
        quantity = position['size']
        entry_price = position['entry_price']
        
        # Apply slippage
        execution_price = price * (1 - self.slippage_rate)
        
        # Calculate proceeds
        gross_proceeds = quantity * execution_price
        commission = gross_proceeds * self.commission_rate
        net_proceeds = gross_proceeds - commission
        
        # Calculate P&L
        cost_basis = quantity * entry_price
        gross_pnl = gross_proceeds - cost_basis
        net_pnl = net_proceeds - cost_basis
        
        # Execute simulated trade
        self.current_balance += net_proceeds
        self.realized_pnl += net_pnl
        self.daily_pnl += net_pnl
        
        # Remove position
        self.positions[symbol] = {'size': 0, 'entry_price': None}
        
        # Log trade
        pnl_indicator = "PROFIT" if net_pnl > 0 else "LOSS"
        self.logger.info(
            f"PAPER SOLD {quantity:.6f} {symbol} @ ${execution_price:.2f} "
            f"P&L: {pnl_indicator} ${net_pnl:.2f} (Commission: ${commission:.2f})"
        )
        
        # Send alert
        if self.alert_system:
            alert_message = f"Paper Position Closed ({pnl_indicator}): {symbol}\nSize: {quantity:.6f}\nPrice: ${execution_price:.2f}\nP&L: ${net_pnl:.2f}\nBalance: ${self.current_balance:.2f}"
            alert_level = "info" if net_pnl > 0 else "warning"
            self.alert_system.send_alert(alert_message, alert_level)
    
    def _simulate_short(self, symbol: str, price: float):
        """Simulate opening a short position"""
        if not self.allow_shorting:
            self.logger.warning(f"Shorting not allowed for {symbol} in {self.trading_type} mode")
            return
            
        # Calculate position size using risk manager
        total_equity = self.current_balance + self.unrealized_pnl
        position_size_ratio = self.risk_manager.calculate_position_size(
            signal=-1,
            current_price=price,
            equity=total_equity
        )
        
        # Convert ratio to actual quantity (negative for short)
        position_value = total_equity * position_size_ratio
        quantity = -(position_value / price)  # Negative for short
        
        # Apply slippage (worse fill for short)
        execution_price = price * (1 + self.slippage_rate)
        
        # For shorting, we receive cash upfront but owe shares
        total_proceeds = abs(quantity) * execution_price
        commission = total_proceeds * self.commission_rate
        net_proceeds = total_proceeds - commission
        
        # Execute simulated short
        self.positions[symbol] = {
            'size': quantity,  # Negative for short
            'entry_price': execution_price,
            'timestamp': datetime.now().isoformat()
        }
        
        self.current_balance += net_proceeds  # Receive cash from short sale
        
        # Log trade
        self.logger.info(
            f"PAPER SHORTED {abs(quantity):.6f} {symbol} @ ${execution_price:.2f} "
            f"(Commission: ${commission:.2f})"
        )
        
        # Send alert
        if self.alert_system:
            alert_message = f"Paper Short Opened: {symbol}\nSize: {abs(quantity):.6f}\nPrice: ${execution_price:.2f}\nBalance: ${self.current_balance:.2f}"
            self.alert_system.send_alert(alert_message, "info")

    def _simulate_buy_to_cover(self, symbol: str, price: float):
        """Simulate buying to cover a short position"""
        position = self.positions.get(symbol)
        if not position or position['size'] >= 0:
            return
        
        quantity = abs(position['size'])  # Convert negative to positive
        entry_price = position['entry_price']
        
        # Apply slippage
        execution_price = price * (1 + self.slippage_rate)
        
        # Calculate costs to buy back shares
        total_cost = quantity * execution_price
        commission = total_cost * self.commission_rate
        total_with_commission = total_cost + commission
        
        # Calculate P&L (profit when covering at lower price)
        short_proceeds = quantity * entry_price  # What we received when shorting
        gross_pnl = short_proceeds - total_cost  # Profit if covering cheaper
        net_pnl = short_proceeds - total_with_commission
        
        # Execute simulated cover
        self.current_balance -= total_with_commission
        self.realized_pnl += net_pnl
        self.daily_pnl += net_pnl
        
        # Remove position
        self.positions[symbol] = {'size': 0, 'entry_price': None}
        
        # Log trade
        pnl_indicator = "PROFIT" if net_pnl > 0 else "LOSS"
        self.logger.info(
            f"PAPER COVERED {quantity:.6f} {symbol} @ ${execution_price:.2f} "
            f"P&L: {pnl_indicator} ${net_pnl:.2f} (Commission: ${commission:.2f})"
        )
        
        # Send alert
        if self.alert_system:
            alert_message = f"Paper Short Covered ({pnl_indicator}): {symbol}\nSize: {quantity:.6f}\nPrice: ${execution_price:.2f}\nP&L: ${net_pnl:.2f}\nBalance: ${self.current_balance:.2f}"
            alert_level = "info" if net_pnl > 0 else "warning"
            self.alert_system.send_alert(alert_message, alert_level)
    
    def _update_unrealized_pnl(self):
        """Update unrealized P&L for open positions"""
        self.unrealized_pnl = 0.0
        
        for symbol, position in self.positions.items():
            if position['size'] != 0:  # Handle both long (positive) and short (negative) positions
                try:
                    current_price = self.get_current_price(symbol)
                    if current_price > 0:
                        entry_price = position['entry_price']
                        quantity = position['size']
                        
                        if quantity > 0:  # Long position
                            unrealized = (current_price - entry_price) * quantity
                        else:  # Short position (quantity is negative)
                            unrealized = (entry_price - current_price) * abs(quantity)  # Profit when price drops
                        
                        self.unrealized_pnl += unrealized
                except Exception as e:
                    self.logger.error(f"Failed to update unrealized P&L for {symbol}: {e}")
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary"""
        total_equity = self.current_balance + self.unrealized_pnl
        total_pnl = self.realized_pnl + self.unrealized_pnl
        
        open_positions = sum(1 for pos in self.positions.values() if pos['size'] != 0)
        
        return {
            'daily_pnl': self.daily_pnl,
            'open_positions': open_positions,
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'total_pnl': total_pnl,
            'total_equity': total_equity,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'emergency_stop': self.emergency_stop,
            'mode': 'PAPER'
        }
    
    def shutdown(self):
        """Shutdown paper trader"""
        try:
            self._save_state()
            self.state_store.release_lock(self.lock_id)
            self.logger.info("Paper trader shutdown complete")
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")