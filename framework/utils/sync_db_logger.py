import asyncio
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional, List
from functools import wraps

from utils.db_logger import get_db_logger, close_db_logger
from utils.logger import get_logger

logger = get_logger(__name__)


def run_async(func):
    """Decorator to run async functions in sync context."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # Create new event loop if none exists
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            # If loop is already running (e.g., in Jupyter), create a task
            task = asyncio.create_task(func(*args, **kwargs))
            return task
        else:
            # Run the coroutine
            return loop.run_until_complete(func(*args, **kwargs))
    return wrapper


class SyncDatabaseLogger:
    """Synchronous wrapper for DatabaseLogger."""
    
    def __init__(self):
        self._db_logger = None
        self._initialized = False
        
    @run_async
    async def initialize(self):
        """Initialize the database logger."""
        if not self._initialized:
            self._db_logger = await get_db_logger()
            self._initialized = True
            
    @run_async
    async def close(self):
        """Close the database logger."""
        if self._initialized:
            await close_db_logger()
            self._initialized = False
            
    @run_async
    async def log_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        status: str = 'pending',
        order_type: str = 'market',
        strategy_name: Optional[str] = None,
        signal_reason: Optional[str] = None,
        exchange: Optional[str] = None,
        account_id: Optional[str] = None,
        commission: Decimal = Decimal('0'),
        commission_asset: Optional[str] = None,
        executed_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log a trade to the database."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.log_trade(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=status,
            order_type=order_type,
            strategy_name=strategy_name,
            signal_reason=signal_reason,
            exchange=exchange,
            account_id=account_id,
            commission=commission,
            commission_asset=commission_asset,
            executed_at=executed_at,
            metadata=metadata
        )
        
    @run_async
    async def update_position(
        self,
        symbol: str,
        quantity: Decimal,
        average_price: Decimal,
        exchange: Optional[str] = None,
        account_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        current_price: Optional[Decimal] = None,
        unrealized_pnl: Optional[Decimal] = None,
        realized_pnl: Optional[Decimal] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Update or create a position record."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.update_position(
            symbol=symbol,
            quantity=quantity,
            average_price=average_price,
            exchange=exchange,
            account_id=account_id,
            strategy_name=strategy_name,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            metadata=metadata
        )
        
    @run_async
    async def log_signal(
        self,
        symbol: str,
        strategy_name: str,
        signal_type: str,
        price: Decimal,
        signal_strength: Optional[Decimal] = None,
        indicators: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log a strategy signal."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.log_signal(
            symbol=symbol,
            strategy_name=strategy_name,
            signal_type=signal_type,
            price=price,
            signal_strength=signal_strength,
            indicators=indicators,
            metadata=metadata
        )
        
    @run_async
    async def update_balance(
        self,
        account_id: str,
        asset: str,
        free_balance: Decimal,
        locked_balance: Decimal,
        exchange: Optional[str] = None
    ):
        """Update account balance."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.update_balance(
            account_id=account_id,
            asset=asset,
            free_balance=free_balance,
            locked_balance=locked_balance,
            exchange=exchange
        )
        
    @run_async
    async def log_performance_metrics(
        self,
        strategy_name: str,
        symbol: Optional[str] = None,
        total_trades: int = 0,
        winning_trades: int = 0,
        losing_trades: int = 0,
        total_pnl: Decimal = Decimal('0'),
        win_rate: Optional[Decimal] = None,
        sharpe_ratio: Optional[Decimal] = None,
        max_drawdown: Optional[Decimal] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log performance metrics."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.log_performance_metrics(
            strategy_name=strategy_name,
            symbol=symbol,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            win_rate=win_rate,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            period_start=period_start,
            period_end=period_end,
            metadata=metadata
        )
        
    @run_async
    async def get_recent_trades(
        self,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recent trades from database."""
        if not self._initialized:
            await self.initialize()
            
        return await self._db_logger.get_recent_trades(
            symbol=symbol,
            strategy_name=strategy_name,
            limit=limit
        )


# Singleton instance
_sync_db_logger: Optional[SyncDatabaseLogger] = None


def get_sync_db_logger() -> SyncDatabaseLogger:
    """Get or create the sync database logger instance."""
    global _sync_db_logger
    if _sync_db_logger is None:
        try:
            logger.info(
                "Creating sync database logger instance...",
                extra={'instance_exists': _sync_db_logger is not None}
            )
            _sync_db_logger = SyncDatabaseLogger()
            # Initialize on first use
            logger.info(
                "Initializing sync database logger...",
                extra={'logger_created': True}
            )
            _sync_db_logger.initialize()
            logger.info(
                "Sync database logger initialized successfully",
                extra={'initialization_complete': True}
            )
        except Exception as e:
            logger.error(
                "Failed to initialize sync database logger",
                extra={
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
            raise
    return _sync_db_logger