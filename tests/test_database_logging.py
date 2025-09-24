"""
Test database logging functionality
"""
import asyncio
import time
from datetime import datetime
from decimal import Decimal

from framework.utils.async_db_logger import get_db_logger, close_db_logger


def test_trade_db_logger():
    """Test synchronous trade database logger"""
    print("Testing Database Logger...")
    
    # Get logger instance
    db_logger = get_db_logger()
    print(f"Database logger initialized: {db_logger._initialized}")
    
    if not db_logger._initialized:
        print("Database logger not initialized, skipping test")
        return
    
    # Test trade logging
    print("Logging test trade...")
    db_logger.log_trade(
        trade_id=f"test_trade_{int(time.time())}",
        symbol="BTC_USDT",
        side="buy",
        quantity=0.001,
        price=50000.0,
        status="filled",
        order_type="market",
        strategy="test_strategy",
        fee=0.05,
        fee_currency="USDT",
        executed_at=datetime.now(),
        metadata={
            "test": True,
            "exchange": "test_exchange"
        }
    )
    print("Trade logged successfully")
    
    # Test position logging
    print("Logging test position...")
    db_logger.update_position(
        symbol="BTC_USDT",
        quantity=0.001,
        entry_price=50000.0,
        side="long",
        strategy="test_strategy",
        metadata={
            "test": True,
            "entry_time": datetime.now().isoformat(),
            "exchange": "test_exchange"
        }
    )
    print("Position logged successfully")
    
    # Test balance logging
    print("Logging test balance...")
    db_logger.log_balance(
        account_id="test_account",
        total_balance=10000.0,
        free_balance=9950.0,
        used_balance=50.0,
        currency="USDT",
        metadata={
            "test": True,
            "exchange": "test_exchange"
        }
    )
    print("Balance logged successfully")
    
    # Wait a moment for async operations to complete
    time.sleep(2)
    
    # Test position close
    print("Logging position close...")
    db_logger.update_position(
        symbol="BTC_USDT",
        quantity=0,
        entry_price=50000.0,
        side="long", 
        strategy="test_strategy",
        metadata={
            "test": True,
            "close_time": datetime.now().isoformat(),
            "close_price": 51000.0,
            "pnl": 1.0,
            "exchange": "test_exchange"
        }
    )
    print("Position close logged successfully")
    
    # Log closing trade
    print("Logging closing trade...")
    db_logger.log_trade(
        trade_id=f"test_close_{int(time.time())}",
        symbol="BTC_USDT",
        side="sell",
        quantity=0.001,
        price=51000.0,
        status="filled",
        order_type="market",
        strategy="test_strategy",
        fee=0.051,
        fee_currency="USDT",
        executed_at=datetime.now(),
        metadata={
            "test": True,
            "pnl": 1.0,
            "exchange": "test_exchange"
        }
    )
    print("Closing trade logged successfully")
    
    # Wait for final operations
    time.sleep(2)
    
    print("All database logging tests completed successfully!")
    
    # Close logger
    close_db_logger()
    print("Database logger closed")


async def test_async_db_logger():
    """Test async database logger directly"""
    print("Testing Async Database Logger...")
    
    try:
        from framework.utils.async_db_logger import get_async_db_logger, close_async_db_logger
        
        # Get async logger
        async_logger = await get_async_db_logger()
        print("Async database logger initialized")
        
        # Test async trade logging
        await async_logger.log_trade(
            trade_id=f"async_test_{int(time.time())}",
            symbol="ETH_USDT",
            side="buy",
            quantity=0.1,
            price=3000.0,
            status="filled",
            strategy="async_test_strategy",
            metadata={"async_test": True}
        )
        print("Async trade logged successfully")
        
        # Test async position logging
        await async_logger.update_position(
            symbol="ETH_USDT",
            quantity=0.1,
            entry_price=3000.0,
            side="long",
            strategy="async_test_strategy",
            metadata={"async_test": True}
        )
        print("Async position logged successfully")
        
        # Test async balance logging
        await async_logger.log_balance(
            account_id="async_test_account",
            total_balance=5000.0,
            free_balance=4700.0,
            used_balance=300.0,
            currency="USDT",
            metadata={"async_test": True}
        )
        print("Async balance logged successfully")
        
        # Close async logger
        await close_async_db_logger()
        print("Async database logger closed")
        
    except Exception as e:
        print(f"Async database logger test failed: {e}")


def test_database_connection():
    """Test database connection"""
    print("Testing database connection...")
    
    try:
        import asyncpg
        import os
        
        async def check_connection():
            connection_string = (
                f"postgresql://{os.getenv('DB_USER', 'trading_user')}:"
                f"{os.getenv('DB_PASSWORD', 'trading_password')}@"
                f"{os.getenv('DB_HOST', 'postgres')}:"
                f"{os.getenv('DB_PORT', '5432')}/"
                f"{os.getenv('DB_NAME', 'trading')}"
            )
            
            try:
                conn = await asyncpg.connect(connection_string)
                print("Database connection successful")
                
                # Test basic query
                result = await conn.fetchval("SELECT COUNT(*) FROM trades WHERE metadata->>'test' = 'true'")
                print(f"Test trades in database: {result}")
                
                result = await conn.fetchval("SELECT COUNT(*) FROM positions WHERE metadata->>'test' = 'true'") 
                print(f"Test positions in database: {result}")
                
                result = await conn.fetchval("SELECT COUNT(*) FROM balance_snapshots WHERE metadata->>'test' = 'true'")
                print(f"Test balance snapshots in database: {result}")
                
                await conn.close()
                print("Database connection closed")
                
            except Exception as e:
                print(f"Database connection failed: {e}")
        
        asyncio.run(check_connection())
        
    except ImportError:
        print("asyncpg not available, skipping database connection test")
    except Exception as e:
        print(f"Database connection test failed: {e}")


if __name__ == "__main__":
    print("=== Database Logging Test Suite ===\n")
    
    # Test database connection first
    test_database_connection()
    print()
    
    # Test async logger
    asyncio.run(test_async_db_logger())
    print()
    
    # Test synchronous wrapper
    test_trade_db_logger()
    print()
    
    print("=== All tests completed ===")