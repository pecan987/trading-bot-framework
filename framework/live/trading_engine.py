"""
Broker-agnostic trading engine that executes strategies
"""
import os
import time
import logging
import signal
import threading
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import pandas as pd
import traceback

from framework.strategies.base_strategy import BaseStrategy
from framework.risk.fixed_risk_manager import FixedRiskManager
from .brokers.base_broker import BaseBroker, OrderSide, OrderType, Order
from .db_manager import DatabaseManager


class TradingEngine:
    """Main trading engine that coordinates strategy, broker, and database"""
    
    def __init__(
        self,
        broker: BaseBroker,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str = '15m',
        lookback_periods: int = 100,
        db_manager: DatabaseManager = None,
        position_size: float = 0.1,  # 10% of portfolio
        max_positions: int = 1,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        risk_per_trade: float = 0.01,
        use_risk_management: bool = True
    ):
        """
        Initialize trading engine
        
        Args:
            broker: Broker instance for execution
            strategy: Trading strategy instance
            symbol: Symbol to trade
            timeframe: Timeframe for data and signals
            lookback_periods: Number of candles to fetch
            db_manager: Database manager for logging
            position_size: Position size as portfolio percentage
            max_positions: Maximum concurrent positions
            stop_loss_pct: Stop loss percentage
            take_profit_pct: Take profit percentage
            risk_per_trade: Risk per trade for position sizing
            use_risk_management: Enable risk management
        """
        self.broker = broker
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback_periods = lookback_periods
        self.db = db_manager
        self.position_size = position_size
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.risk_per_trade = risk_per_trade
        self.use_risk_management = use_risk_management
        
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        self.last_signal = 0
        self.current_positions = {}
        
        # Risk manager for position sizing
        if use_risk_management:
            self.risk_manager = FixedRiskManager(
                risk_percent=risk_per_trade,
                default_stop_distance=stop_loss_pct
            )
        else:
            self.risk_manager = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Shutdown signal {signum} received")
        self.is_running = False
        self.stop()
    
    def start(self):
        """Start the trading engine"""
        try:
            # Connect to broker
            if not self.broker.connect():
                raise ConnectionError(f"Failed to connect to {self.broker.name}")
            
            self.logger.info(
                f"Trading engine started: {self.symbol} on {self.broker.name} "
                f"using {self.strategy.__class__.__name__}"
            )
            
            # Update broker status in database
            if self.db:
                self.db.update_broker_status(
                    broker=self.broker.name,
                    is_active=True,
                    is_paper_trading='paper' in self.broker.name,
                    connection_status='connected'
                )
            
            self.is_running = True
            
            # Start main trading loop
            self._run_trading_loop()
            
        except Exception as e:
            self.logger.error(f"Trading engine error: {e}")
            self.logger.error(traceback.format_exc())
            self.stop()
            raise
    
    def stop(self):
        """Stop the trading engine"""
        self.is_running = False
        
        # Close all positions if configured
        if os.getenv('CLOSE_ON_EXIT', 'false').lower() == 'true':
            self._close_all_positions()
        
        # Disconnect broker
        if self.broker:
            self.broker.disconnect()
        
        # Update broker status
        if self.db:
            self.db.update_broker_status(
                broker=self.broker.name,
                is_active=False,
                connection_status='disconnected'
            )
        
        self.logger.info("Trading engine stopped")
    
    def _run_trading_loop(self):
        """Main trading loop"""
        # Calculate sleep interval based on timeframe
        sleep_seconds = self._get_sleep_seconds()
        
        while self.is_running:
            try:
                # Fetch latest market data
                data = self.broker.get_market_data(
                    self.symbol,
                    self.timeframe,
                    self.lookback_periods
                )
                
                if data.empty:
                    self.logger.warning("No market data available")
                    time.sleep(sleep_seconds)
                    continue
                
                # Check if still running before processing
                if not self.is_running:
                    break
                
                # Generate trading signals
                signals_df = self.strategy.generate_signals(data)
                
                if signals_df.empty or 'signal' not in signals_df.columns:
                    self.logger.warning("No signals generated")
                    time.sleep(sleep_seconds)
                    continue
                
                # Get latest signal
                latest_signal = signals_df['signal'].iloc[-1]
                current_price = data['Close'].iloc[-1]
                
                # Log current price and signal
                self.logger.info(
                    f"BTC/USDT:USDT ${current_price:.2f} | Signal: {latest_signal} | "
                    f"Strategy: {self.strategy.__class__.__name__}"
                )
                
                # Log signal change
                if latest_signal != self.last_signal:
                    self.logger.info(
                        f"🔄 Signal changed: {self.last_signal} -> {latest_signal} "
                        f"at ${current_price:.2f}"
                    )
                    self.last_signal = latest_signal
                
                # Execute trading logic
                self._execute_signal(latest_signal, current_price, signals_df)
                
                # Update positions and P&L
                self._update_positions()
                
                # Save portfolio snapshot
                self._save_portfolio_snapshot()
                
                # Check stop loss and take profit
                self._check_exit_conditions()
                
                # Heartbeat
                if self.db:
                    self.db.update_broker_status(
                        broker=self.broker.name,
                        is_active=True,
                        is_paper_trading='paper' in self.broker.name,
                        connection_status='running'
                    )
                
                # Sleep until next candle (check for interruption during sleep)
                for _ in range(sleep_seconds):
                    if not self.is_running:
                        return
                    time.sleep(1)
                
            except KeyboardInterrupt:
                self.logger.info("Trading interrupted by user")
                break
            except Exception as e:
                self.logger.error(f"Trading loop error: {e}")
                self.logger.error(traceback.format_exc())
                
                # Log error to database
                if self.db:
                    self.db.update_broker_status(
                        broker=self.broker.name,
                        is_active=True,
                        error_message=str(e)
                    )
                
                # Wait before retrying
                time.sleep(sleep_seconds)
    
    def _execute_signal(self, signal: int, current_price: float, signals_df: pd.DataFrame):
        """Execute trading signal"""
        # Get current positions
        positions = self.broker.get_positions(self.symbol)
        has_position = len(positions) > 0
        
        # Check position limits
        if signal != 0 and has_position and len(positions) >= self.max_positions:
            self.logger.debug(f"Max positions ({self.max_positions}) reached")
            return
        
        # Execute based on signal
        if signal == 1 and not has_position:  # Buy signal
            self._open_long_position(current_price, signals_df)
            
        elif signal == -1 and not has_position:  # Sell signal (short)
            # Only short if allowed
            if os.getenv('ALLOW_SHORT', 'false').lower() == 'true':
                self._open_short_position(current_price, signals_df)
            
        elif signal == 0 and has_position:  # Close signal
            self._close_position(positions[0], current_price)
    
    def _open_long_position(self, current_price: float, signals_df: pd.DataFrame):
        """Open a long position"""
        try:
            # Get account info
            account = self.broker.get_account_info()
            
            # Calculate position size
            if self.use_risk_management and self.risk_manager:
                # Calculate position with risk management
                stop_loss = current_price * (1 - self.stop_loss_pct)
                quantity = self.risk_manager.calculate_position_size(
                    signal=1,
                    current_price=current_price,
                    equity=account.total_equity,
                    stop_loss=stop_loss
                )
            else:
                # Simple position sizing
                position_value = account.total_equity * self.position_size
                quantity = position_value / current_price
            
            # Check for custom position size in signals
            if 'position_size' in signals_df.columns:
                custom_size = signals_df['position_size'].iloc[-1]
                if custom_size > 0:
                    quantity = quantity * custom_size
            
            # Round quantity
            quantity = self.broker.round_quantity(quantity, self.symbol)
            
            if quantity <= 0:
                self.logger.warning("Position size too small")
                return
            
            # Place buy order
            order = self.broker.place_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                order_type=OrderType.MARKET
            )
            
            # Log to database
            if self.db and order.status != 'rejected':
                # Save order
                order_id = self.db.save_order(
                    broker=self.broker.name,
                    symbol=self.symbol,
                    side='buy',
                    order_type='market',
                    quantity=quantity,
                    status=order.status.value,
                    broker_order_id=order.broker_order_id
                )
                
                # Save position info
                self.current_positions[self.symbol] = {
                    'order': order,
                    'entry_price': current_price,
                    'stop_loss': current_price * (1 - self.stop_loss_pct),
                    'take_profit': current_price * (1 + self.take_profit_pct),
                    'db_order_id': order_id
                }
            
            self.logger.info(
                f"Opened long position: {quantity:.4f} {self.symbol} @ ${current_price:.2f}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to open long position: {e}")
    
    def _open_short_position(self, current_price: float, signals_df: pd.DataFrame):
        """Open a short position"""
        # Similar to long but reversed
        self.logger.warning("Short selling not fully implemented yet")
    
    def _close_position(self, position, current_price: float):
        """Close an existing position"""
        try:
            # Place sell order
            order = self.broker.place_order(
                symbol=position.symbol,
                side=OrderSide.SELL,
                quantity=abs(position.quantity),
                order_type=OrderType.MARKET
            )
            
            # Calculate P&L
            pnl = (current_price - position.avg_entry_price) * position.quantity
            
            # Log to database
            if self.db:
                # Save trade
                self.db.save_trade(
                    broker=self.broker.name,
                    strategy=self.strategy.__class__.__name__,
                    symbol=position.symbol,
                    side='sell',
                    quantity=abs(position.quantity),
                    price=current_price,
                    pnl=pnl,
                    broker_trade_id=order.broker_order_id
                )
                
                # Close position in DB
                self.db.close_position(
                    broker=self.broker.name,
                    symbol=position.symbol,
                    realized_pnl=pnl
                )
            
            # Remove from current positions
            if position.symbol in self.current_positions:
                del self.current_positions[position.symbol]
            
            self.logger.info(
                f"Closed position: {abs(position.quantity):.4f} {position.symbol} "
                f"@ ${current_price:.2f} (P&L: ${pnl:.2f})"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to close position: {e}")
    
    def _check_exit_conditions(self):
        """Check stop loss and take profit conditions"""
        for symbol, pos_info in list(self.current_positions.items()):
            try:
                current_price = self.broker.get_current_price(symbol)
                positions = self.broker.get_positions(symbol)
                
                if not positions:
                    continue
                
                position = positions[0]
                
                # Check stop loss
                if current_price <= pos_info['stop_loss']:
                    self.logger.info(f"Stop loss triggered for {symbol}")
                    self._close_position(position, current_price)
                
                # Check take profit
                elif current_price >= pos_info['take_profit']:
                    self.logger.info(f"Take profit triggered for {symbol}")
                    self._close_position(position, current_price)
                    
            except Exception as e:
                self.logger.error(f"Error checking exit conditions: {e}")
    
    def _update_positions(self):
        """Update position information in database"""
        if not self.db:
            return
        
        try:
            positions = self.broker.get_positions()
            
            for position in positions:
                self.db.upsert_position(
                    broker=self.broker.name,
                    symbol=position.symbol,
                    quantity=position.quantity,
                    avg_entry_price=position.avg_entry_price,
                    current_price=position.current_price,
                    unrealized_pnl=position.unrealized_pnl
                )
        except Exception as e:
            self.logger.error(f"Failed to update positions: {e}")
    
    def _save_portfolio_snapshot(self):
        """Save portfolio snapshot to database"""
        if not self.db:
            return
        
        try:
            account = self.broker.get_account_info()
            
            self.db.save_portfolio_snapshot(
                broker=self.broker.name,
                total_value=account.total_equity,
                cash_balance=account.cash_balance,
                positions_value=account.positions_value,
                daily_pnl=account.unrealized_pnl,
                total_pnl=account.unrealized_pnl + account.realized_pnl
            )
        except Exception as e:
            self.logger.error(f"Failed to save portfolio snapshot: {e}")
    
    def _close_all_positions(self):
        """Close all open positions"""
        try:
            positions = self.broker.get_positions()
            for position in positions:
                current_price = self.broker.get_current_price(position.symbol)
                self._close_position(position, current_price)
        except Exception as e:
            self.logger.error(f"Failed to close all positions: {e}")
    
    def _get_sleep_seconds(self) -> int:
        """Calculate sleep interval based on timeframe"""
        timeframe_seconds = {
            '1m': 60,
            '5m': 300,
            '15m': 900,
            '30m': 1800,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400
        }
        return timeframe_seconds.get(self.timeframe, 60)