"""
PostgreSQL-based state store for trading bot state persistence
"""
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import threading
import os
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """Database configuration"""
    host: str = 'postgres'
    port: int = 5432
    database: str = 'trading_bot'
    user: str = 'trading_user'
    password: str = 'trading_password'
    schema: str = 'trading'
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        """Create config from environment variables"""
        return cls(
            host=os.getenv('DB_HOST', 'postgres'),
            port=int(os.getenv('DB_PORT', '5432')),
            database=os.getenv('DB_NAME', 'trading_bot'),
            user=os.getenv('DB_USER', 'trading_user'),
            password=os.getenv('DB_PASSWORD', 'trading_password'),
            schema=os.getenv('DB_SCHEMA', 'trading')
        )


class PostgreSQLStateStore:
    """PostgreSQL-based state store for trading bot state persistence"""
    
    def __init__(self, config: Optional[DatabaseConfig] = None, instance_id: str = None, exchange: str = 'CCXT'):
        self.config = config or DatabaseConfig.from_env()
        self.instance_id = instance_id or f"trader_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.exchange = exchange
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        
        # Connection pool
        self._connection = None
        
    def _get_connection(self):
        """Get database connection with retry logic"""
        if self._connection is None or self._connection.closed:
            try:
                self.logger.debug(
                    "Connecting to PostgreSQL database...",
                    extra={
                        'host': self.config.host,
                        'port': self.config.port,
                        'database': self.config.database,
                        'user': self.config.user,
                        'instance_id': self.instance_id,
                        'exchange': self.exchange
                    }
                )
                self._connection = psycopg2.connect(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.user,
                    password=self.config.password
                )
                self._connection.autocommit = False
                self.logger.debug(
                    "PostgreSQL connection established",
                    extra={
                        'connection_status': 'connected',
                        'instance_id': self.instance_id,
                        'exchange': self.exchange
                    }
                )
            except Exception as e:
                self.logger.error(
                    "Failed to connect to PostgreSQL",
                    extra={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'host': self.config.host,
                        'port': self.config.port,
                        'database': self.config.database,
                        'user': self.config.user,
                        'instance_id': self.instance_id,
                        'exchange': self.exchange
                    }
                )
                raise
        return self._connection
    
    def _execute_query(self, query: str, params: tuple = None, fetch: bool = False) -> Optional[Any]:
        """Execute a query with error handling"""
        with self._lock:
            try:
                conn = self._get_connection()
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if fetch:
                        return cursor.fetchall()
                    conn.commit()
                    return cursor.rowcount
            except Exception as e:
                self.logger.error(f"Database query failed: {e}")
                if self._connection:
                    self._connection.rollback()
                raise
    
    def save_positions(self, positions: Dict[str, Any]) -> None:
        """Save positions to database"""
        try:
            self.logger.debug(
                "Saving positions to PostgreSQL",
                extra={
                    'positions_count': len(positions),
                    'instance_id': self.instance_id,
                    'exchange': self.exchange
                }
            )
            
            # Save each position
            for symbol, position_data in positions.items():
                query = """
                    INSERT INTO trading.trading_state (instance_id, exchange, state_type, state_key, state_data)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (instance_id, exchange, state_type, state_key)
                    DO UPDATE SET state_data = EXCLUDED.state_data, updated_at = NOW()
                """
                params = (
                    self.instance_id,
                    self.exchange,
                    'positions',
                    symbol,
                    json.dumps(position_data)
                )
                self._execute_query(query, params)
                
            self.logger.debug(
                "Positions saved to PostgreSQL successfully",
                extra={
                    'positions_count': len(positions),
                    'instance_id': self.instance_id,
                    'exchange': self.exchange
                }
            )
                
        except Exception as e:
            self.logger.error(
                "Failed to save positions",
                extra={
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'positions_count': len(positions),
                    'instance_id': self.instance_id,
                    'exchange': self.exchange
                }
            )
    
    def load_positions(self) -> Dict[str, Any]:
        """Load positions from database"""
        try:
            query = """
                SELECT state_key, state_data 
                FROM trading.trading_state 
                WHERE instance_id = %s AND exchange = %s AND state_type = %s
            """
            params = (self.instance_id, self.exchange, 'positions')
            
            rows = self._execute_query(query, params, fetch=True)
            
            positions = {}
            for row in rows:
                positions[row['state_key']] = json.loads(row['state_data'])
            
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to load positions: {e}")
            return {}
    
    def save_orders(self, orders: Dict[str, Any]) -> None:
        """Save orders to database"""
        try:
            # Save each order
            for order_id, order_data in orders.items():
                query = """
                    INSERT INTO trading.trading_state (instance_id, exchange, state_type, state_key, state_data)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (instance_id, exchange, state_type, state_key)
                    DO UPDATE SET state_data = EXCLUDED.state_data, updated_at = NOW()
                """
                params = (
                    self.instance_id,
                    self.exchange,
                    'orders',
                    order_id,
                    json.dumps(order_data)
                )
                self._execute_query(query, params)
                
        except Exception as e:
            self.logger.error(f"Failed to save orders: {e}")
    
    def load_orders(self) -> Dict[str, Any]:
        """Load orders from database"""
        try:
            query = """
                SELECT state_key, state_data 
                FROM trading.trading_state 
                WHERE instance_id = %s AND exchange = %s AND state_type = %s
            """
            params = (self.instance_id, self.exchange, 'orders')
            
            rows = self._execute_query(query, params, fetch=True)
            
            orders = {}
            for row in rows:
                orders[row['state_key']] = json.loads(row['state_data'])
            
            return orders
            
        except Exception as e:
            self.logger.error(f"Failed to load orders: {e}")
            return {}
    
    def save_daily_pnl(self, date: str, pnl: float) -> None:
        """Save daily P&L to database"""
        try:
            query = """
                INSERT INTO trading.trading_state (instance_id, exchange, state_type, state_key, state_data)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (instance_id, exchange, state_type, state_key)
                DO UPDATE SET state_data = EXCLUDED.state_data, updated_at = NOW()
            """
            params = (
                self.instance_id,
                self.exchange,
                'daily_pnl',
                date,
                json.dumps({'pnl': pnl})
            )
            self._execute_query(query, params)
            
        except Exception as e:
            self.logger.error(f"Failed to save daily P&L: {e}")
    
    def load_daily_pnl(self, date: str) -> float:
        """Load daily P&L from database"""
        try:
            query = """
                SELECT state_data 
                FROM trading.trading_state 
                WHERE instance_id = %s AND exchange = %s AND state_type = %s AND state_key = %s
            """
            params = (self.instance_id, self.exchange, 'daily_pnl', date)
            
            rows = self._execute_query(query, params, fetch=True)
            
            if rows:
                data = json.loads(rows[0]['state_data'])
                return data.get('pnl', 0.0)
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"Failed to load daily P&L: {e}")
            return 0.0
    
    def save_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        """Save checkpoint to database"""
        try:
            query = """
                INSERT INTO trading.trading_state (instance_id, exchange, state_type, state_key, state_data)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (instance_id, exchange, state_type, state_key)
                DO UPDATE SET state_data = EXCLUDED.state_data, updated_at = NOW()
            """
            params = (
                self.instance_id,
                self.exchange,
                'checkpoint',
                'latest',
                json.dumps(checkpoint)
            )
            self._execute_query(query, params)
            
        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
    
    def load_checkpoint(self) -> Dict[str, Any]:
        """Load checkpoint from database"""
        try:
            query = """
                SELECT state_data 
                FROM trading.trading_state 
                WHERE instance_id = %s AND exchange = %s AND state_type = %s AND state_key = %s
            """
            params = (self.instance_id, self.exchange, 'checkpoint', 'latest')
            
            rows = self._execute_query(query, params, fetch=True)
            
            if rows:
                return json.loads(rows[0]['state_data'])
            
            return {}
            
        except Exception as e:
            self.logger.error(f"Failed to load checkpoint: {e}")
            return {}
    
    def acquire_lock(self, lock_id: str) -> bool:
        """Acquire a trading lock"""
        try:
            # Clean up expired locks first
            self._cleanup_expired_locks()
            
            # Try to acquire lock
            query = """
                INSERT INTO trading.trading_locks (lock_id, instance_id, exchange, expires_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (lock_id) DO NOTHING
            """
            params = (
                lock_id,
                self.instance_id,
                self.exchange,
                datetime.now() + timedelta(hours=1)
            )
            
            rowcount = self._execute_query(query, params)
            
            if rowcount > 0:
                self.logger.info(f"Acquired lock: {lock_id}")
                return True
            else:
                self.logger.warning(f"Failed to acquire lock: {lock_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to acquire lock: {e}")
            return False
    
    def release_lock(self, lock_id: str) -> bool:
        """Release a trading lock"""
        try:
            query = """
                DELETE FROM trading.trading_locks 
                WHERE lock_id = %s AND instance_id = %s
            """
            params = (lock_id, self.instance_id)
            
            rowcount = self._execute_query(query, params)
            
            if rowcount > 0:
                self.logger.info(f"Released lock: {lock_id}")
                return True
            else:
                self.logger.warning(f"Lock not found or not owned: {lock_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to release lock: {e}")
            return False
    
    def _cleanup_expired_locks(self) -> None:
        """Clean up expired locks"""
        try:
            query = """
                DELETE FROM trading.trading_locks 
                WHERE expires_at < NOW()
            """
            rowcount = self._execute_query(query)
            
            if rowcount > 0:
                self.logger.debug(f"Cleaned up {rowcount} expired locks")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired locks: {e}")
    
    def close(self) -> None:
        """Close database connection"""
        with self._lock:
            if self._connection and not self._connection.closed:
                self._connection.close()
                self._connection = None