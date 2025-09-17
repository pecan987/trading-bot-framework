import pandas as pd
import numpy as np
from typing import Dict, Any
from tqdm import tqdm
from .base_strategy import BaseStrategy
from .detectors.swing_detector import SwingDetector
from .detectors.bos_detector import BoSDetector
from .detectors.choch_detector import ChOChDetector
from .detectors.liquidity_objective_detector import LiquidityObjectiveDetector, TradeDirection


class BreakoutStrategy(BaseStrategy):
    """
    Simplified Liquidity Breakout Strategy
    
    Entry: Breakout detection + OBV confirmation after liquidity grab
    Exit: Target liquidity objectives or ATR-based stops
    Uses proper swing/structure breakouts and liquidity detectors
    """

    def __init__(self, swing_sensitivity: int = 3, bos_lookback: int = 20,
                 obv_period: int = 20, liquidity_timeframe: str = '4h',
                 atr_period: int = 14, atr_multiplier: float = 2.0,
                 position_size: float = 0.01):
        
        parameters = {
            "swing_sensitivity": swing_sensitivity,
            "bos_lookback": bos_lookback,
            "obv_period": obv_period,
            "liquidity_timeframe": liquidity_timeframe,
            "atr_period": atr_period,
            "atr_multiplier": atr_multiplier,
            "position_size": position_size,
        }
        
        # Initialize detectors
        self.swing_detector = SwingDetector(sensitivity=swing_sensitivity)
        self.bos_detector = BoSDetector()
        self.choch_detector = ChOChDetector()
        self.liquidity_detector = LiquidityObjectiveDetector()
        
        super().__init__("Breakout", parameters)
        self.params = parameters
        self.min_bars_required = max(swing_sensitivity, bos_lookback, obv_period, atr_period) + 10  # Need enough data for all indicators
        
    def get_strategy_name(self) -> str:
        return f"LiquidityBreakout_{self.params['swing_sensitivity']}_{self.params['bos_lookback']}"

    def calculate_atr(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range"""
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        hl = high - low
        hc = np.abs(high - close.shift(1))
        lc = np.abs(low - close.shift(1))
        
        true_range = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = true_range.rolling(window=self.params['atr_period']).mean()
        
        return atr
    
    def calculate_obv(self, data: pd.DataFrame) -> pd.Series:
        """Calculate On-Balance Volume"""
        close = data['Close']
        volume = data['Volume']
        
        obv = pd.Series(index=data.index, dtype=float)
        obv.iloc[0] = volume.iloc[0]
        
        for i in range(1, len(data)):
            if close.iloc[i] > close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
            elif close.iloc[i] < close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]
                
        return obv
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add breakout detection indicators and liquidity analysis"""
        data = data.copy()
        
        # Detect swing highs and lows
        swing_highs = self.swing_detector.find_all_swing_highs(data['High'])
        swing_lows = self.swing_detector.find_all_swing_lows(data['Low'])
        
        data['swing_high'] = np.nan
        data['swing_low'] = np.nan
        
        for idx, price in swing_highs:
            if idx < len(data):
                data.iloc[idx, data.columns.get_loc('swing_high')] = price
        
        for idx, price in swing_lows:
            if idx < len(data):
                data.iloc[idx, data.columns.get_loc('swing_low')] = price
        
        # Detect Break of Structure (BoS)
        bos_df = self.bos_detector.detect_bos_events(data)
        data['bos_bullish'] = False
        data['bos_bearish'] = False
        
        for _, bos in bos_df.iterrows():
            if bos['bos_type'] == 'bullish':
                bos_idx = data.index.get_loc(bos['timestamp']) if bos['timestamp'] in data.index else None
                if bos_idx is not None:
                    data.iloc[bos_idx, data.columns.get_loc('bos_bullish')] = True
            elif bos['bos_type'] == 'bearish':
                bos_idx = data.index.get_loc(bos['timestamp']) if bos['timestamp'] in data.index else None
                if bos_idx is not None:
                    data.iloc[bos_idx, data.columns.get_loc('bos_bearish')] = True
        
        # OBV and smoothed OBV for confirmation
        data['obv'] = self.calculate_obv(data)
        data['obv_sma'] = data['obv'].rolling(window=self.params['obv_period']).mean()
        data['obv_signal'] = data['obv'] > data['obv_sma']
        
        # ATR for position sizing and stops
        data['atr'] = self.calculate_atr(data)
        
        return data

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate liquidity-based breakout signals using proper structure breakouts"""
        if not self.validate_data(data):
            raise ValueError("Invalid data format")
            
        data_with_indicators = self.add_indicators(data)
        
        result = data.copy()
        result['signal'] = 0
        result['position_size'] = self.params['position_size']
        result['stop_loss'] = None
        result['take_profit'] = None
        
        position_type = None
        entry_price = None
        target_price = None
        
        # Create progress bar for signal generation
        progress_bar = tqdm(range(len(data)), desc="🔍 Generating breakout signals", 
                           unit="bars", leave=False, disable=len(data) < 100)
        
        signals_generated = 0
        
        for i in progress_bar:
            min_bars = max(self.params['bos_lookback'], 
                          self.params['obv_period'], 
                          self.params['atr_period'])
            if i < min_bars:
                continue
                
            current_close = data['Close'].iloc[i]
            current_high = data['High'].iloc[i]
            current_low = data['Low'].iloc[i]
            
            # Get breakout signals
            bos_bullish = data_with_indicators['bos_bullish'].iloc[i]
            bos_bearish = data_with_indicators['bos_bearish'].iloc[i]
            obv_signal = data_with_indicators['obv_signal'].iloc[i]
            atr = data_with_indicators['atr'].iloc[i]
            
            # Update progress bar with current status
            if i % 50 == 0:  # Update every 50 bars to avoid too frequent updates
                timestamp = data.index[i].strftime('%Y-%m-%d %H:%M') if hasattr(data.index[i], 'strftime') else str(data.index[i])
                progress_bar.set_postfix({
                    'Time': timestamp,
                    'Position': position_type or 'Flat',
                    'Signals': signals_generated,
                    'Price': f"${current_close:,.2f}" if current_close > 1 else f"{current_close:.6f}"
                })
            
            if position_type is None:
                # Long Entry: Bullish BoS + OBV confirmation
                if bos_bullish and obv_signal:
                    # Get liquidity objectives for long trade
                    current_data = data[:i+1]
                    objectives = self.liquidity_detector.detect_objectives(
                        current_data, TradeDirection.BULLISH, current_close
                    )
                    
                    if objectives and not pd.isna(atr):
                        result.iloc[i, result.columns.get_loc('signal')] = 1
                        entry_price = current_close
                        position_type = 'long'
                        target_price = objectives[0].price  # First (highest priority) objective
                        signals_generated += 1
                        
                        stop_loss = entry_price - (atr * self.params['atr_multiplier'])
                        result.iloc[i, result.columns.get_loc('stop_loss')] = stop_loss
                        result.iloc[i, result.columns.get_loc('take_profit')] = target_price
                
                # Short Entry: Bearish BoS + OBV confirmation
                elif bos_bearish and not obv_signal:
                    # Get liquidity objectives for short trade
                    current_data = data[:i+1]
                    objectives = self.liquidity_detector.detect_objectives(
                        current_data, TradeDirection.BEARISH, current_close
                    )
                    
                    if objectives and not pd.isna(atr):
                        result.iloc[i, result.columns.get_loc('signal')] = -1
                        entry_price = current_close
                        position_type = 'short'
                        target_price = objectives[0].price  # First (highest priority) objective
                        signals_generated += 1
                        
                        stop_loss = entry_price + (atr * self.params['atr_multiplier'])
                        result.iloc[i, result.columns.get_loc('stop_loss')] = stop_loss
                        result.iloc[i, result.columns.get_loc('take_profit')] = target_price
            
            elif position_type == 'long':
                # Maintain stop loss and take profit during position
                if not pd.isna(atr) and entry_price is not None:
                    stop_loss = entry_price - (atr * self.params['atr_multiplier'])
                    result.iloc[i, result.columns.get_loc('stop_loss')] = stop_loss
                    result.iloc[i, result.columns.get_loc('take_profit')] = target_price
                
                # Exit at liquidity target or stop loss
                if current_high >= target_price or current_low <= (entry_price - atr * self.params['atr_multiplier']):
                    result.iloc[i, result.columns.get_loc('signal')] = -1
                    position_type = None
                    entry_price = None
                    target_price = None
                    
            elif position_type == 'short':
                # Maintain stop loss and take profit during position
                if not pd.isna(atr) and entry_price is not None:
                    stop_loss = entry_price + (atr * self.params['atr_multiplier'])
                    result.iloc[i, result.columns.get_loc('stop_loss')] = stop_loss
                    result.iloc[i, result.columns.get_loc('take_profit')] = target_price
                
                # Exit at liquidity target or stop loss
                if current_low <= target_price or current_high >= (entry_price + atr * self.params['atr_multiplier']):
                    result.iloc[i, result.columns.get_loc('signal')] = 1
                    position_type = None
                    entry_price = None
                    target_price = None
        
        return result

    def get_description(self) -> str:
        """Return strategy description."""
        return (f"Liquidity Breakout Strategy with swing sensitivity {self.params['swing_sensitivity']}, "
                f"{self.params['bos_lookback']}-period BoS lookback, {self.params['obv_period']}-period OBV confirmation, "
                f"and {self.params['liquidity_timeframe']} liquidity objectives. "
                f"Stop loss: {self.params['atr_multiplier']}x ATR. Position size: {self.params['position_size'] * 100}%.")