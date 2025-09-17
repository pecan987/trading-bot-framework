"""
FVG Strategy (M15 Timeframe with H4 Context)

Multi-timeframe FVG strategy that:
- Uses H4 unmitigated FVG context with M15 FVG confirmation
- Only considers H4 FVGs from last 9 H4 candles
- Requires price to touch unmitigated H4 FVG before M15 FVG signal
- Only trades during specific execution windows in NY timezone
- Daily open filter: Long above daily open, Short below daily open
- Allows only one trade per session window
- Excludes weekend trading

Entry Conditions:
1. H4 FVG formation within last 9 H4 candles that is UNMITIGATED
2. Price must touch (wick into) the unmitigated H4 FVG
3. Daily open filter: Long only if price above daily open, Short only if price below daily open
4. M15 FVG detected in same direction as H4 FVG
5. Must be within execution time window
6. Only ONE trade allowed per session window  
7. NOT on weekends (Saturday/Sunday)

Exit Conditions:
- Stop Loss: Low/High of first candle in M15 FVG formation
- Take Profit: Configurable Risk/Reward ratio (default 2:1)

Execution Windows (NY Time):
- 03:00 - 04:00 (London Open)
- 10:00 - 11:00 (NY Open)  
- 14:00 - 15:00 (NY Afternoon)
"""

import pandas as pd
import numpy as np
from datetime import timedelta
import pytz
from .base_strategy import BaseStrategy
from .detectors.fvg_detector import FVGDetector


