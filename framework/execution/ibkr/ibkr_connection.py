"""
IBKR connection management - Synchronous implementation using ib_async properly
"""

import time
from typing import Optional, Callable, Any

from ib_async import IB, Stock, Forex, Index, Contract
from framework.utils.logger import setup_logger
from .ibkr_config import IBKRConfig


class IBKRConnection:
    """
    Synchronous IBKR connection management using ib_async library properly
    """
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.logger = setup_logger("INFO")
        
        # Connection state
        self.ib = IB()
        self.connected = False
        self.reconnect_attempts = 0
        self.last_error = None
        
        # Rate limiting
        self.request_interval = 1.0 / config.max_requests_per_second
        self.last_request_time = 0.0
        
        # Set up event handlers
        self.ib.errorEvent += self._on_error
    
    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract: Contract = None):
        """Handle IBKR errors"""
        self.last_error = {
            'reqId': reqId,
            'errorCode': errorCode,
            'errorString': errorString,
            'contract': contract,
            'timestamp': time.time()
        }
        
        # Log error with appropriate level
        if errorCode in [2104, 2106, 2158]:  # Market data warnings
            self.logger.info(f"IBKR Info [{errorCode}]: {errorString}")
        elif errorCode in [200, 399, 400, 401, 402]:  # Order/position errors
            self.logger.warning(f"IBKR Warning [{errorCode}]: {errorString}")
        elif errorCode >= 500:  # System errors
            self.logger.error(f"IBKR Error [{errorCode}]: {errorString}")
        else:
            self.logger.debug(f"IBKR Message [{errorCode}]: {errorString}")
    
    def connect(self) -> bool:
        """
        Connect to IBKR TWS/IB Gateway using synchronous methods
        
        Returns:
            bool: True if connected successfully
        """
        if self.connected:
            self.logger.info("Already connected to IBKR")
            return True
        
        try:
            self.logger.info(f"Connecting to IBKR at {self.config.host}:{self.config.port} (client_id={self.config.client_id})")
            
            # Use synchronous connect method
            self.ib.connect(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.connect_timeout
            )
            
            self.connected = True
            self.reconnect_attempts = 0
            
            # Wait a moment for connection to stabilize
            time.sleep(0.5)
            
            # Set market data type
            self.ib.reqMarketDataType(self.config.market_data_type.value)
            self.logger.info(f"Market data type set to: {self.config.market_data_type.name}")
            
            # Verify account access
            managed_accounts = self.ib.managedAccounts()
            self.logger.info(f"Managed accounts: {managed_accounts}")
            
            if self.config.account_id:
                self.logger.info(f"Configured account ID: '{self.config.account_id}'")
                if self.config.account_id not in managed_accounts:
                    raise ValueError(f"Account {self.config.account_id} not accessible. Available: {managed_accounts}")
            else:
                self.logger.info("No account ID configured - using default account")
            
            self.logger.info("Connected to IBKR successfully")
            return True
            
        except Exception as e:
            self.connected = False
            self.logger.error(f"Failed to connect to IBKR: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from IBKR"""
        if self.connected:
            self.logger.info("Disconnecting from IBKR")
            self.ib.disconnect()
            self.connected = False
    
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.connected and self.ib.isConnected()
    
    def get_managed_accounts(self) -> list:
        """Get list of managed accounts"""
        if self.connected:
            return self.ib.managedAccounts()
        return []
    
    def get_account_summary(self) -> list:
        """Get account summary using synchronous method"""
        if not self.connected:
            return []
        
        try:
            return self.ib.accountSummary()
        except Exception as e:
            self.logger.warning(f"Could not get account summary: {e}")
            return []
    
    def get_positions(self) -> list:
        """Get current positions"""
        if not self.connected:
            return []
        
        try:
            return self.ib.positions()
        except Exception as e:
            self.logger.error(f"Failed to get positions: {e}")
            return []
    
    def create_contract(self, symbol: str, sec_type: str = 'STK', 
                       exchange: str = 'SMART', currency: str = 'USD') -> Contract:
        """
        Create IBKR contract object
        
        Args:
            symbol: Symbol (e.g., 'AAPL', 'SPY')
            sec_type: Security type ('STK', 'OPT', 'FUT', 'FOREX', etc.)
            exchange: Exchange ('SMART', 'NYSE', 'NASDAQ', etc.)
            currency: Currency ('USD', 'EUR', etc.)
        """
        if sec_type == 'STK':
            return Stock(symbol, exchange, currency)
        elif sec_type == 'FOREX':
            return Forex(symbol)
        elif sec_type == 'IND':
            return Index(symbol, exchange, currency)
        else:
            # Generic contract
            contract = Contract()
            contract.symbol = symbol
            contract.secType = sec_type
            contract.exchange = exchange
            contract.currency = currency
            return contract
    
    def qualify_contract(self, contract: Contract) -> bool:
        """Qualify contract with IBKR using synchronous method"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return False
        
        try:
            self.rate_limit()
            qualified = self.ib.qualifyContracts(contract)
            return len(qualified) > 0
        except Exception as e:
            self.logger.error(f"Failed to qualify contract {contract.symbol}: {e}")
            return False
    
    def get_historical_data(self, contract: Contract, duration: str = '1 D', 
                           bar_size: str = '1 hour', what_to_show: str = 'MIDPOINT') -> list:
        """Get historical data using synchronous method"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return []
        
        try:
            self.logger.debug(f"Requesting historical data for {contract.symbol}: duration={duration}, bar_size={bar_size}")
            self.rate_limit()
            
            # Ensure contract is qualified first
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                self.logger.error(f"Failed to qualify contract for {contract.symbol}")
                return []
            
            # Use the first qualified contract
            qualified_contract = qualified[0]
            self.logger.debug(f"Using qualified contract: {qualified_contract}")
            
            # Request historical data with timeout
            bars = self.ib.reqHistoricalData(
                contract=qualified_contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=False,
                timeout=30  # 30 second timeout
            )
            
            if bars:
                self.logger.debug(f"Retrieved {len(bars)} historical bars for {contract.symbol}")
            else:
                self.logger.warning(f"No historical data returned for {contract.symbol}")
            
            return bars
            
        except Exception as e:
            self.logger.error(f"Failed to get historical data for {contract.symbol}: {e}")
            return []
    
    def place_order(self, contract: Contract, order) -> Optional[Any]:
        """Place order using synchronous method"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return None
        
        try:
            self.rate_limit()
            trade = self.ib.placeOrder(contract, order)
            return trade
        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            return None
    
    def cancel_order(self, order) -> bool:
        """Cancel order"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return False
        
        try:
            self.ib.cancelOrder(order)
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel order: {e}")
            return False
    
    def get_open_orders(self) -> list:
        """Get open orders"""
        if not self.connected:
            return []
        
        try:
            return self.ib.openOrders()
        except Exception as e:
            self.logger.error(f"Failed to get open orders: {e}")
            return []
    
    def get_live_price(self, contract: Contract, timeout: float = 10.0) -> Optional[float]:
        """Get live market price for a contract"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return None
        
        try:
            self.logger.debug(f"Requesting live market data for {contract.symbol}")
            self.rate_limit()
            
            # Ensure contract is qualified first
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                self.logger.error(f"Failed to qualify contract for {contract.symbol}")
                return None
            
            qualified_contract = qualified[0]
            
            # Request market data
            ticker = self.ib.reqMktData(qualified_contract, '', False, False)
            
            # Wait for price data with timeout
            start_time = time.time()
            while time.time() - start_time < timeout:
                self.ib.sleep(0.1)  # Small sleep to allow data to arrive
                
                # Check for valid price data
                if ticker.last and ticker.last > 0:
                    price = float(ticker.last)
                    self.logger.debug(f"Got live price for {contract.symbol}: ${price}")
                    # Cancel the market data subscription
                    self.ib.cancelMktData(qualified_contract)
                    return price
                elif ticker.close and ticker.close > 0:
                    # Fallback to close price if last is not available
                    price = float(ticker.close)
                    self.logger.debug(f"Got close price for {contract.symbol}: ${price}")
                    self.ib.cancelMktData(qualified_contract)
                    return price
            
            # Timeout reached, cancel subscription
            self.ib.cancelMktData(qualified_contract)
            self.logger.warning(f"Timeout waiting for live price data for {contract.symbol}")
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get live price for {contract.symbol}: {e}")
            return None
    
    def get_market_snapshot(self, contract: Contract) -> Optional[dict]:
        """Get market snapshot with bid/ask/last prices"""
        if not self.connected:
            self.logger.error("Not connected to IBKR")
            return None
        
        try:
            self.logger.debug(f"Requesting market snapshot for {contract.symbol}")
            self.rate_limit()
            
            # Ensure contract is qualified first
            qualified = self.ib.qualifyContracts(contract)
            if not qualified:
                self.logger.error(f"Failed to qualify contract for {contract.symbol}")
                return None
            
            qualified_contract = qualified[0]
            
            # Request market data
            ticker = self.ib.reqMktData(qualified_contract, '', True, False)  # snapshot=True
            
            # Wait briefly for data
            self.ib.sleep(2.0)
            
            snapshot = {
                'symbol': contract.symbol,
                'last': float(ticker.last) if ticker.last and ticker.last > 0 else None,
                'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else None,
                'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else None,
                'close': float(ticker.close) if ticker.close and ticker.close > 0 else None,
                'volume': int(ticker.volume) if ticker.volume else None,
                'timestamp': time.time()
            }
            
            # Cancel the market data subscription
            self.ib.cancelMktData(qualified_contract)
            
            self.logger.debug(f"Market snapshot for {contract.symbol}: {snapshot}")
            return snapshot
            
        except Exception as e:
            self.logger.error(f"Failed to get market snapshot for {contract.symbol}: {e}")
            return None
    
    def rate_limit(self):
        """Apply rate limiting to API requests using synchronous sleep"""
        now = time.time()
        elapsed = now - self.last_request_time
        
        if elapsed < self.request_interval:
            sleep_time = self.request_interval - elapsed
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def get_last_error(self) -> Optional[dict]:
        """Get the last error that occurred"""
        return self.last_error
    
    def clear_last_error(self):
        """Clear the last error"""
        self.last_error = None
    
    def __repr__(self) -> str:
        return f"IBKRConnection(connected={self.connected}, config={self.config})"


def test_connection(config: IBKRConfig) -> bool:
    """
    Test IBKR connection synchronously
    
    Args:
        config: IBKR configuration
        
    Returns:
        bool: True if connection successful
    """
    connection = IBKRConnection(config)
    
    try:
        success = connection.connect()
        if success:
            print(f"✅ Successfully connected to IBKR")
            print(f"📊 Managed accounts: {connection.get_managed_accounts()}")
            
            # Test account summary
            account_summary = connection.get_account_summary()
            if account_summary:
                print(f"💰 Account summary: {len(account_summary)} items")
                for item in account_summary[:3]:
                    print(f"   - {item.tag}: {item.value} {item.currency}")
            
            # Test positions
            positions = connection.get_positions()
            print(f"📈 Current positions: {len(positions)}")
            
        else:
            print(f"❌ Failed to connect to IBKR")
        
        connection.disconnect()
        return success
        
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        connection.disconnect()
        return False