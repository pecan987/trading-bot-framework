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
        self.min_bars_required = 2  # Minimal requirement for compatibility
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate alternating buy/sell signals every 2 candles.
        
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
        
        # Generate alternating pattern every 2 candles
        for i in range(len(data)):
            cycle_position = i % 4  # 4-candle cycle
            
            if cycle_position in [0, 1]:
                # First 2 candles: Buy signal
                result.iloc[i, result.columns.get_loc('signal')] = 1
                result.iloc[i, result.columns.get_loc('position_size')] = self.position_size
            elif cycle_position in [2, 3]:
                # Next 2 candles: Sell signal  
                result.iloc[i, result.columns.get_loc('signal')] = -1
                result.iloc[i, result.columns.get_loc('position_size')] = self.position_size
        
        return result[['signal', 'position_size']]
    
    def get_description(self) -> str:
        """Return strategy description."""
        return (
            f"Test Strategy - Alternates buy/sell every 2 candles "
            f"(position_size: {self.position_size})"
        )
    
    def get_parameters(self) -> Dict[str, Any]:
        """Return strategy parameters."""
        return {
            'position_size': self.position_size,
            'min_bars_required': self.min_bars_required
        }