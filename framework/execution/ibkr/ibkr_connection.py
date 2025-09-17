"""
IBKR connection management with auto-reconnection and error handling.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional, Callable, Any

from ib_async import IB, Stock, Forex, Index, Contract
from framework.utils.logger import get_logger
from .ibkr_config import IBKRConfig


class IBKRConnectionManager:
    """
    Professional IBKR connection management with auto-reconnection, 
    error handling, and rate limiting.
    """
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.logger = get_logger(__name__)
        
        # Connection state
        self.ib = IB()
        self.connected = False
        self.connecting = False
        self.reconnect_attempts = 0
        self.last_error = None
        
        # Rate limiting
        self.request_interval = 1.0 / config.max_requests_per_second
        self.last_request_time = 0.0
        
        # Callbacks
        self.on_connected_callback: Optional[Callable] = None
        self.on_disconnected_callback: Optional[Callable] = None
        self.on_error_callback: Optional[Callable] = None
        
        # Set up event handlers
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
        self.ib.timeoutEvent += self._on_timeout
    
    def _on_connected(self):
        """Handle connection events"""
        self.connected = True
        self.connecting = False
        self.reconnect_attempts = 0
        self.logger.info("Connected to IBKR successfully")
        
        if self.on_connected_callback:
            try:
                self.on_connected_callback()
            except Exception as e:
                self.logger.error(f"Error in connected callback: {e}")
    
    def _on_disconnected(self):
        """Handle disconnection events"""
        self.connected = False
        self.connecting = False
        self.logger.warning("Disconnected from IBKR")
        
        if self.on_disconnected_callback:
            try:
                self.on_disconnected_callback()
            except Exception as e:
                self.logger.error(f"Error in disconnected callback: {e}")
        
        # Auto-reconnect if enabled
        if self.config.auto_reconnect and self.reconnect_attempts < self.config.max_reconnect_attempts:
            self.logger.info(f"Auto-reconnecting in {self.config.reconnect_delay} seconds...")
            asyncio.create_task(self._auto_reconnect())
    
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
        
        if self.on_error_callback:
            try:
                self.on_error_callback(reqId, errorCode, errorString, contract)
            except Exception as e:
                self.logger.error(f"Error in error callback: {e}")
    
    def _on_timeout(self, idlePeriod: float):
        """Handle timeout events"""
        self.logger.warning(f"IBKR connection timeout after {idlePeriod:.1f}s of inactivity")
    
    async def _auto_reconnect(self):
        """Auto-reconnection logic"""
        await asyncio.sleep(self.config.reconnect_delay)
        
        if not self.connected and self.reconnect_attempts < self.config.max_reconnect_attempts:
            self.reconnect_attempts += 1
            self.logger.info(f"Reconnection attempt {self.reconnect_attempts}/{self.config.max_reconnect_attempts}")
            
            try:
                await self.connect()
            except Exception as e:
                self.logger.error(f"Reconnection attempt {self.reconnect_attempts} failed: {e}")
    
    async def connect(self) -> bool:
        """
        Connect to IBKR TWS/IB Gateway
        
        Returns:
            bool: True if connected successfully
        """
        if self.connected:
            self.logger.info("Already connected to IBKR")
            return True
        
        if self.connecting:
            self.logger.info("Connection attempt already in progress")
            return False
        
        self.connecting = True
        
        try:
            self.logger.info(f"Connecting to IBKR at {self.config.host}:{self.config.port} (client_id={self.config.client_id})")
            
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.connect_timeout,
                readonly=False  # We need trading permissions
            )
            
            # Wait a moment for connection to stabilize
            await asyncio.sleep(0.5)
            
            # Verify account access
            if self.config.account_id:
                managed_accounts = self.ib.managedAccounts()
                self.logger.info(f"Managed accounts: {managed_accounts}")
                self.logger.info(f"Configured account ID: '{self.config.account_id}'")
                if self.config.account_id not in managed_accounts:
                    raise ValueError(f"Account {self.config.account_id} not accessible. Available: {managed_accounts}")
            else:
                self.logger.info("No account ID configured - using default account")
            
            return self.connected
            
        except Exception as e:
            self.connecting = False
            self.logger.error(f"Failed to connect to IBKR: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from IBKR"""
        if self.connected:
            self.logger.info("Disconnecting from IBKR")
            self.ib.disconnect()
            await asyncio.sleep(0.1)  # Allow disconnect to complete
        
        self.connected = False
        self.connecting = False
    
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.connected and self.ib.isConnected()
    
    def get_connection_stats(self) -> Optional[dict]:
        """Get connection statistics"""
        if self.connected:
            try:
                # Try the connectionStats method if available
                if hasattr(self.ib, 'connectionStats'):
                    return self.ib.connectionStats()
                else:
                    # Fallback to basic connection info
                    return {
                        'connected': self.ib.isConnected(),
                        'client_id': self.config.client_id,
                        'host': self.config.host,
                        'port': self.config.port
                    }
            except Exception as e:
                self.logger.debug(f"Could not get connection stats: {e}")
                return {'connected': self.ib.isConnected()}
        return None
    
    def get_managed_accounts(self) -> list:
        """Get list of managed accounts"""
        if self.connected:
            return self.ib.managedAccounts()
        return []
    
    def set_callbacks(self, 
                     on_connected: Optional[Callable] = None,
                     on_disconnected: Optional[Callable] = None,
                     on_error: Optional[Callable] = None):
        """Set event callbacks"""
        self.on_connected_callback = on_connected
        self.on_disconnected_callback = on_disconnected
        self.on_error_callback = on_error
    
    async def rate_limit(self):
        """Apply rate limiting to API requests"""
        now = time.time()
        elapsed = now - self.last_request_time
        
        if elapsed < self.request_interval:
            sleep_time = self.request_interval - elapsed
            await asyncio.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
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
    
    @asynccontextmanager
    async def connection_context(self):
        """Context manager for automatic connection/disconnection"""
        try:
            await self.connect()
            yield self
        finally:
            await self.disconnect()
    
    def __repr__(self) -> str:
        return f"IBKRConnectionManager(connected={self.connected}, config={self.config})"


async def test_connection(config: IBKRConfig) -> bool:
    """
    Test IBKR connection
    
    Args:
        config: IBKR configuration
        
    Returns:
        bool: True if connection successful
    """
    manager = IBKRConnectionManager(config)
    
    try:
        success = await manager.connect()
        if success:
            print(f"✅ Successfully connected to IBKR")
            print(f"📊 Managed accounts: {manager.get_managed_accounts()}")
            print(f"📈 Connection stats: {manager.get_connection_stats()}")
        else:
            print(f"❌ Failed to connect to IBKR")
        
        await manager.disconnect()
        return success
        
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        await manager.disconnect()
        return False