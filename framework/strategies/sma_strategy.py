import pandas as pd
from typing import Dict, Any
from .base_strategy import BaseStrategy


class SMAStrategy(BaseStrategy):
    """
    Simple Moving Average Crossover Strategy.
    
    Generates buy signals when short MA crosses above long MA,
    and sell signals when short MA crosses below long MA.
    """
    
    def __init__(self, short_window: int = 20, long_window: int = 50,
                 position_size: float = 0.01, stop_loss_pct: float = 0.02,
                 take_profit_pct: float = 0.04):
        """
        Initialize the strategy.
        
        Args:
            short_window: Period for short moving average
            long_window: Period for long moving average  
            position_size: Fraction of portfolio to use for each trade (0.0 to 1.0)
            stop_loss_pct: Stop loss percentage (e.g., 0.02 for 2% stop loss)
            take_profit_pct: Take profit percentage (e.g., 0.04 for 4% take profit)
        """
        parameters = {
            'short_window': short_window,
            'long_window': long_window,
            'position_size': position_size,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct
        }
        super().__init__("SMA", parameters)
        
        self.short_window = short_window
        self.long_window = long_window
        self.position_size = position_size
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.min_bars_required = max(short_window, long_window) + 1  # Need enough data for moving averages
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals based on moving average crossover.
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            DataFrame with signal and position_size columns added
        """
        if not self.validate_data(data):
            raise ValueError("Invalid data format")
            
        df = data.copy()
        
        # Calculate moving averages
        df['ma_short'] = df['Close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['Close'].rolling(window=self.long_window).mean()
        
        # Initialize signal columns
        df['signal'] = 0
        df['position_size'] = self.position_size
        df['stop_loss'] = None
        df['take_profit'] = None
        
        # Generate crossover signals
        df['ma_short_prev'] = df['ma_short'].shift(1)
        df['ma_long_prev'] = df['ma_long'].shift(1)
        
        # Buy signal: short MA crosses above long MA
        buy_condition = (
            (df['ma_short'] > df['ma_long']) & 
            (df['ma_short_prev'] <= df['ma_long_prev'])
        )
        
        # Sell signal: short MA crosses below long MA
        sell_condition = (
            (df['ma_short'] < df['ma_long']) & 
            (df['ma_short_prev'] >= df['ma_long_prev'])
        )
        
        # Apply crossover signals
        df.loc[buy_condition, 'signal'] = 1
        df.loc[sell_condition, 'signal'] = -1
        
        # Only generate signals when we have enough data for both MAs
        min_periods = max(self.short_window, self.long_window)
        df.iloc[:min_periods, df.columns.get_loc('signal')] = 0
        
        # Calculate stop loss and take profit for buy signals (long positions)
        if self.stop_loss_pct is not None:
            buy_mask = df['signal'] == 1
            df.loc[buy_mask, 'stop_loss'] = df.loc[buy_mask, 'Close'] * (1 - self.stop_loss_pct)
            
            # For short positions, stop loss is above entry price
            sell_mask = df['signal'] == -1
            df.loc[sell_mask, 'stop_loss'] = df.loc[sell_mask, 'Close'] * (1 + self.stop_loss_pct)
        
        if self.take_profit_pct is not None:
            buy_mask = df['signal'] == 1
            df.loc[buy_mask, 'take_profit'] = df.loc[buy_mask, 'Close'] * (1 + self.take_profit_pct)
            
            # For short positions, take profit is below entry price
            sell_mask = df['signal'] == -1
            df.loc[sell_mask, 'take_profit'] = df.loc[sell_mask, 'Close'] * (1 - self.take_profit_pct)
        
        # Clean up temporary columns
        df = df.drop(['ma_short_prev', 'ma_long_prev'], axis=1)
        
        return df
        
    def get_description(self) -> str:
        """Return strategy description."""
        sl_desc = ""
        if self.stop_loss_pct is not None:
            sl_desc = f" Stop loss: {self.stop_loss_pct * 100}%."
            
        tp_desc = ""
        if self.take_profit_pct is not None:
            tp_desc = f" Take profit: {self.take_profit_pct * 100}%."
        
        return (f"Simple Moving Average Crossover Strategy with "
                f"{self.short_window}-period short MA and {self.long_window}-period long MA. "
                f"Position size: {self.position_size * 100}%.{sl_desc}{tp_desc}")
    
    def get_strategy_name(self) -> str:
        """Return strategy name for identification."""
        return self.name