"""
Position synchronization with exchange
"""
import logging
from typing import Dict, List, Any, Optional
import ccxt


class PositionSynchronizer:
    """Synchronizes local position state with exchange"""
    
    def __init__(self, exchange: ccxt.Exchange, logger: Optional[logging.Logger] = None):
        self.exchange = exchange
        self.logger = logger or logging.getLogger(__name__)
        
    def sync_positions(self, known_symbols: List[str], saved_positions: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Sync positions with exchange (supports both spot and futures)
        
        Args:
            known_symbols: List of symbols we're tracking
            saved_positions: Previously saved positions
            
        Returns:
            Dict of synchronized positions
        """
        if saved_positions is None:
            saved_positions = {}
            
        try:
            # Determine trading type
            trading_type = getattr(self.exchange, 'options', {}).get('defaultType', 'spot')
            
            if trading_type == 'future':
                return self._sync_futures_positions(known_symbols, saved_positions)
            else:
                return self._sync_spot_positions(known_symbols, saved_positions)
                
        except Exception as e:
            self.logger.error(f"Failed to sync positions: {e}")
            return saved_positions or {}
            
    def _sync_futures_positions(self, known_symbols: List[str], saved_positions: Dict[str, Any]) -> Dict[str, Any]:
        """Sync futures positions using fetch_positions()"""
        try:
            # Get all futures positions
            exchange_positions = self.exchange.fetch_positions()
            seen_symbols = set()
            positions = {}
            
            # Convert exchange positions to our format
            for pos in exchange_positions:
                symbol = pos['symbol']
                
                # Only process symbols we're tracking
                if symbol in known_symbols:
                    position_size = pos.get('contracts', 0) or pos.get('size', 0)
                    
                    # Only track non-zero positions
                    if abs(position_size) > 0.0001:
                        side = pos.get('side', 'long')
                        entry_price = pos.get('entryPrice') or pos.get('markPrice')
                        
                        # Use signed size (positive for long, negative for short)
                        if side == 'short':
                            position_size = -abs(position_size)
                        else:
                            position_size = abs(position_size)
                            
                        saved_pos = saved_positions.get(symbol, {})
                        
                        positions[symbol] = {
                            'size': position_size,
                            'entry_price': entry_price,
                            'side': side,
                            'unrealized_pnl': pos.get('unrealizedPnl', 0),
                            'percentage': pos.get('percentage', 0),
                            'contracts': pos.get('contracts', position_size),
                            'synchronized': True,
                            'verified': True
                        }
                        
                        # Log discovered position
                        self.logger.warning(
                            f"Found existing {side} position: {symbol} "
                            f"size={position_size}, entry={entry_price}"
                        )
                        
                        seen_symbols.add(symbol)
                        
            # Check for positions in saved state that no longer exist
            for symbol, saved_pos in saved_positions.items():
                if symbol not in seen_symbols and abs(saved_pos.get('size', 0)) > 0.0001:
                    self.logger.warning(
                        f"Saved position for {symbol} not found on exchange, marking as closed"
                    )
                    
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to sync futures positions: {e}")
            return saved_positions or {}
            
    def _sync_spot_positions(self, known_symbols: List[str], saved_positions: Dict[str, Any]) -> Dict[str, Any]:
        """Sync spot positions using fetch_balance()"""
        try:
            # Get current balance from exchange
            balance = self.exchange.fetch_balance()
            
            # Track which saved positions we've seen
            seen_symbols = set()
            positions = {}
            
            # Process each known symbol
            for symbol in known_symbols:
                try:
                    base, quote = symbol.split('/')
                    
                    # Check if we have a position in base currency
                    base_balance = balance.get(base, {})
                    base_total = base_balance.get('total', 0)
                    base_free = base_balance.get('free', 0)
                    base_used = base_balance.get('used', 0)
                    
                    # Consider it a position if we have any balance
                    if base_total > 0.0001:  # Small threshold to ignore dust
                        # Check if this matches our saved position
                        saved_pos = saved_positions.get(symbol, {})
                        
                        if saved_pos and abs(saved_pos.get('size', 0) - base_total) < 0.0001:
                            # Position matches saved state
                            positions[symbol] = saved_pos
                            positions[symbol]['verified'] = True
                        else:
                            # Position doesn't match or is new
                            self.logger.warning(
                                f"Position mismatch for {symbol}: "
                                f"saved={saved_pos.get('size', 0)}, exchange={base_total}"
                            )
                            
                            positions[symbol] = {
                                'size': base_total,
                                'free': base_free,
                                'used': base_used,
                                'entry_price': saved_pos.get('entry_price'),  # Preserve if available
                                'side': 'long',
                                'synchronized': True,
                                'verified': False
                            }
                            
                        seen_symbols.add(symbol)
                        
                except Exception as e:
                    self.logger.error(f"Error processing symbol {symbol}: {e}")
                    
            # Check for positions in saved state that no longer exist
            for symbol, saved_pos in saved_positions.items():
                if symbol not in seen_symbols and saved_pos.get('size', 0) != 0:
                    self.logger.warning(
                        f"Saved position for {symbol} not found on exchange, marking as closed"
                    )
                    # Don't include in returned positions (effectively closing it)
                    
            # Also check for open orders that might affect positions
            try:
                open_orders = self.exchange.fetch_open_orders()
                if open_orders:
                    self.logger.info(f"Found {len(open_orders)} open orders")
                    for order in open_orders:
                        self.logger.info(
                            f"Open order: {order['symbol']} {order['side']} "
                            f"{order['amount']} @ {order['price'] or 'market'}"
                        )
            except Exception as e:
                self.logger.error(f"Failed to fetch open orders: {e}")
                
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to sync positions: {e}")
            # Return saved positions as fallback
            return saved_positions or {}
            
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information including total balance"""
        try:
            balance = self.exchange.fetch_balance()
            
            # Calculate total balance in quote currency (usually USDT)
            total_balance_usdt = balance.get('USDT', {}).get('total', 0)
            
            # Add value of other holdings (simplified - in production you'd get current prices)
            info = {
                'total_balance_usdt': total_balance_usdt,
                'balances': {},
                'timestamp': self.exchange.milliseconds()
            }
            
            # Include non-zero balances
            for currency, bal in balance.items():
                if isinstance(bal, dict) and bal.get('total', 0) > 0.0001:
                    info['balances'][currency] = {
                        'total': bal['total'],
                        'free': bal.get('free', 0),
                        'used': bal.get('used', 0)
                    }
                    
            return info
            
        except Exception as e:
            self.logger.error(f"Failed to get account info: {e}")
            return {}