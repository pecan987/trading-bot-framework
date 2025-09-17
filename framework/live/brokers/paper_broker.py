"""
Paper trading broker wrapper that simulates trading without real money
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd
from collections import defaultdict
import uuid

from .base_broker import (
    BaseBroker, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)


class PaperBroker(BaseBroker):
    """
    Paper trading wrapper that simulates order execution
    Uses real market data but simulated execution
    """
    
    def __init__(
        self,
        data_broker: BaseBroker,
        initial_capital: float = 10000,
        commission_rate: float = 0.001,  # 0.1%
        slippage_rate: float = 0.0005,   # 0.05%
        config: dict = None
    ):
        """
        Initialize paper trading broker
        
        Args:
            data_broker: Real broker to use for market data
            initial_capital: Starting capital
            commission_rate: Commission as percentage
            slippage_rate: Slippage as percentage
            config: Additional configuration
        """
        super().__init__(name=f"paper_{data_broker.name}", config=config or {})
        
        self.data_broker = data_broker
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.logger = logging.getLogger(__name__)
        
        # Paper trading state
        self.cash_balance = initial_capital
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.trades: List[Dict] = []
        self.order_counter = 0
        
        # Track P&L
        self.realized_pnl = 0
        self.total_commission = 0
    
    def connect(self) -> bool:
        """Connect to data broker"""
        success = self.data_broker.connect()
        if success:
            self.is_connected = True
            self.logger.info(
                f"Paper trading connected with ${self.initial_capital:.2f} capital"
            )
        return success
    
    def disconnect(self):
        """Disconnect from data broker"""
        self.data_broker.disconnect()
        self.is_connected = False
        self.logger.info("Paper trading disconnected")
    
    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100
    ) -> pd.DataFrame:
        """Get market data from real broker"""
        return self.data_broker.get_market_data(symbol, timeframe, limit)
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price from real broker"""
        return self.data_broker.get_current_price(symbol)
    
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
        """Simulate order placement"""
        if not self.validate_connection():
            raise ConnectionError("Not connected")
        
        # Generate order ID
        self.order_counter += 1
        order_id = f"PAPER_{self.order_counter}_{uuid.uuid4().hex[:8]}"
        
        # Get current market price
        current_price = self.get_current_price(symbol)
        
        # Create order
        order = Order(
            broker_order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.PENDING,
            created_at=datetime.now()
        )
        
        # Store order
        self.orders[order_id] = order
        
        # Execute immediately for market orders
        if order_type == OrderType.MARKET:
            self._execute_order(order, current_price)
        else:
            order.status = OrderStatus.SUBMITTED
            self.logger.info(
                f"Placed {order_type.value} {side.value} order: "
                f"{quantity} {symbol} @ {price or 'market'}"
            )
        
        return order
    
    def _execute_order(self, order: Order, execution_price: float):
        """Execute an order (simulate fill)"""
        # Apply slippage
        if order.side == OrderSide.BUY:
            # Buy slightly higher
            execution_price *= (1 + self.slippage_rate)
        else:
            # Sell slightly lower
            execution_price *= (1 - self.slippage_rate)
        
        # Calculate commission
        commission = order.quantity * execution_price * self.commission_rate
        
        # Check if we have enough balance for buy orders
        if order.side == OrderSide.BUY:
            required_cash = (order.quantity * execution_price) + commission
            if required_cash > self.cash_balance:
                order.status = OrderStatus.REJECTED
                order.updated_at = datetime.now()
                self.logger.error(
                    f"Order rejected: Insufficient balance. "
                    f"Required: ${required_cash:.2f}, Available: ${self.cash_balance:.2f}"
                )
                return
        
        # Execute the order
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = execution_price
        order.commission = commission
        order.updated_at = datetime.now()
        
        # Update cash and positions
        if order.side == OrderSide.BUY:
            # Deduct cash
            self.cash_balance -= (order.quantity * execution_price + commission)
            
            # Update or create position
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                # Average up
                total_qty = pos.quantity + order.quantity
                total_cost = (pos.quantity * pos.avg_entry_price + 
                            order.quantity * execution_price)
                pos.quantity = total_qty
                pos.avg_entry_price = total_cost / total_qty
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    avg_entry_price=execution_price,
                    current_price=execution_price,
                    unrealized_pnl=0
                )
        
        else:  # SELL
            if order.symbol not in self.positions:
                self.logger.error(f"Cannot sell {order.symbol}: No position")
                order.status = OrderStatus.REJECTED
                return
            
            pos = self.positions[order.symbol]
            if order.quantity > pos.quantity:
                self.logger.error(
                    f"Cannot sell {order.quantity} {order.symbol}: "
                    f"Only {pos.quantity} available"
                )
                order.status = OrderStatus.REJECTED
                return
            
            # Calculate P&L
            pnl = (execution_price - pos.avg_entry_price) * order.quantity
            self.realized_pnl += pnl
            
            # Add cash
            self.cash_balance += (order.quantity * execution_price - commission)
            
            # Update or close position
            pos.quantity -= order.quantity
            if pos.quantity == 0:
                del self.positions[order.symbol]
        
        # Track commission
        self.total_commission += commission
        
        # Record trade
        self.trades.append({
            'timestamp': datetime.now(),
            'symbol': order.symbol,
            'side': order.side.value,
            'quantity': order.quantity,
            'price': execution_price,
            'commission': commission,
            'pnl': pnl if order.side == OrderSide.SELL else None
        })
        
        self.logger.info(
            f"Executed {order.side.value} {order.quantity} {order.symbol} "
            f"@ ${execution_price:.4f} (commission: ${commission:.2f})"
        )
    
    def cancel_order(self, order: Order) -> bool:
        """Cancel an order"""
        if order.broker_order_id in self.orders:
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()
                self.logger.info(f"Cancelled order {order.broker_order_id}")
                return True
        return False
    
    def get_order_status(self, order: Order) -> Order:
        """Get order status"""
        if order.broker_order_id in self.orders:
            stored_order = self.orders[order.broker_order_id]
            
            # Check if limit order should be executed
            if (stored_order.status == OrderStatus.SUBMITTED and 
                stored_order.order_type == OrderType.LIMIT):
                
                current_price = self.get_current_price(stored_order.symbol)
                
                if stored_order.side == OrderSide.BUY:
                    if current_price <= stored_order.price:
                        self._execute_order(stored_order, stored_order.price)
                else:  # SELL
                    if current_price >= stored_order.price:
                        self._execute_order(stored_order, stored_order.price)
            
            return stored_order
        return order
    
    def get_open_orders(self, symbol: str = None) -> List[Order]:
        """Get open orders"""
        open_orders = []
        for order in self.orders.values():
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                if symbol is None or order.symbol == symbol:
                    # Check if should be executed
                    self.get_order_status(order)
                    if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                        open_orders.append(order)
        return open_orders
    
    def get_positions(self, symbol: str = None) -> List[Position]:
        """Get current positions"""
        positions = []
        for sym, pos in self.positions.items():
            if symbol is None or sym == symbol:
                # Update current price and unrealized P&L
                try:
                    current_price = self.get_current_price(sym)
                    pos.current_price = current_price
                    pos.unrealized_pnl = (current_price - pos.avg_entry_price) * pos.quantity
                except:
                    pass  # Keep last known price
                positions.append(pos)
        return positions
    
    def get_account_info(self) -> AccountInfo:
        """Get account information"""
        positions_value = 0
        unrealized_pnl = 0
        
        # Calculate positions value and P&L
        for position in self.get_positions():
            positions_value += position.market_value
            unrealized_pnl += position.unrealized_pnl
        
        total_equity = self.cash_balance + positions_value
        
        return AccountInfo(
            cash_balance=self.cash_balance,
            total_equity=total_equity,
            positions_value=positions_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self.realized_pnl
        )
    
    def get_trade_history(
        self,
        symbol: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get trade history"""
        trades = self.trades.copy()
        
        # Filter by symbol
        if symbol:
            trades = [t for t in trades if t['symbol'] == symbol]
        
        # Filter by date range
        if start_date:
            trades = [t for t in trades if t['timestamp'] >= start_date]
        if end_date:
            trades = [t for t in trades if t['timestamp'] <= end_date]
        
        # Limit results
        return trades[-limit:]
    
    def get_min_order_size(self, symbol: str) -> float:
        """Get minimum order size from data broker"""
        return self.data_broker.get_min_order_size(symbol)
    
    def get_tick_size(self, symbol: str) -> float:
        """Get tick size from data broker"""
        return self.data_broker.get_tick_size(symbol)
    
    def get_statistics(self) -> Dict:
        """Get paper trading statistics"""
        account = self.get_account_info()
        
        return {
            'initial_capital': self.initial_capital,
            'current_equity': account.total_equity,
            'cash_balance': account.cash_balance,
            'positions_value': account.positions_value,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': account.unrealized_pnl,
            'total_pnl': self.realized_pnl + account.unrealized_pnl,
            'total_commission': self.total_commission,
            'total_trades': len(self.trades),
            'open_positions': len(self.positions),
            'return_pct': ((account.total_equity / self.initial_capital) - 1) * 100
        }