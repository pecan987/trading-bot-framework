"""
CCXT broker implementation for cryptocurrency exchanges
"""
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd

import ccxt

from .base_broker import (
    BaseBroker, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)


class CCXTBroker(BaseBroker):
    """CCXT implementation for cryptocurrency trading"""
    
    TIMEFRAME_MAP = {
        '1m': '1m',
        '5m': '5m', 
        '15m': '15m',
        '30m': '30m',
        '1h': '1h',
        '4h': '4h',
        '1d': '1d',
        '1w': '1w'
    }
    
    def __init__(
        self,
        exchange_name: str = None,
        api_key: str = None,
        api_secret: str = None,
        testnet: bool = True,
        config: dict = None
    ):
        """
        Initialize CCXT broker
        
        Args:
            exchange_name: Exchange name (binance, kraken, etc.)
            api_key: API key
            api_secret: API secret
            testnet: Use testnet/sandbox mode
            config: Additional configuration
        """
        # Get from environment if not provided
        exchange_name = exchange_name or os.getenv('CCXT_EXCHANGE', 'binance')
        api_key = api_key or os.getenv('CCXT_API_KEY')
        api_secret = api_secret or os.getenv('CCXT_API_SECRET')
        
        if testnet is None:
            testnet = os.getenv('CCXT_TESTNET', 'true').lower() == 'true'
        
        super().__init__(name=f"ccxt_{exchange_name}", config=config or {})
        
        self.exchange_name = exchange_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.logger = logging.getLogger(__name__)
        
        self.exchange = None
        self._positions_cache = {}
    
    def connect(self) -> bool:
        """Connect to exchange"""
        try:
            self.logger.info(f"Creating {self.exchange_name} exchange instance...")
            # Create exchange instance
            exchange_class = getattr(ccxt, self.exchange_name)
            
            # Basic configuration
            exchange_config = {
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'enableRateLimit': True,
                'timeout': 30000,  # 30 second timeout
                'options': {
                    'defaultType': 'spot',  # or 'future', 'margin'
                }
            }
            
            # Add testnet configuration if needed
            if self.testnet:
                if self.exchange_name == 'binance':
                    exchange_config['urls'] = {
                        'api': {
                            'public': 'https://testnet.binance.vision/api',
                            'private': 'https://testnet.binance.vision/api',
                        }
                    }
                elif self.exchange_name == 'bybit':
                    exchange_config['urls'] = {
                        'api': {
                            'public': 'https://api-testnet.bybit.com',
                            'private': 'https://api-testnet.bybit.com',
                        }
                    }
            
            self.logger.info(f"Initializing exchange with config...")
            self.exchange = exchange_class(exchange_config)
            
            # Test connection by fetching markets
            self.logger.info(f"Loading markets to test connection...")
            markets = self.exchange.load_markets()
            self.logger.info(f"Loaded {len(markets)} markets")
            
            self.is_connected = True
            self.logger.info(
                f"Successfully connected to {self.exchange_name} "
                f"({'testnet' if self.testnet else 'live'})"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to {self.exchange_name}: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from exchange"""
        self.is_connected = False
        self.exchange = None
        self.logger.info(f"Disconnected from {self.exchange_name}")
    
    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> pd.DataFrame:
        """Fetch OHLCV data"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            # Convert timeframe if needed
            ccxt_timeframe = self.TIMEFRAME_MAP.get(timeframe, timeframe)
            
            # Fetch OHLCV data
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=ccxt_timeframe,
                limit=limit
            )
            
            # Convert to DataFrame with standardized column names
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
            )
            
            # Convert timestamp to datetime and set as index
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
            
        except Exception as e:
            self.logger.error(f"Failed to fetch market data for {symbol}: {e}")
            raise
    
    def get_current_price(self, symbol: str) -> float:
        """Get current market price"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            self.logger.error(f"Failed to fetch price for {symbol}: {e}")
            raise
    
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Order:
        """Place an order"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            # Map order type to CCXT
            ccxt_order_type = order_type.value
            
            # Create order parameters
            params = {}
            if stop_price:
                params['stopPrice'] = stop_price
            
            # Place order
            if order_type == OrderType.MARKET:
                result = self.exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=side.value,
                    amount=quantity,
                    params=params
                )
            elif order_type == OrderType.LIMIT:
                if price is None:
                    raise ValueError("Limit order requires price")
                result = self.exchange.create_order(
                    symbol=symbol,
                    type='limit',
                    side=side.value,
                    amount=quantity,
                    price=price,
                    params=params
                )
            else:
                raise NotImplementedError(f"Order type {order_type} not implemented")
            
            # Create Order object
            order = Order(
                broker_order_id=str(result['id']),
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=self._map_order_status(result['status']),
                filled_quantity=result.get('filled', 0),
                avg_fill_price=result.get('average'),
                created_at=datetime.now()
            )
            
            self.logger.info(
                f"Placed {order_type.value} {side.value} order: "
                f"{quantity} {symbol} @ {price or 'market'}"
            )
            
            return order
            
        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            raise
    
    def cancel_order(self, order: Order) -> bool:
        """Cancel an order"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            result = self.exchange.cancel_order(
                order.broker_order_id,
                order.symbol
            )
            return result is not None
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order.broker_order_id}: {e}")
            return False
    
    def get_order_status(self, order: Order) -> Order:
        """Get updated order status"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            result = self.exchange.fetch_order(
                order.broker_order_id,
                order.symbol
            )
            
            # Update order fields
            order.status = self._map_order_status(result['status'])
            order.filled_quantity = result.get('filled', 0)
            order.avg_fill_price = result.get('average')
            order.updated_at = datetime.now()
            
            return order
            
        except Exception as e:
            self.logger.error(f"Failed to get order status: {e}")
            raise
    
    def get_open_orders(self, symbol: str = None) -> List[Order]:
        """Get open orders"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            
            return [
                Order(
                    broker_order_id=str(o['id']),
                    symbol=o['symbol'],
                    side=OrderSide.BUY if o['side'] == 'buy' else OrderSide.SELL,
                    order_type=self._map_order_type(o['type']),
                    quantity=o['amount'],
                    price=o.get('price'),
                    status=self._map_order_status(o['status']),
                    filled_quantity=o.get('filled', 0),
                    avg_fill_price=o.get('average')
                )
                for o in orders
            ]
            
        except Exception as e:
            self.logger.error(f"Failed to fetch open orders: {e}")
            return []
    
    def get_positions(self, symbol: str = None) -> List[Position]:
        """Get current positions"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            # For spot trading, positions are based on balances
            balances = self.exchange.fetch_balance()
            positions = []
            
            # Convert non-zero balances to positions
            for asset, balance in balances['total'].items():
                if balance > 0 and asset != 'USDT':  # Skip stablecoins
                    # Try to get current price
                    try:
                        pair = f"{asset}/USDT"
                        if symbol and pair != symbol:
                            continue
                            
                        current_price = self.get_current_price(pair)
                        
                        # Get average entry price from cache or estimate
                        avg_price = self._positions_cache.get(pair, current_price)
                        
                        position = Position(
                            symbol=pair,
                            quantity=balance,
                            avg_entry_price=avg_price,
                            current_price=current_price,
                            unrealized_pnl=(current_price - avg_price) * balance
                        )
                        positions.append(position)
                    except:
                        pass  # Skip if can't get price
            
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to fetch positions: {e}")
            return []
    
    def get_account_info(self) -> AccountInfo:
        """Get account information"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            balance = self.exchange.fetch_balance()
            
            # Calculate total equity
            total_equity = 0
            cash_balance = balance['USDT']['total'] if 'USDT' in balance else 0
            
            # Add up all assets in USDT value
            for asset, amount in balance['total'].items():
                if amount > 0:
                    if asset == 'USDT':
                        total_equity += amount
                    else:
                        try:
                            price = self.get_current_price(f"{asset}/USDT")
                            total_equity += amount * price
                        except:
                            pass  # Skip if can't convert
            
            positions_value = total_equity - cash_balance
            
            return AccountInfo(
                cash_balance=cash_balance,
                total_equity=total_equity,
                positions_value=positions_value
            )
            
        except Exception as e:
            self.logger.error(f"Failed to fetch account info: {e}")
            raise
    
    def get_trade_history(
        self,
        symbol: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get trade history"""
        if not self.validate_connection():
            raise ConnectionError("Not connected to exchange")
        
        try:
            # Calculate since parameter
            since = None
            if start_date:
                since = int(start_date.timestamp() * 1000)
            
            trades = self.exchange.fetch_my_trades(
                symbol=symbol,
                since=since,
                limit=limit
            )
            
            # Filter by end date if provided
            if end_date:
                end_timestamp = end_date.timestamp() * 1000
                trades = [t for t in trades if t['timestamp'] <= end_timestamp]
            
            # Update position cache with trade data
            for trade in trades:
                sym = trade['symbol']
                if sym not in self._positions_cache:
                    self._positions_cache[sym] = trade['price']
            
            return trades
            
        except Exception as e:
            self.logger.error(f"Failed to fetch trade history: {e}")
            return []
    
    def get_min_order_size(self, symbol: str) -> float:
        """Get minimum order size"""
        try:
            market = self.exchange.market(symbol)
            return market.get('limits', {}).get('amount', {}).get('min', 0.001)
        except:
            return 0.001
    
    def get_tick_size(self, symbol: str) -> float:
        """Get price tick size"""
        try:
            market = self.exchange.market(symbol)
            return market.get('limits', {}).get('price', {}).get('min', 0.01)
        except:
            return 0.01
    
    # Helper methods
    
    def _map_order_status(self, ccxt_status: str) -> OrderStatus:
        """Map CCXT status to OrderStatus"""
        status_map = {
            'open': OrderStatus.SUBMITTED,
            'closed': OrderStatus.FILLED,
            'canceled': OrderStatus.CANCELLED,
            'cancelled': OrderStatus.CANCELLED,
            'expired': OrderStatus.EXPIRED,
            'rejected': OrderStatus.REJECTED,
            'partially_filled': OrderStatus.PARTIALLY_FILLED
        }
        return status_map.get(ccxt_status.lower(), OrderStatus.PENDING)
    
    def _map_order_type(self, ccxt_type: str) -> OrderType:
        """Map CCXT order type to OrderType"""
        type_map = {
            'market': OrderType.MARKET,
            'limit': OrderType.LIMIT,
            'stop': OrderType.STOP,
            'stop_limit': OrderType.STOP_LIMIT
        }
        return type_map.get(ccxt_type.lower(), OrderType.MARKET)