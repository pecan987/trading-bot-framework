"""
Strategy wrapper for integrating framework strategies with backtesting.py library.

This module provides a bridge between our custom trading framework strategies
and the backtesting.py library, allowing seamless integration and reuse of
existing strategy implementations.
"""

import pandas as pd
from typing import Dict, Any, Optional

try:
    from backtesting import Strategy
except ImportError:
    raise ImportError("backtesting library not found. Install it with: uv add backtesting")

from framework.utils.logger import setup_logger
from framework.risk.base_risk_manager import BaseRiskManager
from framework.risk.fixed_position_size_manager import FixedPositionSizeManager


class StrategyWrapper(Strategy):
    """
    Wrapper to adapt existing framework strategies to work with backtesting.py
    
    This allows reuse of existing strategy implementations without duplicating
    the trading logic. The wrapper handles data format conversion and integrates
    stop loss and take profit functionality from strategy signals.
    
    Supports both long and short positions with integrated risk management.
    """
    
    # These will be set dynamically by create_wrapper_class()
    framework_strategy_class = None
    strategy_params = {}
    risk_manager = None  # Risk manager instance for position sizing
    debug = False  # Debug logging flag
    
    def init(self):
        """Initialize the wrapped strategy."""
        self.logger = setup_logger("INFO")
        
        # Create instance of framework strategy
        if self.__class__.framework_strategy_class is None:
            raise ValueError("framework_strategy_class must be set")
        
        # Log strategy initialization parameters for debugging
        if self.__class__.debug:
            self.logger.debug(f"Initializing {self.__class__.framework_strategy_class.__name__} with params: {self.__class__.strategy_params}")
            
        self.strategy = self.__class__.framework_strategy_class(**self.__class__.strategy_params)
        
        # Initialize risk manager if not provided
        if self.__class__.risk_manager is None:
            # Default to fixed position size manager with 10% position size
            self.__class__.risk_manager = FixedPositionSizeManager(position_size=0.1)
            self.logger.info("Using default FixedPositionSizeManager with 10% position size")

        
        # Generate signals for the entire dataset once
        # Convert backtesting.py data to framework format
        framework_data = pd.DataFrame({
            'Open': self.data.Open,
            'High': self.data.High, 
            'Low': self.data.Low,
            'Close': self.data.Close,
            'Volume': self.data.Volume if hasattr(self.data, 'Volume') else 0
        }, index=self.data.index)
        
        self.signals = self.strategy.generate_signals(framework_data)
        
        # Track current position state for stop loss/take profit
        self.entry_price = None
        self.stop_loss_price = None
        self.take_profit_price = None
        
        self.logger.info(f"Initialized {self.strategy.get_description()}")
        self.logger.info(f"Risk Manager: {self.__class__.risk_manager.get_description()}")
        
    def next(self):
        """Execute trading logic for current bar."""
        # Get current bar's timestamp
        current_time = self.data.index[-1]
        
        # Skip if we don't have signals for this timestamp
        if current_time not in self.signals.index:
            return
            
        # Get current signal data by timestamp
        current_signal_row = self.signals.loc[current_time]
        current_price = self.data.Close[-1]
        
        signal = current_signal_row.get('signal', 0)
        
        # Debug: Check if price data is valid
        if self.__class__.debug and signal != 0:
            self.logger.debug(f"Raw price data: Close[-1]={self.data.Close[-1]}, Open[-1]={self.data.Open[-1]}")
            self.logger.debug(f"Data index[-1]={self.data.index[-1]}, Signal time={current_time}")
        
        # Debug logging
        if self.__class__.debug and signal != 0:
            position_status = "None"
            if self.position:
                position_status = "Long" if self.position.is_long else "Short"
            self.logger.debug(f"Time {current_time}: Signal={signal}, Position={position_status}")
        
        # Get stop loss and take profit from signal if available
        stop_loss = current_signal_row.get('stop_loss', None)
        take_profit = current_signal_row.get('take_profit', None)
        
        # Get trade tag if available
        trade_tag = current_signal_row.get('tag', None)
        
        # Get strategy's position size if available
        strategy_position_size = current_signal_row.get('position_size', None)
        
        # Calculate position size using risk manager
        position_size = self.__class__.risk_manager.calculate_position_size(
            signal=signal,
            current_price=current_price,
            equity=self.equity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_position_size=strategy_position_size
        )
        
        # Check stop loss and take profit for existing positions
        if self.position and (self.stop_loss_price or self.take_profit_price):
            should_exit = False
            exit_reason = ""
            
            # Check stop loss
            if (self.stop_loss_price and 
                ((self.position.is_long and current_price <= self.stop_loss_price) or
                 (self.position.is_short and current_price >= self.stop_loss_price))):
                should_exit = True
                exit_reason = f"Stop Loss at ${current_price:.2f}"
                
            # Check take profit  
            elif (self.take_profit_price and
                  ((self.position.is_long and current_price >= self.take_profit_price) or
                   (self.position.is_short and current_price <= self.take_profit_price))):
                should_exit = True
                exit_reason = f"Take Profit at ${current_price:.2f}"
                
            if should_exit:
                self.position.close()
                if self.__class__.debug:
                    self.logger.debug(f"EXIT: {exit_reason}")
                self._reset_position_tracking()
                return
        
        # Handle new signals (only process non-zero signals)
        if signal == 0:
            return  # No signal, hold current position
        
        # Skip if position size is 0 (risk manager rejected the trade)
        if position_size == 0:
            if self.__class__.debug:
                self.logger.debug(f"Risk manager rejected trade: signal={signal}, stop_loss={stop_loss}")
            return
            
        # Debug position size
        if self.__class__.debug:
            self.logger.debug(f"About to execute trade: signal={signal}, position_size={position_size}, price={current_price}")
        
        # Close any existing position first if signal changes direction
        if self.position and (
            (signal == 1 and self.position.is_short) or 
            (signal == -1 and self.position.is_long)
        ):
            if self.__class__.debug:
                direction = "short" if self.position.is_short else "long"
                self.logger.debug(f"Closing existing {direction} position")
            self.position.close()
            self._reset_position_tracking()
            
        if signal == 1:  # Buy/Long signal
            if not self.position:
                if self.__class__.debug:
                    self.logger.debug(f"Executing LONG trade: size={position_size:.4f}, price={current_price:.6f}, sl={stop_loss}, tp={take_profit}")
                try:
                    # Open long position
                    self.buy(size=position_size, sl=stop_loss, tp=take_profit, tag=trade_tag)
                    
                    # Track position details for our own stop loss/take profit logic
                    self.entry_price = current_price
                    self.stop_loss_price = stop_loss
                    self.take_profit_price = take_profit
                    
                    if self.__class__.debug:
                        self.logger.debug(f"LONG trade executed successfully")
                except Exception as e:
                    if self.__class__.debug:
                        self.logger.debug(f"LONG trade execution failed: {e}")
                        
            else:
                if self.__class__.debug:
                    self.logger.debug(f"LONG signal ignored - already have position")
                    
        elif signal == -1:  # Sell/Short signal
            if not self.position:
                if self.__class__.debug:
                    self.logger.debug(f"Executing SHORT trade: size={position_size:.4f}, price={current_price:.6f}, sl={stop_loss}, tp={take_profit}")
                try:
                    # Open short position
                    self.sell(size=position_size, sl=stop_loss, tp=take_profit, tag=trade_tag)
                    
                    # Track position details for our own stop loss/take profit logic
                    self.entry_price = current_price
                    # For short positions, stop loss is above entry, take profit is below
                    self.stop_loss_price = stop_loss
                    self.take_profit_price = take_profit
                    
                    if self.__class__.debug:
                        self.logger.debug(f"SHORT trade executed successfully")
                except Exception as e:
                    if self.__class__.debug:
                        self.logger.debug(f"SHORT trade execution failed: {e}")
                        
            else:
                if self.__class__.debug:
                    self.logger.debug(f"SHORT signal ignored - already have position")
            
    def _reset_position_tracking(self):
        """Reset position tracking variables."""
        self.entry_price = None
        self.stop_loss_price = None  
        self.take_profit_price = None


def create_wrapper_class(
    strategy_cls, 
    params: Dict[str, Any],
    risk_manager: Optional[BaseRiskManager] = None,
    debug: bool = False
):
    """
    Create a dynamic wrapper class for a framework strategy.
    
    Args:
        strategy_cls: The framework strategy class to wrap
        params: Parameters to pass to the strategy constructor
        risk_manager: Risk manager instance for position sizing (optional)
        debug: Enable debug logging (default: False)
        
    Returns:
        A strategy class ready for use with backtesting.py
    """
    class DynamicWrapper(StrategyWrapper):
        framework_strategy_class = strategy_cls
        strategy_params = params
        
    # Set optional parameters
    DynamicWrapper.risk_manager = risk_manager
    DynamicWrapper.debug = debug
    
    return DynamicWrapper