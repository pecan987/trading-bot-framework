#!/usr/bin/env python3
"""
Mean Reversion Strategy

A statistical arbitrage strategy that trades when price deviates significantly from its mean,
expecting it to revert back. Uses Z-score, RSI, and ADX filters for robust signal generation.

Strategy Logic:
1. Calculate Z-score based on rolling mean and standard deviation
2. Enter SHORT when: Z-score > +2, RSI > 70 (overbought), ADX < 35 (low trend strength)
3. Enter LONG when: Z-score < -2, RSI < 30 (oversold), ADX < 35 (low trend strength)  
4. Exit when Z-score crosses back to 0 (mean reversion) OR hit SL/TP levels
5. Use ATR-based stop losses and take profits for risk management

Author: Claude Code
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from tqdm import tqdm
from .base_strategy import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """
    Z-Score based Mean Reversion Strategy
    
    Identifies overbought/oversold conditions using statistical measures
    and trades expecting price to revert to the mean.
    """
    
    def __init__(self, lookback_period: int = 20, z_threshold: float = 2.0,
                 rsi_period: int = 14, rsi_oversold: float = 30, rsi_overbought: float = 70,
                 atr_period: int = 14, atr_multiplier: float = 2.0, atr_tp_multiplier: float = 3.0,
                 adx_period: int = 14, adx_threshold: float = 35,
                 use_rsi_filter: bool = True, use_adx_filter: bool = True,
                 position_size: float = 0.01):
        
        parameters = {
            "lookback_period": lookback_period,
            "z_threshold": z_threshold,
            "rsi_period": rsi_period,
            "rsi_oversold": rsi_oversold,
            "rsi_overbought": rsi_overbought,
            "atr_period": atr_period,
            "atr_multiplier": atr_multiplier,
            "atr_tp_multiplier": atr_tp_multiplier,
            "adx_period": adx_period,
            "adx_threshold": adx_threshold,
            "use_rsi_filter": use_rsi_filter,
            "use_adx_filter": use_adx_filter,
            "position_size": position_size,
        }
        
        super().__init__("MeanReversion", parameters)
        self.params = parameters
        self.min_bars_required = max(lookback_period, rsi_period, atr_period, adx_period) + 10  # Need enough data for all indicators
        
    def get_strategy_name(self) -> str:
        return f"MeanReversion_{self.params['lookback_period']}_{self.params['z_threshold']}"
    
    def get_description(self) -> str:
        """Get strategy description"""
        return (f"Mean Reversion Strategy using Z-Score with {self.params['lookback_period']}-period lookback. "
                f"Threshold: ±{self.params['z_threshold']}, SL: {self.params['atr_multiplier']}x ATR, "
                f"TP: {self.params['atr_tp_multiplier']}x ATR, RSI filter: {self.params['use_rsi_filter']}, "
                f"ADX filter: {self.params['use_adx_filter']}, Position size: {self.params['position_size']:.1%}")

    def calculate_atr(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range"""
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        # True Range calculation
        hl = high - low
        hc = np.abs(high - close.shift(1))
        lc = np.abs(low - close.shift(1))
        
        true_range = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = true_range.rolling(window=self.params['atr_period']).mean()
        
        return atr

    def calculate_rsi(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.params['rsi_period']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.params['rsi_period']).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi

    def calculate_adx(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Average Directional Index (ADX)"""
        high = data['High']
        low = data['Low']
        close = data['Close']
        
        # Calculate +DM and -DM
        up_move = high.diff()
        down_move = -low.diff()
        
        plus_dm = pd.Series(0.0, index=data.index)
        minus_dm = pd.Series(0.0, index=data.index)
        
        # +DM occurs when up_move > down_move and up_move > 0
        plus_dm[(up_move > down_move) & (up_move > 0)] = up_move[(up_move > down_move) & (up_move > 0)]
        # -DM occurs when down_move > up_move and down_move > 0
        minus_dm[(down_move > up_move) & (down_move > 0)] = down_move[(down_move > up_move) & (down_move > 0)]
        
        # Calculate True Range (ATR denominator)
        atr = self.calculate_atr(data)
        
        # Calculate +DI and -DI
        plus_di = 100 * (plus_dm.rolling(window=self.params['adx_period']).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=self.params['adx_period']).mean() / atr)
        
        # Calculate DX
        dx = 100 * (np.abs(plus_di - minus_di) / (plus_di + minus_di))
        
        # Calculate ADX as smoothed average of DX
        adx = dx.rolling(window=self.params['adx_period']).mean()
        
        return adx

    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators to the data"""
        data = data.copy()
        
        # Calculate rolling statistics
        data['sma'] = data['Close'].rolling(window=self.params['lookback_period']).mean()
        data['std'] = data['Close'].rolling(window=self.params['lookback_period']).std()
        data['z_score'] = (data['Close'] - data['sma']) / data['std']
        
        # Calculate technical indicators
        data['rsi'] = self.calculate_rsi(data)
        data['adx'] = self.calculate_adx(data)
        data['atr'] = self.calculate_atr(data)
        
        return data

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate mean reversion signals"""
        if not self.validate_data(data):
            raise ValueError("Invalid data format")
            
        data_with_indicators = self.add_indicators(data)
        
        result = data.copy()
        result['signal'] = 0
        result['position_size'] = self.params['position_size']
        result['stop_loss'] = None
        result['take_profit'] = None
        
        position_type = None  # Track current position: 'long', 'short', or None
        
        # Create progress bar
        progress_bar = tqdm(range(len(data)), desc="🔄 Generating mean reversion signals", 
                           unit="bars", leave=False, disable=len(data) < 100)
        
        signals_generated = 0
        
        for i in progress_bar:
            # Need enough data for all indicators
            min_bars = max(self.params['lookback_period'], 
                          self.params['rsi_period'], 
                          self.params['adx_period'],
                          self.params['atr_period'])
            if i < min_bars:
                continue
                
            current_price = data['Close'].iloc[i]
            z_score = data_with_indicators['z_score'].iloc[i]
            rsi = data_with_indicators['rsi'].iloc[i]
            adx = data_with_indicators['adx'].iloc[i]
            atr = data_with_indicators['atr'].iloc[i]
            
            # Skip if any indicator is NaN
            if pd.isna(z_score) or pd.isna(rsi) or pd.isna(adx) or pd.isna(atr):
                continue
            
            # Update progress bar with current status
            if i % 50 == 0:
                timestamp = data.index[i].strftime('%Y-%m-%d %H:%M') if hasattr(data.index[i], 'strftime') else str(data.index[i])
                progress_bar.set_postfix({
                    'Time': timestamp,
                    'Position': position_type or 'Flat',
                    'Signals': signals_generated,
                    'Z-Score': f"{z_score:.2f}",
                    'RSI': f"{rsi:.1f}"
                })
            
            # Exit conditions (mean reversion)
            if position_type == 'long' and z_score >= 0:
                # Exit long when Z-score reverts to mean
                result.iloc[i, result.columns.get_loc('signal')] = -1
                position_type = None
                signals_generated += 1
                
            elif position_type == 'short' and z_score <= 0:
                # Exit short when Z-score reverts to mean  
                result.iloc[i, result.columns.get_loc('signal')] = 1
                position_type = None
                signals_generated += 1
            
            # Entry conditions (only when flat)
            elif position_type is None:
                # Long signal: Oversold conditions
                if (z_score < -self.params['z_threshold'] and 
                    (not self.params['use_rsi_filter'] or rsi < self.params['rsi_oversold']) and
                    (not self.params['use_adx_filter'] or adx < self.params['adx_threshold'])):
                    
                    result.iloc[i, result.columns.get_loc('signal')] = 1
                    result.iloc[i, result.columns.get_loc('stop_loss')] = current_price - (atr * self.params['atr_multiplier'])
                    result.iloc[i, result.columns.get_loc('take_profit')] = current_price + (atr * self.params['atr_tp_multiplier'])
                    position_type = 'long'
                    signals_generated += 1
                    
                # Short signal: Overbought conditions
                elif (z_score > self.params['z_threshold'] and 
                      (not self.params['use_rsi_filter'] or rsi > self.params['rsi_overbought']) and
                      (not self.params['use_adx_filter'] or adx < self.params['adx_threshold'])):
                    
                    result.iloc[i, result.columns.get_loc('signal')] = -1
                    result.iloc[i, result.columns.get_loc('stop_loss')] = current_price + (atr * self.params['atr_multiplier'])
                    result.iloc[i, result.columns.get_loc('take_profit')] = current_price - (atr * self.params['atr_tp_multiplier'])
                    position_type = 'short'
                    signals_generated += 1
        
        progress_bar.close()
        
        return result


# Alias for backward compatibility
ZScoreStrategy = MeanReversionStrategy