"""
Async database logger for trading activities
Logs trades, positions, and balance snapshots to PostgreSQL without blocking
"""
import asyncio
import asyncpg
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, Union
import json
import logging
import os
from contextlib import asynccontextmanager


class AsyncDatabaseLogger:
    """Async database logger for trading activities"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.pool = None
        self._connection_string = None
        self._queue = asyncio.Queue(maxsize=1000)  # Buffer for async logging
        self._worker_task = None
        self._shutdown = False
        
    async def initialize(self):
        """Initialize database connection pool"""
        try:
            self._connection_string = (
                f"postgresql://{os.getenv('DB_USER', 'trading_user')}:"
                f"{os.getenv('DB_PASSWORD', 'trading_password')}@"
                f"{os.getenv('DB_HOST', 'postgres')}:"
                f"{os.getenv('DB_PORT', '5432')}/"
                f"{os.getenv('DB_NAME', 'trading')}"
            )
            
            self.pool = await asyncpg.create_pool(
                self._connection_string,
                min_size=2,
                max_size=10,
                command_timeout=5.0
            )
            
            # Start background worker
            self._worker_task = asyncio.create_task(self._background_worker())
            
            self.logger.info("Async database logger initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize async database logger: {e}")
            return False
    
    async def _background_worker(self):
        """Background worker to process database writes"""
        while not self._shutdown:
            try:
                # Wait for items in queue with timeout
                try:
                    operation = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process the database operation
                await self._execute_operation(operation)
                self._queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Background worker error: {e}")
                await asyncio.sleep(0.1)
    
    async def _execute_operation(self, operation: Dict[str, Any]):
        """Execute a database operation"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                op_type = operation['type']
                data = operation['data']
                
                if op_type == 'trade':
                    await self._insert_trade(conn, **data)
                elif op_type == 'position':
                    await self._update_position(conn, **data)
                elif op_type == 'balance':
                    await self._insert_balance(conn, **data)
                    
        except Exception as e:
            self.logger.error(f"Database operation failed: {e}")
    
    async def _insert_trade(self, conn, **kwargs):
        """Insert trade record"""
        # Map side to enum value
        trade_side = kwargs['side'].lower()
        if trade_side not in ['buy', 'sell', 'long', 'short']:
            trade_side = 'buy' if kwargs['side'].lower() in ['buy', 'long'] else 'sell'
        
        # Map status to enum value  
        trade_status = kwargs['status'].lower()
        if trade_status not in ['pending', 'filled', 'cancelled', 'rejected', 'expired']:
            trade_status = 'filled' if kwargs['status'].lower() in ['filled', 'closed', 'complete'] else 'pending'
        
        query = """
            INSERT INTO trades (
                trade_id, symbol, strategy, side, quantity, price,
                fee, fee_currency, status, order_type, stop_loss, take_profit,
                executed_at, metadata
            ) VALUES (
                $1, $2, $3, $4::trade_side, $5, $6,
                $7, $8, $9::trade_status, $10, $11, $12,
                $13, $14
            )
            ON CONFLICT (trade_id) DO UPDATE SET
                status = EXCLUDED.status,
                executed_at = EXCLUDED.executed_at,
                updated_at = CURRENT_TIMESTAMP
        """
        
        await conn.execute(query,
            kwargs['trade_id'],
            kwargs['symbol'],
            kwargs.get('strategy'),
            trade_side,
            float(kwargs['quantity']),
            float(kwargs['price']),
            float(kwargs.get('fee', 0)),
            kwargs.get('fee_currency'),
            trade_status,
            kwargs.get('order_type', 'market'),
            float(kwargs['stop_loss']) if kwargs.get('stop_loss') else None,
            float(kwargs['take_profit']) if kwargs.get('take_profit') else None,
            kwargs.get('executed_at') or datetime.now(),
            json.dumps(kwargs.get('metadata', {}))
        )
    
    async def _update_position(self, conn, **kwargs):
        """Update position record"""
        # Determine if this is opening or closing a position
        is_closing = kwargs['quantity'] == 0
        
        if is_closing:
            # For closing positions, update existing open position
            self.logger.info(f"DB: Closing position for {kwargs['symbol']}, exit_price={kwargs.get('exit_price')}")
            # Closing position - update status, exit_price, and realized_pnl
            query = """
                UPDATE positions 
                SET status = 'closed'::position_status,
                    exit_price = $2,
                    realized_pnl = CASE 
                        WHEN side = 'long' THEN ($2 - entry_price) * quantity
                        WHEN side = 'short' THEN (entry_price - $2) * quantity
                        ELSE 0
                    END,
                    closed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = $1 AND status = 'open'::position_status
            """
            # Get exit_price with better error handling
            exit_price = kwargs.get('exit_price')
            if exit_price is not None:
                try:
                    exit_price = float(exit_price)
                except (ValueError, TypeError):
                    self.logger.error(f"Invalid exit_price value: {exit_price}")
                    exit_price = None
            
            await conn.execute(query, 
                kwargs['symbol'],
                exit_price
            )
            return
        
        # For opening positions, create new position record
        position_id = kwargs.get('position_id') or f"{kwargs['symbol']}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        status = 'open'
        
        # Map side to enum
        side = kwargs.get('side', 'long').lower()
        if side not in ['buy', 'sell', 'long', 'short']:
            side = 'long' if kwargs['quantity'] > 0 else 'short'
        
        if status == 'open':
            query = """
                INSERT INTO positions (
                    position_id, symbol, strategy, side, entry_price,
                    quantity, status, stop_loss, take_profit, metadata
                ) VALUES (
                    $1, $2, $3, $4::trade_side, $5,
                    $6, $7::position_status, $8, $9, $10
                )
                ON CONFLICT (position_id) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    status = EXCLUDED.status,
                    stop_loss = EXCLUDED.stop_loss,
                    take_profit = EXCLUDED.take_profit,
                    updated_at = CURRENT_TIMESTAMP
            """
            
            await conn.execute(query,
                position_id,
                kwargs['symbol'],
                kwargs.get('strategy'),
                side,
                float(kwargs['entry_price']) if kwargs.get('entry_price') else None,
                float(kwargs['quantity']),
                status,
                float(kwargs['stop_loss']) if kwargs.get('stop_loss') else None,
                float(kwargs['take_profit']) if kwargs.get('take_profit') else None,
                json.dumps(kwargs.get('metadata', {}))
            )
    
    async def _insert_balance(self, conn, **kwargs):
        """Insert balance snapshot"""
        query = """
            INSERT INTO balance_snapshots (
                account_id, total_balance, free_balance, used_balance,
                currency, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6)
        """
        
        await conn.execute(query,
            kwargs['account_id'],
            float(kwargs['total_balance']),
            float(kwargs.get('free_balance', kwargs['total_balance'])),
            float(kwargs.get('used_balance', 0)),
            kwargs.get('currency', 'USDT'),
            json.dumps(kwargs.get('metadata', {}))
        )
    
    # Public API methods (non-blocking)
    async def log_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: Union[Decimal, float],
        price: Union[Decimal, float],
        status: str = 'filled',
        order_type: str = 'market',
        strategy: Optional[str] = None,
        fee: Union[Decimal, float] = 0,
        fee_currency: Optional[str] = None,
        stop_loss: Optional[Union[Decimal, float]] = None,
        take_profit: Optional[Union[Decimal, float]] = None,
        executed_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Queue trade for async logging (non-blocking)"""
        try:
            operation = {
                'type': 'trade',
                'data': {
                    'trade_id': trade_id,
                    'symbol': symbol,
                    'side': side,
                    'quantity': quantity,
                    'price': price,
                    'status': status,
                    'order_type': order_type,
                    'strategy': strategy,
                    'fee': fee,
                    'fee_currency': fee_currency,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'executed_at': executed_at,
                    'metadata': metadata
                }
            }
            
            # Non-blocking queue put
            self._queue.put_nowait(operation)
            
        except asyncio.QueueFull:
            self.logger.warning("Database logging queue is full, dropping trade log")
        except Exception as e:
            self.logger.error(f"Failed to queue trade log: {e}")
    
    async def update_position(
        self,
        symbol: str,
        quantity: Union[Decimal, float],
        entry_price: Optional[Union[Decimal, float]] = None,
        exit_price: Optional[Union[Decimal, float]] = None,
        side: Optional[str] = None,
        strategy: Optional[str] = None,
        stop_loss: Optional[Union[Decimal, float]] = None,
        take_profit: Optional[Union[Decimal, float]] = None,
        position_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Queue position update for async logging (non-blocking)"""
        try:
            operation = {
                'type': 'position',
                'data': {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': entry_price,
                    'side': side,
                    'strategy': strategy,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'position_id': position_id,
                    'metadata': metadata
                }
            }
            
            self._queue.put_nowait(operation)
            
        except asyncio.QueueFull:
            self.logger.warning("Database logging queue is full, dropping position update")
        except Exception as e:
            self.logger.error(f"Failed to queue position update: {e}")
    
    async def log_balance(
        self,
        account_id: str,
        total_balance: Union[Decimal, float],
        free_balance: Optional[Union[Decimal, float]] = None,
        used_balance: Optional[Union[Decimal, float]] = None,
        currency: str = 'USDT',
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Queue balance snapshot for async logging (non-blocking)"""
        try:
            operation = {
                'type': 'balance',
                'data': {
                    'account_id': account_id,
                    'total_balance': total_balance,
                    'free_balance': free_balance,
                    'used_balance': used_balance,
                    'currency': currency,
                    'metadata': metadata
                }
            }
            
            self._queue.put_nowait(operation)
            
        except asyncio.QueueFull:
            self.logger.warning("Database logging queue is full, dropping balance log")
        except Exception as e:
            self.logger.error(f"Failed to queue balance log: {e}")
    
    async def close(self):
        """Close database logger"""
        self._shutdown = True
        
        # Wait for queue to empty
        if self._queue:
            await self._queue.join()
        
        # Cancel worker task
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        # Close database pool
        if self.pool:
            await self.pool.close()
            
        self.logger.info("Async database logger closed")


# Singleton instance
_async_db_logger_instance = None


async def get_async_db_logger() -> AsyncDatabaseLogger:
    """Get singleton async database logger instance"""
    global _async_db_logger_instance
    if _async_db_logger_instance is None:
        _async_db_logger_instance = AsyncDatabaseLogger()
        await _async_db_logger_instance.initialize()
    return _async_db_logger_instance


async def close_async_db_logger():
    """Close async database logger"""
    global _async_db_logger_instance
    if _async_db_logger_instance:
        await _async_db_logger_instance.close()
        _async_db_logger_instance = None


# Synchronous interface for easy integration with sync traders
import threading
import asyncio
import time
from typing import Callable


class SyncDatabaseLogger:
    """Synchronous interface to async database logger for easy integration"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._async_logger = None
        self._loop = None
        self._thread = None
        self._initialized = False
        self._shutdown = False
        
    def _run_async_loop(self):
        """Run async event loop in background thread"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            async def init():
                self._async_logger = await get_async_db_logger()
                self._initialized = True
                self.logger.info("Database logger initialized in background thread")
            
            self._loop.run_until_complete(init())
            self._loop.run_forever()
        except Exception as e:
            self.logger.error(f"Async loop error: {e}")
        finally:
            self._loop.close()
    
    def initialize(self) -> bool:
        """Initialize database logger"""
        try:
            if self._initialized:
                return True
                
            self.logger.info("Initializing database logger...")
            
            # Start background thread with event loop
            self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
            self._thread.start()
            
            # Wait for initialization
            timeout = 10.0
            start_time = time.time()
            while not self._initialized and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            if self._initialized:
                self.logger.info("Database logger initialized successfully")
                return True
            else:
                self.logger.warning("Database logger initialization timed out")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to initialize database logger: {e}")
            return False
    
    def _run_async_safe(self, coro):
        """Run async coroutine safely in background loop"""
        if not self._initialized or not self._loop:
            return
        
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception as e:
            self.logger.error(f"Failed to schedule async operation: {e}")
    
    def log_trade(self, **kwargs):
        """Log trade to database (non-blocking)"""
        if not self._initialized or not self._async_logger:
            return
        
        self._run_async_safe(self._async_logger.log_trade(**kwargs))
    
    def update_position(self, **kwargs):
        """Update position in database (non-blocking)"""
        if not self._initialized or not self._async_logger:
            return
        
        self._run_async_safe(self._async_logger.update_position(**kwargs))
    
    def log_balance(self, **kwargs):
        """Log balance snapshot to database (non-blocking)"""
        if not self._initialized or not self._async_logger:
            return
        
        self._run_async_safe(self._async_logger.log_balance(**kwargs))
    
    def close(self):
        """Close database logger"""
        if self._shutdown:
            return
        
        self._shutdown = True
        
        try:
            if self._loop and self._initialized:
                cleanup_coro = close_async_db_logger()
                future = asyncio.run_coroutine_threadsafe(cleanup_coro, self._loop)
                self._loop.call_soon_threadsafe(self._loop.stop)
                
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=5.0)
                
            self.logger.info("Database logger closed")
        except Exception as e:
            self.logger.error(f"Error closing database logger: {e}")


# Singleton sync logger instance
_sync_db_logger_instance = None
_logger_lock = threading.Lock()


def get_db_logger() -> SyncDatabaseLogger:
    """Get singleton sync database logger instance"""
    global _sync_db_logger_instance
    
    with _logger_lock:
        if _sync_db_logger_instance is None:
            _sync_db_logger_instance = SyncDatabaseLogger()
            _sync_db_logger_instance.initialize()
        return _sync_db_logger_instance


def close_db_logger():
    """Close sync database logger"""
    global _sync_db_logger_instance
    
    with _logger_lock:
        if _sync_db_logger_instance:
            _sync_db_logger_instance.close()
            _sync_db_logger_instance = None