"""
Swing Failure Pattern (SFP) Strategy

This strategy detects swing failure patterns using pivot highs and lows.
A bearish SFP occurs when price breaks above a pivot high but closes below it.
A bullish SFP occurs when price breaks below a pivot low but closes above it.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from .base_strategy import BaseStrategy, Signal
from .detectors.pivot_detector import PivotDetector


class SFPStrategy(BaseStrategy):
    """
    Swing Failure Pattern Strategy
    
    Parameters:
        left_bars: Number of bars to the left for pivot detection (default: 5)
        right_bars: Number of bars to the right for pivot detection (default: 5)
        lookback_pivots: Number of unmitigated pivot points to look back (default: 10)
        max_swing_back: Max bars for price to return below/above pivot for SFP (default: 5)
        min_break_percent: Minimum percentage break required (default: 0.1%)
        stop_loss_percent: Stop loss percentage from entry (default: 2%)
        take_profit_percent: Take profit percentage from entry (default: 4%)
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        super().__init__(params)
        
        # Default parameters
        default_params = {
            'left_bars': 20,
            'right_bars': 20,
            'lookback_pivots': 100,  # Number of unmitigated pivots to consider
            'max_swing_back': 3,    # Max bars for price to return for SFP
            'min_break_percent': 0.001,  # 0.1%
            'stop_loss_percent': 0.02,   # 2%
            'take_profit_percent': 0.04  # 4%
        }
        
        # Merge with provided params
        self.params = {**default_params, **(params or {})}
        
        # Initialize pivot detector
        self.pivot_detector = PivotDetector()
        
        # Set minimum bars required
        self.min_bars_required = self.params['left_bars'] + self.params['right_bars'] + 1
        
        # Track detected pivots and SFPs
        self.pivot_highs: List[Tuple[int, float]] = []  # (index, value)
        self.pivot_lows: List[Tuple[int, float]] = []  # (index, value)
        self.mitigated_highs: set = set()  # Indices of mitigated pivot highs
        self.mitigated_lows: set = set()  # Indices of mitigated pivot lows
        self.last_sfp_bar = -1  # Track last SFP to avoid duplicate signals
        
    def get_strategy_name(self) -> str:
        """Returns strategy name"""
        return "SFP Strategy"
    
    def _detect_bearish_sfp(self, data: pd.DataFrame, current_idx: int) -> Tuple[bool, Optional[int]]:
        """
        Detect bearish SFP: Price breaks above pivot high but returns below within max_swing_back bars
        
        Args:
            data: DataFrame with OHLCV data
            current_idx: Current bar index
            
        Returns:
            Tuple of (True if bearish SFP detected, pivot index if detected)
        """
        if current_idx < 1:
            return False, None
            
        # Get unmitigated pivot highs
        unmitigated_highs = [(idx, val) for idx, val in self.pivot_highs 
                           if idx not in self.mitigated_highs]
        
        # Sort by index (most recent first) and take only lookback_pivots
        unmitigated_highs.sort(key=lambda x: x[0], reverse=True)
        unmitigated_highs = unmitigated_highs[:self.params['lookback_pivots']]
        
        # Look back max_swing_back bars to find breaks
        lookback_start = max(0, current_idx - self.params['max_swing_back'])
        
        for pivot_idx, pivot_value in unmitigated_highs:
            # Skip if pivot is too recent (need at least right_bars between)
            if pivot_idx >= lookback_start:
                continue
                
            # Check if any bar in the lookback period broke above pivot
            broke_above = False
            break_bar_idx = -1
            
            for i in range(lookback_start, current_idx + 1):
                if data['High'].iloc[i] > pivot_value * (1 + self.params['min_break_percent']):
                    broke_above = True
                    break_bar_idx = i
                    break
                    
            if broke_above:
                # Check if current bar closes below pivot (failure)
                current_close = data['Close'].iloc[current_idx]
                if current_close < pivot_value:
                    return True, pivot_idx
                        
        return False, None
    
    def _detect_bullish_sfp(self, data: pd.DataFrame, current_idx: int) -> Tuple[bool, Optional[int]]:
        """
        Detect bullish SFP: Price breaks below pivot low but returns above within max_swing_back bars
        
        Args:
            data: DataFrame with OHLCV data
            current_idx: Current bar index
            
        Returns:
            Tuple of (True if bullish SFP detected, pivot index if detected)
        """
        if current_idx < 1:
            return False, None
            
        # Get unmitigated pivot lows
        unmitigated_lows = [(idx, val) for idx, val in self.pivot_lows 
                          if idx not in self.mitigated_lows]
        
        # Sort by index (most recent first) and take only lookback_pivots
        unmitigated_lows.sort(key=lambda x: x[0], reverse=True)
        unmitigated_lows = unmitigated_lows[:self.params['lookback_pivots']]
        
        # Look back max_swing_back bars to find breaks
        lookback_start = max(0, current_idx - self.params['max_swing_back'])
        
        for pivot_idx, pivot_value in unmitigated_lows:
            # Skip if pivot is too recent (need at least right_bars between)
            if pivot_idx >= lookback_start:
                continue
                
            # Check if any bar in the lookback period broke below pivot
            broke_below = False
            break_bar_idx = -1
            
            for i in range(lookback_start, current_idx + 1):
                if data['Low'].iloc[i] < pivot_value * (1 - self.params['min_break_percent']):
                    broke_below = True
                    break_bar_idx = i
                    break
                    
            if broke_below:
                # Check if current bar closes above pivot (failure)
                current_close = data['Close'].iloc[current_idx]
                if current_close > pivot_value:
                    return True, pivot_idx
                        
        return False, None
    
    def _update_pivots(self, data: pd.DataFrame, end_idx: int):
        """
        Update pivot highs and lows up to the specified index
        
        Args:
            data: DataFrame with OHLCV data
            end_idx: Index to update pivots up to
        """
        # Calculate the valid range for pivot detection
        start_idx = max(self.params['left_bars'], len(self.pivot_highs))
        end_idx = min(end_idx, len(data) - self.params['right_bars'] - 1)
        
        if start_idx >= end_idx:
            return
            
        # Detect new pivot highs
        highs = data['High'].iloc[start_idx - self.params['left_bars']:end_idx + self.params['right_bars'] + 1]
        new_highs = self.pivot_detector.find_all_pivot_highs(
            highs,
            self.params['left_bars'],
            self.params['right_bars']
        )
        
        # Adjust indices and add to list
        for idx, value in new_highs:
            adjusted_idx = start_idx - self.params['left_bars'] + idx
            if adjusted_idx >= start_idx:
                self.pivot_highs.append((adjusted_idx, value))
                
        # Detect new pivot lows
        lows = data['Low'].iloc[start_idx - self.params['left_bars']:end_idx + self.params['right_bars'] + 1]
        new_lows = self.pivot_detector.find_all_pivot_lows(
            lows,
            self.params['left_bars'],
            self.params['right_bars']
        )
        
        # Adjust indices and add to list
        for idx, value in new_lows:
            adjusted_idx = start_idx - self.params['left_bars'] + idx
            if adjusted_idx >= start_idx:
                self.pivot_lows.append((adjusted_idx, value))
                
        # Clean up old mitigated pivots (keep memory usage reasonable)
        if len(self.mitigated_highs) > 100:
            min_idx = min(idx for idx, _ in self.pivot_highs) if self.pivot_highs else 0
            self.mitigated_highs = {idx for idx in self.mitigated_highs if idx >= min_idx}
        if len(self.mitigated_lows) > 100:
            min_idx = min(idx for idx, _ in self.pivot_lows) if self.pivot_lows else 0
            self.mitigated_lows = {idx for idx in self.mitigated_lows if idx >= min_idx}
    
    def _update_mitigated_pivots(self, data: pd.DataFrame, current_idx: int):
        """
        Update which pivots have been mitigated by price action
        
        A pivot high is mitigated when price closes above it (beyond max_swing_back period)
        A pivot low is mitigated when price closes below it (beyond max_swing_back period)
        """
        current_close = data['Close'].iloc[current_idx]
        
        # Check pivot highs for mitigation
        for pivot_idx, pivot_value in self.pivot_highs:
            if pivot_idx not in self.mitigated_highs and pivot_idx < current_idx:
                # Only mitigate if we're beyond the max_swing_back period
                if current_idx - pivot_idx > self.params['max_swing_back']:
                    if current_close > pivot_value:
                        self.mitigated_highs.add(pivot_idx)
                        
        # Check pivot lows for mitigation
        for pivot_idx, pivot_value in self.pivot_lows:
            if pivot_idx not in self.mitigated_lows and pivot_idx < current_idx:
                # Only mitigate if we're beyond the max_swing_back period
                if current_idx - pivot_idx > self.params['max_swing_back']:
                    if current_close < pivot_value:
                        self.mitigated_lows.add(pivot_idx)
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals based on SFP detection
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            DataFrame with signal, stop_loss, and take_profit columns
        """
        # Ensure we have enough data
        if len(data) < self.min_bars_required:
            return pd.DataFrame({
                'signal': [0] * len(data),
                'stop_loss': [np.nan] * len(data),
                'take_profit': [np.nan] * len(data)
            }, index=data.index)
            
        # Initialize signal arrays
        signals = np.zeros(len(data))
        stop_losses = np.full(len(data), np.nan)
        take_profits = np.full(len(data), np.nan)
        
        # Process each bar
        for i in range(self.min_bars_required, len(data)):
            # Update pivots up to current bar minus right_bars
            self._update_pivots(data, i - self.params['right_bars'])
            
            # Update mitigated pivots
            self._update_mitigated_pivots(data, i)
            
            # Skip if we just had an SFP signal (avoid duplicates)
            if i - self.last_sfp_bar < 3:
                continue
                
            # Check for bearish SFP (sell signal)
            bearish_sfp, bearish_pivot_idx = self._detect_bearish_sfp(data, i)
            if bearish_sfp:
                signals[i] = Signal.SELL.value
                entry_price = data['Close'].iloc[i]
                stop_losses[i] = entry_price * (1 + self.params['stop_loss_percent'])
                take_profits[i] = entry_price * (1 - self.params['take_profit_percent'])
                self.last_sfp_bar = i
                # Mark the pivot as mitigated since SFP occurred
                if bearish_pivot_idx is not None:
                    self.mitigated_highs.add(bearish_pivot_idx)
                
            # Check for bullish SFP (buy signal)
            else:
                bullish_sfp, bullish_pivot_idx = self._detect_bullish_sfp(data, i)
                if bullish_sfp:
                    signals[i] = Signal.BUY.value
                    entry_price = data['Close'].iloc[i]
                    stop_losses[i] = entry_price * (1 - self.params['stop_loss_percent'])
                    take_profits[i] = entry_price * (1 + self.params['take_profit_percent'])
                    self.last_sfp_bar = i
                    # Mark the pivot as mitigated since SFP occurred
                    if bullish_pivot_idx is not None:
                        self.mitigated_lows.add(bullish_pivot_idx)
        
        # Create result DataFrame
        result = pd.DataFrame({
            'signal': signals,
            'stop_loss': stop_losses,
            'take_profit': take_profits
        }, index=data.index)
        
        return result
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add SFP-specific indicators to the dataset
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            DataFrame with additional indicator columns
        """
        # Reset state for new data
        self.pivot_highs = []
        self.pivot_lows = []
        self.mitigated_highs = set()
        self.mitigated_lows = set()
        self.last_sfp_bar = -1
        
        # Detect all pivots
        if len(data) >= self.min_bars_required:
            # Find all pivot highs
            highs = self.pivot_detector.find_all_pivot_highs(
                data['High'],
                self.params['left_bars'],
                self.params['right_bars']
            )
            self.pivot_highs = highs
            
            # Find all pivot lows
            lows = self.pivot_detector.find_all_pivot_lows(
                data['Low'],
                self.params['left_bars'],
                self.params['right_bars']
            )
            self.pivot_lows = lows
            
            # Add pivot markers to data
            data['pivot_high'] = np.nan
            data['pivot_low'] = np.nan
            
            for idx, value in highs:
                if idx < len(data):
                    data.loc[data.index[idx], 'pivot_high'] = value
                    
            for idx, value in lows:
                if idx < len(data):
                    data.loc[data.index[idx], 'pivot_low'] = value
        
        return data