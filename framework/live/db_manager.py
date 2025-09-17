"""
Database manager with connection pooling for PostgreSQL
"""
import os
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from contextlib import contextmanager
from decimal import Decimal

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json


class DatabaseManager:
    """Manages PostgreSQL connections with pooling"""
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        database: str = None,
        user: str = None,
        password: str = None,
        min_connections: int = 2,
        max_connections: int = 10
    ):
        """Initialize database manager with connection pool"""
        self.logger = logging.getLogger(__name__)
        
        # Get config from environment if not provided
        self.host = host or os.getenv('DB_HOST', 'localhost')
        self.port = port or int(os.getenv('DB_PORT', 5432))
        self.database = database or os.getenv('DB_NAME', 'trading')
        self.user = user or os.getenv('DB_USER', 'trading_user')
        self.password = password or os.getenv('DB_PASSWORD', 'trading_password')
        
        # Create connection pool
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                min_connections,
                max_connections,
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self.logger.info(f"Database connection pool created: {self.host}:{self.port}/{self.database}")
        except Exception as e:
            self.logger.error(f"Failed to create connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get connection from pool with context manager"""
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)
    
    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        """Get cursor with context manager"""
        with self.get_connection() as conn:
            cursor_factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
            finally:
                cursor.close()
    
    # ==================== TRADES ====================
    
    def save_trade(
        self,
        broker: str,
        strategy: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float = 0,
        pnl: float = None,
        broker_trade_id: str = None,
        metadata: dict = None
    ) -> int:
        """Save trade to database"""
        query = """
            INSERT INTO trading.trades 
            (broker, strategy, symbol, side, quantity, price, commission, pnl, broker_trade_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker, strategy, symbol, side, 
                Decimal(str(quantity)), Decimal(str(price)),
                Decimal(str(commission)) if commission else 0,
                Decimal(str(pnl)) if pnl else None,
                broker_trade_id,
                Json(metadata) if metadata else None
            ))
            return cursor.fetchone()['id']
    
    def get_trades(
        self, 
        broker: str = None,
        symbol: str = None,
        strategy: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get trades from database"""
        query = "SELECT * FROM trading.trades WHERE 1=1"
        params = []
        
        if broker:
            query += " AND broker = %s"
            params.append(broker)
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)
        if strategy:
            query += " AND strategy = %s"
            params.append(strategy)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()
    
    # ==================== POSITIONS ====================
    
    def upsert_position(
        self,
        broker: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        current_price: float = None,
        unrealized_pnl: float = None
    ) -> int:
        """Insert or update position"""
        query = """
            INSERT INTO trading.positions 
            (broker, symbol, quantity, avg_entry_price, current_price, unrealized_pnl)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (broker, symbol, is_open) WHERE is_open = true
            DO UPDATE SET
                quantity = %s,
                avg_entry_price = %s,
                current_price = %s,
                unrealized_pnl = %s,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker, symbol,
                Decimal(str(quantity)), Decimal(str(avg_entry_price)),
                Decimal(str(current_price)) if current_price else None,
                Decimal(str(unrealized_pnl)) if unrealized_pnl else None,
                # Update values
                Decimal(str(quantity)), Decimal(str(avg_entry_price)),
                Decimal(str(current_price)) if current_price else None,
                Decimal(str(unrealized_pnl)) if unrealized_pnl else None
            ))
            return cursor.fetchone()['id']
    
    def close_position(self, broker: str, symbol: str, realized_pnl: float = None):
        """Close an open position"""
        query = """
            UPDATE trading.positions 
            SET is_open = false, 
                realized_pnl = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE broker = %s AND symbol = %s AND is_open = true
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                Decimal(str(realized_pnl)) if realized_pnl else None,
                broker, symbol
            ))
    
    def get_open_positions(self, broker: str = None) -> List[Dict]:
        """Get all open positions"""
        query = "SELECT * FROM trading.positions WHERE is_open = true"
        params = []
        
        if broker:
            query += " AND broker = %s"
            params.append(broker)
        
        with self.get_cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
    
    # ==================== ORDERS ====================
    
    def save_order(
        self,
        broker: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        status: str,
        price: float = None,
        broker_order_id: str = None
    ) -> int:
        """Save order to database"""
        query = """
            INSERT INTO trading.orders 
            (broker, symbol, side, order_type, quantity, price, status, broker_order_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker, symbol, side, order_type,
                Decimal(str(quantity)),
                Decimal(str(price)) if price else None,
                status, broker_order_id
            ))
            return cursor.fetchone()['id']
    
    def update_order(
        self,
        order_id: int,
        status: str = None,
        filled_quantity: float = None,
        avg_fill_price: float = None,
        commission: float = None
    ):
        """Update order status"""
        updates = []
        params = []
        
        if status:
            updates.append("status = %s")
            params.append(status)
        if filled_quantity is not None:
            updates.append("filled_quantity = %s")
            params.append(Decimal(str(filled_quantity)))
        if avg_fill_price is not None:
            updates.append("avg_fill_price = %s")
            params.append(Decimal(str(avg_fill_price)))
        if commission is not None:
            updates.append("commission = %s")
            params.append(Decimal(str(commission)))
        
        if not updates:
            return
        
        query = f"""
            UPDATE trading.orders 
            SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        params.append(order_id)
        
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
    
    # ==================== PORTFOLIO ====================
    
    def save_portfolio_snapshot(
        self,
        broker: str,
        total_value: float,
        cash_balance: float,
        positions_value: float,
        daily_pnl: float = None,
        total_pnl: float = None,
        metadata: dict = None
    ):
        """Save portfolio snapshot"""
        query = """
            INSERT INTO trading.portfolio_snapshots 
            (broker, total_value, cash_balance, positions_value, daily_pnl, total_pnl, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker,
                Decimal(str(total_value)),
                Decimal(str(cash_balance)),
                Decimal(str(positions_value)),
                Decimal(str(daily_pnl)) if daily_pnl else None,
                Decimal(str(total_pnl)) if total_pnl else None,
                Json(metadata) if metadata else None
            ))
    
    # ==================== BROKER STATUS ====================
    
    def update_broker_status(
        self,
        broker: str,
        is_active: bool,
        is_paper_trading: bool = True,
        connection_status: str = None,
        error_message: str = None
    ):
        """Update broker status and heartbeat"""
        query = """
            INSERT INTO trading.broker_status 
            (broker, is_active, is_paper_trading, last_heartbeat, connection_status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (broker)
            DO UPDATE SET
                is_active = %s,
                is_paper_trading = %s,
                last_heartbeat = %s,
                connection_status = %s,
                error_message = %s,
                updated_at = CURRENT_TIMESTAMP
        """
        
        now = datetime.now()
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker, is_active, is_paper_trading, now, connection_status, error_message,
                # Update values
                is_active, is_paper_trading, now, connection_status, error_message
            ))
    
    # ==================== STRATEGY STATE ====================
    
    def save_strategy_state(
        self,
        broker: str,
        strategy: str,
        symbol: str,
        state_key: str,
        state_value: Any
    ):
        """Save strategy state for persistence"""
        query = """
            INSERT INTO trading.strategy_state 
            (broker, strategy, symbol, state_key, state_value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (broker, strategy, symbol, state_key)
            DO UPDATE SET
                state_value = %s,
                updated_at = CURRENT_TIMESTAMP
        """
        
        with self.get_cursor() as cursor:
            cursor.execute(query, (
                broker, strategy, symbol, state_key,
                Json(state_value),
                Json(state_value)  # For update
            ))
    
    def get_strategy_state(
        self,
        broker: str,
        strategy: str,
        symbol: str,
        state_key: str = None
    ) -> Optional[Any]:
        """Get strategy state"""
        if state_key:
            query = """
                SELECT state_value FROM trading.strategy_state
                WHERE broker = %s AND strategy = %s AND symbol = %s AND state_key = %s
            """
            params = (broker, strategy, symbol, state_key)
        else:
            query = """
                SELECT state_key, state_value FROM trading.strategy_state
                WHERE broker = %s AND strategy = %s AND symbol = %s
            """
            params = (broker, strategy, symbol)
        
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            result = cursor.fetchone() if state_key else cursor.fetchall()
            return result['state_value'] if result and state_key else result
    
    def close(self):
        """Close all connections in the pool"""
        if hasattr(self, 'pool'):
            self.pool.closeall()
            self.logger.info("Database connection pool closed")