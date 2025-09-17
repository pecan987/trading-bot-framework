"""
Data management for efficient historical data caching and updates
"""
import time
import pandas as pd
from typing import Dict, Optional
import logging


class DataManager:
    """Manages historical and real-time data efficiently"""
    
    def __init__(self, max_bars: int = 1000, cache_duration: int = 60):
        """
        Initialize data manager
        
        Args:
            max_bars: Maximum number of bars to keep in memory
            cache_duration: Cache duration in seconds
        """
        self.max_bars = max_bars
        self.cache_duration = cache_duration
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.last_update: Dict[str, float] = {}
        self.last_bar_time: Dict[str, int] = {}  # Track last bar timestamp
        self.logger = logging.getLogger(__name__)
        
    def get_data_for_signals(self, symbol: str, exchange, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Get data suitable for signal generation
        
        Args:
            symbol: Trading symbol
            exchange: CCXT exchange instance
            timeframe: Timeframe string (e.g., '1h', '4h')
            
        Returns:
            DataFrame with OHLCV data or None if error
        """
        try:
            now = time.time()
            
            # Check if we need to update based on time or new bar availability
            needs_update = self._needs_data_update(symbol, exchange, timeframe, now)
            
            if needs_update:
                # Fetch fresh data - only completed bars
                self.logger.debug(f"Fetching fresh data for {symbol}")
                
                ohlcv = exchange.fetch_ohlcv(
                    symbol, 
                    timeframe, 
                    limit=self.max_bars
                )
                
                if not ohlcv:
                    self.logger.warning(f"No data received for {symbol}")
                    return None
                    
                # Convert to DataFrame
                df = pd.DataFrame(
                    ohlcv, 
                    columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                
                # Remove any duplicate indices
                df = df[~df.index.duplicated(keep='last')]
                
                # Sort by time
                df.sort_index(inplace=True)
                
                # Cache it
                self.data_cache[symbol] = df
                self.last_update[symbol] = now
                
                # Track the last bar timestamp for new bar detection
                if len(ohlcv) > 0:
                    self.last_bar_time[symbol] = ohlcv[-1][0]  # timestamp of last bar
                
                self.logger.debug(f"Cached {len(df)} completed bars for {symbol}")
                
            return self.data_cache[symbol].copy()
            
        except Exception as e:
            self.logger.error(f"Error getting data for {symbol}: {e}")
            return None
            
    def _needs_data_update(self, symbol: str, exchange, timeframe: str, current_time: float) -> bool:
        """
        Determine if we need to fetch new data
        
        Args:
            symbol: Trading symbol
            exchange: CCXT exchange instance
            timeframe: Timeframe string
            current_time: Current timestamp
            
        Returns:
            True if data update is needed
        """
        # Always update if we don't have cached data
        if symbol not in self.data_cache or symbol not in self.last_update:
            return True
            
        # Check time-based update
        time_since_update = current_time - self.last_update[symbol]
        if time_since_update > self.cache_duration:
            return True
            
        # Check if a new bar might be available
        # Only check if enough time has passed for a potential new bar
        timeframe_seconds = self.get_timeframe_seconds(timeframe)
        if time_since_update > timeframe_seconds * 0.1:  # Check after 10% of timeframe
            try:
                # Quick check - fetch just the latest bar to see if it's newer
                latest_ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=1)
                if latest_ohlcv and len(latest_ohlcv) > 0:
                    latest_bar_time = latest_ohlcv[0][0]
                    last_known_time = self.last_bar_time.get(symbol, 0)
                    
                    # If we have a newer bar, update
                    if latest_bar_time > last_known_time:
                        self.logger.debug(f"New bar detected for {symbol}")
                        return True
            except Exception as e:
                self.logger.debug(f"Error checking for new bar: {e}")
                # If we can't check, fall back to time-based update
                pass
                
        return False
        
    def update_latest_bars(self, symbol: str, exchange, timeframe: str) -> bool:
        """
        Update with latest completed bars only
        
        Args:
            symbol: Trading symbol
            exchange: CCXT exchange instance
            timeframe: Timeframe string
            
        Returns:
            True if update successful
        """
        try:
            if symbol not in self.data_cache:
                # Need full data first
                self.get_data_for_signals(symbol, exchange, timeframe)
                return True
                
            # Fetch recent bars (only completed ones)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=10)
            
            if not ohlcv:
                return False
                
            # Convert to DataFrame
            df_new = pd.DataFrame(
                ohlcv, 
                columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
            )
            df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms')
            df_new.set_index('timestamp', inplace=True)
            
            # Update cached data with new bars
            cached_df = self.data_cache[symbol]
            
            # Find bars that are newer than what we have
            if len(cached_df) > 0:
                last_cached_time = cached_df.index[-1]
                new_bars = df_new[df_new.index > last_cached_time]
            else:
                new_bars = df_new
                
            if len(new_bars) > 0:
                # Append new bars
                updated_df = pd.concat([cached_df, new_bars])
                # Remove duplicates and sort
                updated_df = updated_df[~updated_df.index.duplicated(keep='last')]
                updated_df.sort_index(inplace=True)
                
                # Trim to max_bars
                if len(updated_df) > self.max_bars:
                    updated_df = updated_df.iloc[-self.max_bars:]
                    
                self.data_cache[symbol] = updated_df
                self.last_update[symbol] = time.time()
                
                # Update last bar time
                self.last_bar_time[symbol] = ohlcv[-1][0]
                
                self.logger.debug(f"Added {len(new_bars)} new bars for {symbol}")
                
            return True
                
        except Exception as e:
            self.logger.error(f"Error updating bars for {symbol}: {e}")
            return False
            
    def clear_cache(self, symbol: Optional[str] = None):
        """Clear cached data"""
        if symbol:
            self.data_cache.pop(symbol, None)
            self.last_update.pop(symbol, None)
            self.last_bar_time.pop(symbol, None)
        else:
            self.data_cache.clear()
            self.last_update.clear()
            self.last_bar_time.clear()
            
    def get_timeframe_seconds(self, timeframe: str) -> int:
        """Convert timeframe string to seconds"""
        units = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
            'M': 2592000  # 30 days
        }
        
        # Parse timeframe (e.g., '1h', '4h', '15m')
        import re
        match = re.match(r'(\d+)([smhdwM])', timeframe)
        if match:
            num, unit = match.groups()
            return int(num) * units.get(unit, 3600)
        
        return 3600  # Default to 1 hour