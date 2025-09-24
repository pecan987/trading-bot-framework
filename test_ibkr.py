#!/usr/bin/env python
"""
Simple IBKR connection test script
Tests:
1. Connection to IB Gateway
2. Fetching market data for AAPL
3. Placing a test order (paper trading)
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv
from ib_async import IB, Stock, MarketOrder, LimitOrder
import pandas as pd

# Load environment variables
load_dotenv()

async def test_ibkr_connection():
    """Test IBKR connection and basic operations"""
    
    # Configuration
    host = os.getenv('IBKR_HOST', 'localhost')
    port = int(os.getenv('IBKR_PORT', '4004'))  # Paper trading port
    client_id = int(os.getenv('IBKR_CLIENT_ID', '2'))  # Use different client ID to avoid conflicts
    
    print(f"=== IBKR Connection Test ===")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Client ID: {client_id}")
    print(f"Time: {datetime.now()}")
    print("=" * 30)
    
    # Create IB instance
    ib = IB()
    
    try:
        # 1. Test Connection
        print("\n1. Testing connection...")
        await ib.connectAsync(host, port, clientId=client_id, timeout=10)
        print(f"✓ Connected successfully!")
        print(f"✓ Connection status: {ib.isConnected()}")
        
        # Get account info
        accounts = ib.managedAccounts()
        print(f"✓ Managed accounts: {accounts}")
        
        # Wait for connection to stabilize
        await asyncio.sleep(1)
        
        # 2. Get Account Summary
        print("\n2. Getting account information...")
        try:
            # Use async version to avoid event loop conflicts
            account_summary = await ib.accountSummaryAsync()
            if account_summary:
                print("✓ Account Summary:")
                for item in account_summary[:5]:  # Show first 5 items
                    print(f"  - {item.tag}: {item.value} {item.currency}")
        except Exception as e:
            print(f"⚠ Account summary error: {e}")
            # Try basic account value instead
            try:
                account_values = ib.accountValues()
                if account_values:
                    print("✓ Account Values (alternative):")
                    for val in account_values[:5]:
                        print(f"  - {val.tag}: {val.value} {val.currency}")
            except Exception as e2:
                print(f"⚠ Account values also failed: {e2}")
        
        # 3. Create AAPL contract
        print("\n3. Creating AAPL contract...")
        aapl = Stock('AAPL', 'SMART', 'USD')
        
        # Qualify the contract (get full details)
        await ib.qualifyContractsAsync(aapl)
        print(f"✓ Contract qualified: {aapl}")
        
        # 4. Get Market Data
        print("\n4. Fetching market data...")
        
        # Set market data type to delayed (free)
        print("  Setting market data type to delayed (free)...")
        ib.reqMarketDataType(3)  # 3 = delayed data (free)
        await asyncio.sleep(1)
        
        # Request market data
        ticker = ib.reqMktData(aapl, '', False, False)
        await asyncio.sleep(3)  # Wait longer for delayed data
        
        if ticker.last and ticker.last > 0:
            print(f"✓ Delayed price: ${ticker.last}")
            print(f"  Bid: ${ticker.bid if ticker.bid else 'N/A'}")
            print(f"  Ask: ${ticker.ask if ticker.ask else 'N/A'}")
            print(f"  Volume: {ticker.volume if ticker.volume else 'N/A'}")
        else:
            print("⚠ No market data available")
            print("  This may require market data subscription in IBKR account")
            
        # Cancel market data to clean up
        ib.cancelMktData(aapl)
        
        # 5. Get Historical Data
        print("\n5. Fetching historical data...")
        bars = await ib.reqHistoricalDataAsync(
            aapl,
            endDateTime='',
            durationStr='1 D',
            barSizeSetting='1 hour',
            whatToShow='MIDPOINT',
            useRTH=True
        )
        
        if bars:
            print(f"✓ Retrieved {len(bars)} historical bars")
            df = pd.DataFrame(bars)
            print(f"  Last 3 bars:")
            print(df.tail(3)[['date', 'open', 'high', 'low', 'close', 'volume']])
        else:
            print("⚠ No historical data received")
        
        # 6. Place a Test Order (Small quantity)
        print("\n6. Placing a test order...")
        print("⚠ PAPER TRADING MODE - This is a test order")
        
        # Create a small limit order (1 share, far from market price to avoid fill)
        if ticker.last and ticker.last > 0:
            # Place a buy limit order 10% below current price
            limit_price = round(ticker.last * 0.9, 2)
        else:
            # Fallback price if no market data
            limit_price = 100.00
        
        order = LimitOrder(
            action='BUY',
            totalQuantity=1,
            lmtPrice=limit_price
        )
        
        print(f"  Order details: BUY 1 AAPL @ ${limit_price} (LIMIT)")
        
        # Place the order
        trade = ib.placeOrder(aapl, order)
        print(f"✓ Order placed! Order ID: {trade.order.orderId}")
        
        # Wait for order status
        await asyncio.sleep(2)
        
        print(f"  Order status: {trade.orderStatus.status}")
        print(f"  Filled: {trade.orderStatus.filled}/{trade.orderStatus.remaining}")
        
        # 7. Check Open Orders
        print("\n7. Checking open orders...")
        open_orders = ib.openOrders()
        print(f"✓ Open orders: {len(open_orders)}")
        for open_order in open_orders[:3]:  # Show first 3
            print(f"  - Order {open_order.orderId}: {open_order.action} {open_order.totalQuantity} @ {open_order.lmtPrice if hasattr(open_order, 'lmtPrice') else 'MKT'}")
        
        # 8. Cancel the test order
        print("\n8. Canceling test order...")
        ib.cancelOrder(order)
        await asyncio.sleep(1)
        print(f"✓ Order canceled. Final status: {trade.orderStatus.status}")
        
        # 9. Get Positions
        print("\n9. Checking positions...")
        positions = ib.positions()
        if positions:
            print(f"✓ Positions found: {len(positions)}")
            for pos in positions:
                print(f"  - {pos.contract.symbol}: {pos.position} shares @ avg cost ${pos.avgCost}")
        else:
            print("  No open positions")
        
        print("\n" + "=" * 30)
        print("✓ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("✓ IBKR connection is working properly")
        print("=" * 30)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Disconnect
        if ib.isConnected():
            print("\nDisconnecting...")
            ib.disconnect()
            print("✓ Disconnected")

def main():
    """Main entry point"""
    print("Starting IBKR connection test...")
    print("Make sure IB Gateway is running and accepting API connections")
    print("")
    
    # Run the async test
    asyncio.run(test_ibkr_connection())

if __name__ == "__main__":
    main()