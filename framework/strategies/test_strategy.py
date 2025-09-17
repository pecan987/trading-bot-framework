"""
Test Strategy for Order Execution Testing

This strategy alternates between buy and sell signals every 2nd candle.
Perfect for testing how orders are executed in paper trading and live CCXT trading.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

from framework.strategies.base_strategy import BaseStrategy


class TestStrategy(BaseStrategy):
    """
    Test strategy that alternates buy/sell signals every 2 candles.
    
    Signal Pattern:
    - Candle 0, 1: Hold (signal=0)
    - Candle 2, 3: Buy (signal=1) 
    - Candle 4, 5: Sell (signal=-1)
    - Candle 6, 7: Buy (signal=1)
    - And so on...
    
    This creates predictable signals for testing order execution.
    """
    
    def __init__(self, position_size: float = 0.1, **kwargs):
        """Initialize test strategy with minimal parameters."""
        parameters = {
            'position_size': position_size
        }
        super().__init__("TEST", parameters)
        
        self.position_size = position_size
        self.min_bars_required = 2  # Need at least 2 candles
        self.last_signal = 0  # Track the last signal to alternate
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate alternating signals: 0 -> 1 -> -1 -> 1 -> -1 -> ...
        
        Args:
            data: OHLCV DataFrame with DatetimeIndex
            
        Returns:
            DataFrame with 'signal' and 'position_size' columns
        """
        # Validate input data
        self.validate_data(data)
        
        if len(data) < self.min_bars_required:
            # Not enough data, return hold signals
            result = data.copy()
            result['signal'] = 0
            result['position_size'] = 0.0
            return result[['signal', 'position_size']]
        
        # Create signals DataFrame
        result = data.copy()
        result['signal'] = 0
        result['position_size'] = 0.0
        
        # Generate next signal based on last signal
        if self.last_signal == 0:
            new_signal = 1  # 0 -> 1 (buy)
        elif self.last_signal == 1:
            new_signal = -1  # 1 -> -1 (sell) 
        else:  # self.last_signal == -1
            new_signal = 1  # -1 -> 1 (buy)
        
        # Set signal for all rows (we only care about the last one)
        result['signal'] = new_signal
        result['position_size'] = self.position_size
        
        # Update last signal for next call
        self.last_signal = new_signal
        
        return result[['signal', 'position_size']]
    
    def get_description(self) -> str:
        """Return strategy description."""
        return (
            f"Test Strategy - Alternates signals: 0→1→-1→1→-1... "
            f"(position_size: {self.position_size})"
        )
    
    def get_parameters(self) -> Dict[str, Any]:
        """Return strategy parameters."""
        return {
            'position_size': self.position_size,
            'min_bars_required': self.min_bars_required
        }