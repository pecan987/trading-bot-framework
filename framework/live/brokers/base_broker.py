"""
Abstract base broker interface for all trading brokers
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
from dataclasses import dataclass
from enum import Enum


class OrderType(Enum):
    """Order types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order sides"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Order data structure"""
    broker_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0
    avg_fill_price: Optional[float] = None
    commission: float = 0
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class Position:
    """Position data structure"""
    symbol: str
    quantity: float  # Positive for long, negative for short
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0
    
    @property
    def market_value(self) -> float:
        return abs(self.quantity) * self.current_price


@dataclass
class AccountInfo:
    """Account information"""
    cash_balance: float
    total_equity: float
    margin_used: float = 0
    margin_available: float = 0
    positions_value: float = 0
    unrealized_pnl: float = 0
    realized_pnl: float = 0


class BaseBroker(ABC):
    """Abstract base class for all broker implementations"""
    
    def __init__(self, name: str, config: dict = None):
        """Initialize broker"""
        self.name = name
        self.config = config or {}
        self.is_connected = False
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to broker
        Returns: True if connection successful
        """
        pass
    
    @abstractmethod
    def disconnect(self):
        """Disconnect from broker"""
        pass
    
    @abstractmethod
    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Fetch OHLCV market data
        
        Args:
            symbol: Trading symbol (e.g., 'BTC/USDT', 'AAPL')
            timeframe: Candle timeframe (e.g., '1m', '5m', '1h', '1d')
            limit: Number of candles to fetch
            
        Returns:
            DataFrame with columns: ['open', 'high', 'low', 'close', 'volume']
            Index should be DatetimeIndex
        """
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for symbol
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current price
        """
        pass
    
    @abstractmethod
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
        """
        Place an order
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            order_type: Market, limit, stop, etc.
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)
            **kwargs: Additional broker-specific parameters
            
        Returns:
            Order object with broker_order_id
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order: Order) -> bool:
        """
        Cancel an open order
        
        Args:
            order: Order to cancel
            
        Returns:
            True if cancellation successful
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order: Order) -> Order:
        """
        Get updated order status
        
        Args:
            order: Order to check
            
        Returns:
            Updated Order object
        """
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: str = None) -> List[Order]:
        """
        Get all open orders
        
        Args:
            symbol: Filter by symbol (optional)
            
        Returns:
            List of open Order objects
        """
        pass
    
    @abstractmethod
    def get_positions(self, symbol: str = None) -> List[Position]:
        """
        Get current positions
        
        Args:
            symbol: Filter by symbol (optional)
            
        Returns:
            List of Position objects
        """
        pass
    
    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """
        Get account information
        
        Returns:
            AccountInfo object with balances and P&L
        """
        pass
    
    @abstractmethod
    def get_trade_history(
        self,
        symbol: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get historical trades
        
        Args:
            symbol: Filter by symbol (optional)
            start_date: Start date filter (optional)
            end_date: End date filter (optional)
            limit: Maximum number of trades
            
        Returns:
            List of trade dictionaries
        """
        pass
    
    def validate_connection(self) -> bool:
        """Check if broker is connected"""
        return self.is_connected
    
    def get_min_order_size(self, symbol: str) -> float:
        """
        Get minimum order size for symbol
        Override in subclasses if needed
        """
        return 0.001
    
    def get_tick_size(self, symbol: str) -> float:
        """
        Get minimum price increment for symbol
        Override in subclasses if needed
        """
        return 0.01
    
    def round_price(self, price: float, symbol: str) -> float:
        """Round price to valid tick size"""
        tick_size = self.get_tick_size(symbol)
        return round(price / tick_size) * tick_size
    
    def round_quantity(self, quantity: float, symbol: str) -> float:
        """Round quantity to valid lot size"""
        min_size = self.get_min_order_size(symbol)
        return round(quantity / min_size) * min_size