class FVGStrategy(BaseStrategy):
    """
    Simple FVG strategy using M15 FVG detection with execution windows.
    """
    
    def __init__(self, 
                 risk_reward_ratio: float = 2.0,
                 max_hold_hours: int = 2,
                 min_fvg_sensitivity: float = 0.1,
                 position_size: float = 0.1,
                 h1_lookback_candles: int = 36,
                 h4_lookback_candles: int = 9,
                 **kwargs):
        """
        Initialize FVG strategy.
        
        Args:
            risk_reward_ratio: Risk/Reward ratio for take profit (default: 2.0)
            max_hold_hours: Maximum hold time in hours (default: 2)
            min_fvg_sensitivity: Minimum FVG sensitivity ratio (default: 0.1)
            position_size: Position size as fraction of equity (default: 0.1)
            h1_lookback_candles: Number of H1 candles to look back for FVG detection (default: 36)
            h4_lookback_candles: Number of H4 candles to look back for unmitigated FVG detection (default: 9)
        """
        super().__init__("fvg", kwargs)
        
        self.risk_reward_ratio = risk_reward_ratio
        self.max_hold_hours = max_hold_hours
        self.min_fvg_sensitivity = min_fvg_sensitivity
        self.position_size = position_size
        self.min_bars_required = max(h1_lookback_candles, h4_lookback_candles) + 20  # Need enough data for FVG detection
        self.h1_lookback_candles = h1_lookback_candles
        self.h4_lookback_candles = h4_lookback_candles
        
        # Initialize FVG detector
        self.fvg_detector = FVGDetector(min_sensitivity=min_fvg_sensitivity)
        
        # Execution windows in NY timezone (24-hour format)
        self.execution_windows = [
            (3, 4),   # London Open: 03:00 - 04:00 NY
            (10, 11), # NY Open: 10:00 - 11:00 NY
            (14, 15)  # NY Afternoon: 14:00 - 15:00 NY
        ]
        
        # Track trades per session to enforce one trade per window
        self.session_trades = {}
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate FVG-based trading signals on M15 timeframe.
        
        Args:
            data: DataFrame with M15 OHLCV data and DatetimeIndex
            
        Returns:
            DataFrame with trading signals and position management columns
        """
        
        if not self.validate_data(data):
            raise ValueError("Invalid input data format")
        
        # Initialize signal columns
        signals_df = data.copy()
        signals_df['signal'] = 0
        signals_df['position_size'] = 0.0
        signals_df['stop_loss'] = np.nan
        signals_df['take_profit'] = np.nan
        
        # Need sufficient data for analysis
        if len(data) < 100:
            return signals_df
        
        # Detect timeframe - strategy only works with M15 data
        timeframe = self._detect_timeframe(data)
        if timeframe != '15min':
            return signals_df
        
        # Resample M15 data to H4 for H4 FVG detection
        h4_data = data.resample('4h').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        
        # Detect H4 FVGs
        h4_fvgs = self.fvg_detector.detect_fvgs(h4_data, merge_consecutive=True)
        
        # Resample M15 data to daily for daily open filter
        daily_data = data.resample('D').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        
        
        # Detect M15 FVGs
        m15_fvgs = self.fvg_detector.detect_fvgs(data, merge_consecutive=True)
        
        if len(m15_fvgs) == 0:
            return signals_df
            
        if len(h4_fvgs) == 0:
            return signals_df
        
        
        # Generate signals based on FVG formations
        signals_generated = 0
        execution_window_count = 0
        weekend_count = 0
        session_limit_count = 0
        h4_touch_failed_count = 0
        daily_filter_failed_count = 0
        
        for fvg in m15_fvgs:
            # Entry occurs on the close of the 3rd candle (end_idx)
            entry_idx = fvg.end_idx
            
            if entry_idx >= len(data):
                continue
                
            current_time = data.index[entry_idx]
            current_price = data.iloc[entrCy_idx]['lose']
            
            # Check if we're in an execution window
            if not self._is_execution_window(current_time):
                continue
            execution_window_count += 1
                
            # Check if it's a weekend
            if self._is_weekend(current_time):
                weekend_count += 1
                continue
                
            # Check session trade limit
            session_key = self._get_session_key(current_time)
            if session_key in self.session_trades:
                session_limit_count += 1
                continue
            
            # Check if price has touched H4 FVG of the same type before this M15 FVG
            if not self._has_price_touched_h4_fvg(data, h4_data, h4_fvgs, entry_idx, fvg.fvg_type):
                h4_touch_failed_count += 1
                continue
            
            # Check daily open filter condition
            if not self._daily_open_filter(daily_data, current_time, current_price, fvg.fvg_type):
                daily_filter_failed_count += 1
                continue
                
            # Generate signal based on FVG type
            if fvg.fvg_type == 'bullish':
                signal = 1  # Long
                # Stop loss at low of first candle in FVG formation
                stop_loss = data.iloc[fvg.start_idx]['Low']
            elif fvg.fvg_type == 'bearish':
                signal = -1  # Short
                # Stop loss at high of first candle in FVG formation
                stop_loss = data.iloc[fvg.start_idx]['High']
            else:
                continue
            
            # Calculate take profit based on risk/reward ratio
            if signal == 1:  # Long
                risk_distance = current_price - stop_loss
                if risk_distance <= 0:
                    continue  # Invalid stop loss
                take_profit = current_price + (risk_distance * self.risk_reward_ratio)
            else:  # Short
                risk_distance = stop_loss - current_price
                if risk_distance <= 0:
                    continue  # Invalid stop loss
                take_profit = current_price - (risk_distance * self.risk_reward_ratio)
            
            # Set the signal
            signals_df.iloc[entry_idx, signals_df.columns.get_loc('signal')] = signal
            signals_df.iloc[entry_idx, signals_df.columns.get_loc('position_size')] = self.position_size
            signals_df.iloc[entry_idx, signals_df.columns.get_loc('stop_loss')] = stop_loss
            signals_df.iloc[entry_idx, signals_df.columns.get_loc('take_profit')] = take_profit
            
            # Mark this session as traded
            self.session_trades[session_key] = current_time
            signals_generated += 1
            
        
        
        return signals_df
    
    def _detect_timeframe(self, data: pd.DataFrame) -> str:
        """
        Detect the timeframe of the data based on index frequency.
        """
        if len(data) < 2:
            return 'unknown'
        
        # Calculate the most common time difference
        time_diffs = data.index[1:] - data.index[:-1]
        most_common_diff = pd.Series(time_diffs).mode().iloc[0]
        
        if most_common_diff == timedelta(minutes=15):
            return '15min'
        elif most_common_diff == timedelta(hours=1):
            return '1h'
        elif most_common_diff == timedelta(hours=4):
            return '4h'
        else:
            return 'unknown'
    
    def _is_execution_window(self, timestamp: pd.Timestamp) -> bool:
        """
        Check if timestamp falls within execution windows (NY timezone).
        """
        # Convert to NY timezone
        ny_tz = pytz.timezone('America/New_York')
        
        # Convert timestamp to NY time if it's not already
        if timestamp.tz is None:
            # Assume UTC if no timezone info
            timestamp = timestamp.tz_localize('UTC')
        
        ny_time = timestamp.astimezone(ny_tz)
        current_hour = ny_time.hour
        
        # Check if current hour falls within any execution window
        for start_hour, end_hour in self.execution_windows:
            if start_hour <= current_hour < end_hour:
                return True
        
        return False
    
    def _is_weekend(self, timestamp: pd.Timestamp) -> bool:
        """
        Check if timestamp falls on weekend (Saturday/Sunday).
        """
        # Convert to NY timezone for consistent weekend detection
        ny_tz = pytz.timezone('America/New_York')
        
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize('UTC')
            
        ny_time = timestamp.astimezone(ny_tz)
        
        # Saturday = 5, Sunday = 6 in Python's weekday()
        return ny_time.weekday() >= 5
    
    def _get_session_key(self, timestamp: pd.Timestamp) -> str:
        """
        Get session key for tracking trades per session.
        """
        ny_tz = pytz.timezone('America/New_York')
        
        if timestamp.tz is None:
            timestamp = timestamp.tz_localize('UTC')
            
        ny_time = timestamp.astimezone(ny_tz)
        current_hour = ny_time.hour
        
        # Determine which window we're in
        window_id = 0
        for i, (start_hour, end_hour) in enumerate(self.execution_windows):
            if start_hour <= current_hour < end_hour:
                window_id = i
                break
        
        # Create session key: YYYY-MM-DD_window_id
        return f"{ny_time.date()}_{window_id}"
    
    def _daily_open_filter(self, daily_data: pd.DataFrame, current_time: pd.Timestamp, current_price: float, fvg_type: str) -> bool:
        """
        Filter trades based on daily open:
        - Long trades only if price is above daily open
        - Short trades only if price is below daily open
        
        Args:
            daily_data: Daily OHLCV data
            current_time: Current M15 candle timestamp
            current_price: Current price
            fvg_type: 'bullish' or 'bearish'
            
        Returns:
            True if trade direction aligns with daily open filter
        """
        # Find the current day's open price
        current_daily_open = None
        for i, day_start_time in enumerate(daily_data.index):
            # Check if current time falls within this day
            if i + 1 < len(daily_data):
                next_day_start = daily_data.index[i + 1]
                if day_start_time <= current_time < next_day_start:
                    current_daily_open = daily_data.iloc[i]['Open']
                    break
            else:
                # Last day in data
                if day_start_time <= current_time:
                    current_daily_open = daily_data.iloc[i]['Open']
                    break
        
        if current_daily_open is None:
            return False
            
        # Apply daily open filter
        if fvg_type == 'bullish':
            # Long only if price is above daily open
            return current_price > current_daily_open
        elif fvg_type == 'bearish':
            # Short only if price is below daily open
            return current_price < current_daily_open
            
        return False
    
    def _has_price_touched_h4_fvg(self, data: pd.DataFrame, h4_data: pd.DataFrame, h4_fvgs: list, current_idx: int, fvg_type: str) -> bool:
        """
        Check if price has touched (wicked into) any H4 FVG of the same type from the last 9 H4 candles before current M15 candle.
        
        Args:
            data: M15 OHLCV data
            h4_data: H4 OHLCV data  
            h4_fvgs: List of H4 FVGs
            current_idx: Current M15 candle index
            fvg_type: 'bullish' or 'bearish'
            
        Returns:
            True if price has touched an H4 FVG of the same type within lookback period
        """
        current_time = data.index[current_idx]
        
        # Find the H4 candle index that corresponds to current M15 time
        current_h4_idx = None
        for i, h4_time in enumerate(h4_data.index):
            if h4_time <= current_time:
                current_h4_idx = i
            else:
                break
        
        if current_h4_idx is None:
            return False
        
        # Calculate lookback range - only consider H4 FVGs from last 9 H4 candles
        lookback_start_idx = max(0, current_h4_idx - self.h4_lookback_candles + 1)
        
        # Find relevant H4 FVGs of the same type within lookback period that are unmitigated
        relevant_h4_fvgs = []
        for fvg in h4_fvgs:
            if (fvg.fvg_type == fvg_type and 
                fvg.end_idx < len(h4_data) and
                fvg.end_idx >= lookback_start_idx and
                fvg.end_idx < current_h4_idx):
                h4_fvg_end_time = h4_data.index[fvg.end_idx]
                if h4_fvg_end_time < current_time:
                    # Check if H4 FVG is unmitigated from its formation until current H4 candle
                    if self._is_fvg_unmitigated(h4_data, fvg, fvg.end_idx, current_h4_idx):
                        relevant_h4_fvgs.append((fvg, h4_fvg_end_time))
        
        if not relevant_h4_fvgs:
            return False
        
        # Check if price has touched any of these H4 FVGs
        for fvg, fvg_end_time in relevant_h4_fvgs:
            # Look at M15 candles from after H4 FVG formation until current candle
            start_search_idx = None
            for i in range(len(data)):
                if data.index[i] > fvg_end_time:
                    start_search_idx = i
                    break
                    
            if start_search_idx is None:
                continue
                
            # Check if any M15 candle from start_search_idx to current_idx touched the H4 FVG
            for i in range(start_search_idx, min(current_idx + 1, len(data))):
                candle_high = data.iloc[i]['High']
                candle_low = data.iloc[i]['Low']
                
                # Check if candle wicked into the H4 FVG
                if fvg.fvg_type == 'bullish':
                    # For bullish H4 FVG, check if price wicked down into the gap
                    if candle_low <= fvg.top and candle_low >= fvg.bottom:
                        return True
                elif fvg.fvg_type == 'bearish':
                    # For bearish H4 FVG, check if price wicked up into the gap
                    if candle_high >= fvg.bottom and candle_high <= fvg.top:
                        return True
        
        return False
    
    def _is_fvg_unmitigated(self, data: pd.DataFrame, fvg, fvg_end_idx: int, current_idx: int) -> bool:
        """
        Check if an FVG is unmitigated (hasn't been fully retraced).
        
        Args:
            data: OHLCV data (M15 or H1)
            fvg: FVG object
            fvg_end_idx: Index where FVG formation completed
            current_idx: Current candle index to check up to
            
        Returns:
            True if FVG is unmitigated (hasn't been fully closed)
        """
        # Look at all candles from after FVG formation until current candle
        for i in range(fvg_end_idx + 1, min(current_idx, len(data))):
            candle_high = data.iloc[i]['High']
            candle_low = data.iloc[i]['Low']
            
            # Check if FVG has been fully mitigated
            if fvg.fvg_type == 'bullish':
                # Bullish FVG is mitigated if price closes below the bottom of the gap
                if candle_low <= fvg.bottom:
                    return False  # FVG is mitigated
            elif fvg.fvg_type == 'bearish':
                # Bearish FVG is mitigated if price closes above the top of the gap
                if candle_high >= fvg.top:
                    return False  # FVG is mitigated
        
        return True  # FVG is unmitigated
    
    def get_description(self) -> str:
        """Return strategy description."""
        return (f"FVG Strategy (M15 timeframe): H4 unmitigated FVG + Daily open filter + M15 FVG confirmation, "
                f"H4 lookback {self.h4_lookback_candles} candles, R:R ratio {self.risk_reward_ratio}:1, "
                f"execution windows: London Open (03:00-04:00), NY Open (10:00-11:00), "
                f"NY Afternoon (14:00-15:00) NY time. Position size: {self.position_size * 100}%.")
    
    def get_strategy_name(self) -> str:
        """Return strategy name for identification."""
        return self.name