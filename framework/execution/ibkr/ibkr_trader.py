#!/usr/bin/env python
"""
Clean IBKR Trader implementation using ibkr_config and ibkr_connection utilities
"""

import os
import time
import pandas as pd
from typing import Optional, Dict, Any
from dotenv import load_dotenv

from ib_async import MarketOrder, LimitOrder, StopOrder
from framework.utils.logger import setup_logger
from .ibkr_config import IBKRConfig
from .ibkr_connection import IBKRConnection


class IBKRTrader:
    """
    Clean IBKR trader implementation using configuration and connection separation
    """
    
    def __init__(self, config=None):
        load_dotenv()
        
        # Store main config for later use
        self.main_config = config
        
        # Create IBKR configuration from environment
        self.ibkr_config = IBKRConfig.from_env()
        
        # Override with main config if provided
        if config:
            if hasattr(config, 'timeframe'):
                self.timeframe = config.timeframe
            else:
                self.timeframe = os.getenv('TIMEFRAME', '15min')
        else:
            self.timeframe = os.getenv('TIMEFRAME', '15min')
        
        # Trading parameters
        self.initial_capital = float(os.getenv('INITIAL_CAPITAL', '10000'))
        self.position_size_pct = 0.1  # 10% of capital per trade
        
        # Create connection
        self.connection = IBKRConnection(self.ibkr_config)
        self.logger = setup_logger("INFO")
        
        # State tracking
        self.positions = {}
        
        self.logger.info(f"IBKR Trader initialized - {self.ibkr_config}")
    
    def initialize(self) -> bool:
        """Initialize connection to IBKR"""
        try:
            if not self.connection.connect():
                return False
            
            # Sync initial positions
            self._sync_positions()
            
            self.logger.info("IBKR Trader initialization complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize IBKR trader: {e}")
            return False
    
    def cleanup(self):
        """Cleanup method for main.py compatibility"""
        self.connection.disconnect()
    
    def _sync_positions(self):
        """Sync positions from IBKR"""
        try:
            positions = self.connection.get_positions()
            self.positions = {}
            
            for pos in positions:
                if abs(pos.position) > 0:  # Only active positions
                    symbol = pos.contract.symbol
                    self.positions[symbol] = {
                        'size': float(pos.position),
                        'entry_price': float(pos.avgCost) if hasattr(pos, 'avgCost') and pos.avgCost else 0.0,
                        'contract': pos.contract,
                        'last_update': time.time()
                    }
                    self.logger.info(f"Position: {symbol} = {pos.position} shares @ ${pos.avgCost}")
            
            if not self.positions:
                self.logger.info("No open positions")
                
        except Exception as e:
            self.logger.error(f"Failed to sync positions: {e}")
    
    def get_market_data(self, symbol: str, timeframe: str = '15min', lookback: int = 100) -> Optional[pd.DataFrame]:
        """
        Get historical market data for a symbol
        
        Args:
            symbol: Trading symbol (e.g., 'AAPL')
            timeframe: Timeframe ('1min', '5min', '15min', '1h', '1D')
            lookback: Number of bars to retrieve
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            if not self.connection.is_connected():
                self.logger.error("Not connected to IBKR")
                return None
            
            # Create contract
            contract = self.connection.create_contract(symbol)
            
            # Qualify contract
            if not self.connection.qualify_contract(contract):
                self.logger.error(f"Failed to qualify contract for {symbol}")
                return None
            
            # Map timeframe to bar size
            bar_size_map = {
                '1min': '1 min',
                '5min': '5 mins', 
                '15min': '15 mins',
                '30min': '30 mins',
                '1h': '1 hour',
                '4h': '4 hours',
                '1D': '1 day'
            }
            
            bar_size = bar_size_map.get(timeframe, '15 mins')
            
            # Calculate duration
            if timeframe in ['1D', '4h']:
                duration = f"{lookback} D"
            else:
                duration = f"{lookback * 2} H"  # Give some buffer
            
            # Request historical data
            self.logger.debug(f"Requesting {lookback} bars of {symbol} ({bar_size})")
            
            bars = self.connection.get_historical_data(
                contract=contract,
                duration=duration,
                bar_size=bar_size,
                what_to_show='MIDPOINT'
            )
            
            if not bars:
                self.logger.warning(f"No historical data received for {symbol}")
                return None
            
            # Convert to DataFrame
            data = []
            for bar in bars:
                data.append({
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': int(bar.volume)
                })
            
            df = pd.DataFrame(data)
            df.index = pd.to_datetime([bar.date for bar in bars])
            df.index.name = 'datetime'
            
            self.logger.info(f"✓ Retrieved {len(df)} bars for {symbol}")
            return df.tail(lookback)  # Return requested number of bars
            
        except Exception as e:
            self.logger.error(f"Failed to get market data for {symbol}: {e}")
            return None
    
    def run_trading_cycle(self, symbol: str, strategy) -> bool:
        """
        Run one trading cycle for a symbol
        
        Args:
            symbol: Trading symbol
            strategy: Strategy instance
            
        Returns:
            bool: True if cycle completed successfully
        """
        try:
            if not self.connection.is_connected():
                self.logger.error("Not connected to IBKR")
                return False
            
            # Get market data - request more bars to ensure we have enough
            lookback_bars = max(100, strategy.min_bars_required)
            df = self.get_market_data(symbol, self.timeframe, lookback_bars)
            if df is None or len(df) < strategy.min_bars_required:
                self.logger.warning(f"Insufficient data for {symbol}: got {len(df) if df is not None else 0}, need {strategy.min_bars_required}")
                return False
            
            # Generate signals
            signals = strategy.generate_signals(df)
            if signals is None or len(signals) == 0:
                return False
            
            latest_signal = signals['signal'].iloc[-1]
            current_price = df['close'].iloc[-1]
            
            # Extract SL/TP if provided by strategy
            stop_loss = None
            take_profit = None
            
            if 'stop_loss' in signals.columns:
                sl_val = signals['stop_loss'].iloc[-1]
                if pd.notna(sl_val) and sl_val > 0:
                    stop_loss = float(sl_val)
            
            if 'take_profit' in signals.columns:
                tp_val = signals['take_profit'].iloc[-1]
                if pd.notna(tp_val) and tp_val > 0:
                    take_profit = float(tp_val)
            
            # Log signal
            self.logger.info(f"{symbol}: Signal={latest_signal}, Price=${current_price:.2f}")
            if stop_loss:
                self.logger.info(f"  Stop Loss: ${stop_loss:.2f}")
            if take_profit:
                self.logger.info(f"  Take Profit: ${take_profit:.2f}")
            
            # Execute trade
            return self.execute_trade(symbol, latest_signal, current_price, stop_loss, take_profit)
            
        except Exception as e:
            self.logger.error(f"Error in trading cycle for {symbol}: {e}")
            return False
    
    def execute_trade(self, symbol: str, signal: int, current_price: float, 
                     stop_loss: float = None, take_profit: float = None) -> bool:
        """
        Execute trade based on signal
        
        Args:
            symbol: Trading symbol
            signal: 1=buy, -1=sell, 0=hold
            current_price: Current market price
            stop_loss: Stop loss price (optional)
            take_profit: Take profit price (optional)
            
        Returns:
            bool: True if trade executed successfully
        """
        try:
            if signal == 0:  # Hold
                return True
            
            current_position = self.positions.get(symbol, {'size': 0})
            position_size = current_position['size']
            
            # Determine action
            if position_size == 0:  # No position
                if signal == 1:  # Buy signal
                    return self._place_buy_order(symbol, current_price, stop_loss, take_profit)
                elif signal == -1:  # Sell signal  
                    return self._place_sell_order(symbol, current_price, stop_loss, take_profit)
            
            elif position_size > 0:  # Long position
                if signal == -1:  # Exit long
                    return self._close_position(symbol, current_price)
            
            elif position_size < 0:  # Short position
                if signal == 1:  # Cover short
                    return self._close_position(symbol, current_price)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to execute trade: {e}")
            return False
    
    def _place_buy_order(self, symbol: str, price: float, stop_loss: float = None, take_profit: float = None) -> bool:
        """Place a buy order"""
        try:
            # Calculate position size
            quantity = self._calculate_quantity(price)
            if quantity <= 0:
                self.logger.warning(f"Invalid quantity: {quantity}")
                return False
            
            # Create contract
            contract = self.connection.create_contract(symbol)
            
            self.logger.info(f"Placing BUY order: {quantity} {symbol} @ ${price:.2f}")
            
            # Place order with bracket if SL/TP provided
            if stop_loss or take_profit:
                return self._place_bracket_order(contract, 'BUY', quantity, price, stop_loss, take_profit)
            else:
                # Simple market order
                order = MarketOrder('BUY', quantity)
                trade = self.connection.place_order(contract, order)
                
                if trade:
                    # Wait for order to process
                    time.sleep(0.5)
                    self.logger.info(f"✓ Buy order placed: {quantity} {symbol}")
                    return True
                else:
                    return False
            
        except Exception as e:
            self.logger.error(f"Failed to place buy order: {e}")
            return False
    
    def _place_sell_order(self, symbol: str, price: float, stop_loss: float = None, take_profit: float = None) -> bool:
        """Place a sell order (short)"""
        try:
            # Calculate position size
            quantity = self._calculate_quantity(price)
            if quantity <= 0:
                self.logger.warning(f"Invalid quantity: {quantity}")
                return False
            
            # Create contract
            contract = self.connection.create_contract(symbol)
            
            self.logger.info(f"Placing SELL order: {quantity} {symbol} @ ${price:.2f}")
            
            # Place order with bracket if SL/TP provided
            if stop_loss or take_profit:
                return self._place_bracket_order(contract, 'SELL', quantity, price, stop_loss, take_profit)
            else:
                # Simple market order
                order = MarketOrder('SELL', quantity)
                trade = self.connection.place_order(contract, order)
                
                if trade:
                    # Wait for order to process
                    time.sleep(0.5)
                    self.logger.info(f"✓ Sell order placed: {quantity} {symbol}")
                    return True
                else:
                    return False
            
        except Exception as e:
            self.logger.error(f"Failed to place sell order: {e}")
            return False
    
    def _close_position(self, symbol: str, price: float) -> bool:
        """Close existing position"""
        try:
            position = self.positions.get(symbol)
            if not position:
                self.logger.warning(f"No position to close for {symbol}")
                return True
            
            current_size = position['size']
            quantity = abs(current_size)
            action = 'SELL' if current_size > 0 else 'BUY'
            
            contract = self.connection.create_contract(symbol)
            order = MarketOrder(action, quantity)
            
            self.logger.info(f"Closing position: {action} {quantity} {symbol}")
            
            trade = self.connection.place_order(contract, order)
            if trade:
                time.sleep(0.5)
                self.logger.info(f"✓ Position closed: {symbol}")
                return True
            else:
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to close position: {e}")
            return False
    
    def _place_bracket_order(self, contract, action: str, quantity: int, entry_price: float, 
                            stop_loss: float = None, take_profit: float = None) -> bool:
        """
        Place bracket order with stop loss and take profit
        """
        try:
            self.logger.info(f"Creating bracket order: {action} {quantity}")
            
            # 1. Parent order (limit order for better control)
            parent_order = LimitOrder(action, quantity, entry_price)
            parent_order.transmit = False  # Don't transmit yet
            
            # Place parent order
            parent_trade = self.connection.place_order(contract, parent_order)
            if not parent_trade:
                self.logger.error("Failed to place parent order")
                return False
                
            parent_id = parent_order.orderId
            
            self.logger.info(f"  Parent order: {action} {quantity} @ ${entry_price:.2f}")
            
            # 2. Stop loss order
            if stop_loss:
                stop_action = 'SELL' if action == 'BUY' else 'BUY'
                stop_order = StopOrder(stop_action, quantity, stop_loss)
                stop_order.parentId = parent_id
                stop_order.transmit = False
                
                self.connection.place_order(contract, stop_order)
                self.logger.info(f"  Stop Loss: {stop_action} {quantity} @ ${stop_loss:.2f}")
            
            # 3. Take profit order
            if take_profit:
                profit_action = 'SELL' if action == 'BUY' else 'BUY'
                profit_order = LimitOrder(profit_action, quantity, take_profit)
                profit_order.parentId = parent_id
                profit_order.transmit = True  # Transmit all orders
                
                self.connection.place_order(contract, profit_order)
                self.logger.info(f"  Take Profit: {profit_action} {quantity} @ ${take_profit:.2f}")
            else:
                # No take profit, transmit parent order
                parent_order.transmit = True
                self.connection.place_order(contract, parent_order)
            
            time.sleep(0.5)
            self.logger.info("✓ Bracket order placed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to place bracket order: {e}")
            # Fallback to simple market order
            fallback_order = MarketOrder(action, quantity)
            self.connection.place_order(contract, fallback_order)
            return True
    
    def _calculate_quantity(self, price: float) -> int:
        """Calculate position quantity based on capital and price"""
        try:
            # Use percentage of capital
            position_value = self.initial_capital * self.position_size_pct
            quantity = int(position_value / price)
            
            # Minimum 1 share
            return max(1, quantity)
            
        except Exception as e:
            self.logger.error(f"Failed to calculate quantity: {e}")
            return 1  # Fallback to 1 share
    
    def get_performance_summary(self) -> dict:
        """Get basic performance summary"""
        try:
            total_positions = len(self.positions)
            
            return {
                'connected': self.connection.is_connected(),
                'open_positions': total_positions,
                'accounts': self.connection.get_managed_accounts(),
                'initial_capital': self.initial_capital,
                'config': str(self.ibkr_config)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting performance summary: {e}")
            return {'error': str(e)}