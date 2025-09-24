"""
IBKR configuration management for trading bot integration.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class IBKRAccountType(Enum):
    """IBKR account types"""
    PAPER = "paper"
    LIVE = "live"


class IBKRMarketDataType(Enum):
    """IBKR market data types"""
    LIVE = 1        # Real-time market data (subscription required)
    FROZEN = 2      # Last available quote (free)
    DELAYED = 3     # 15-minute delayed data (free)
    DELAYED_FROZEN = 4  # Delayed last quote (free)


@dataclass
class IBKRConfig:
    """
    IBKR configuration settings for trading bot integration.
    
    Attributes:
        host: IBKR TWS/Gateway host (default: 127.0.0.1)
        port: IBKR TWS/Gateway port (7497=paper, 7496=live, 4001/4002=Gateway)
        client_id: Unique client ID (0-32 range)
        account_type: Paper or live account
        account_id: IBKR account ID (optional)
        market_data_type: Market data subscription type
        connect_timeout: Connection timeout in seconds
        read_timeout: Read timeout in seconds
        auto_reconnect: Enable automatic reconnection
        max_reconnect_attempts: Maximum reconnection attempts
        reconnect_delay: Delay between reconnection attempts
        max_requests_per_second: API rate limiting
        historical_data_timeout: Historical data request timeout
    """
    
    host: str = "127.0.0.1"
    port: int = 7497  # 7496=live, 7497=paper, 4001/4002=Gateway
    client_id: int = 1
    account_type: IBKRAccountType = IBKRAccountType.PAPER
    account_id: Optional[str] = None
    market_data_type: IBKRMarketDataType = IBKRMarketDataType.DELAYED
    
    # Connection settings
    connect_timeout: int = 10
    read_timeout: int = 30
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 5
    reconnect_delay: int = 5
    
    # Rate limiting
    max_requests_per_second: int = 50
    historical_data_timeout: int = 60
    
    @property
    def is_paper_trading(self) -> bool:
        """Check if this is paper trading configuration"""
        return self.account_type == IBKRAccountType.PAPER
    
    @property
    def is_gateway_port(self) -> bool:
        """Check if using IB Gateway ports"""
        return self.port in [4001, 4002]
    
    @classmethod
    def from_env(cls) -> 'IBKRConfig':
        """Create configuration from environment variables"""
        
        # Parse account type
        account_type_str = os.getenv('IBKR_ACCOUNT_TYPE', 'paper').lower()
        account_type = IBKRAccountType.PAPER if account_type_str == 'paper' else IBKRAccountType.LIVE
        
        # Parse market data type
        market_data_type_int = int(os.getenv('IBKR_MARKET_DATA_TYPE', '3'))
        market_data_type = IBKRMarketDataType(market_data_type_int)
        
        # Determine port based on account type if not specified
        default_port = 7497 if account_type == IBKRAccountType.PAPER else 7496
        port = int(os.getenv('IBKR_PORT', str(default_port)))
        
        return cls(
            host=os.getenv('IBKR_HOST', '127.0.0.1'),
            port=port,
            client_id=int(os.getenv('IBKR_CLIENT_ID', '1')),
            account_type=account_type,
            account_id=os.getenv('IBKR_ACCOUNT_ID'),
            market_data_type=market_data_type,
            connect_timeout=int(os.getenv('IBKR_CONNECT_TIMEOUT', '10')),
            read_timeout=int(os.getenv('IBKR_READ_TIMEOUT', '30')),
            auto_reconnect=os.getenv('IBKR_AUTO_RECONNECT', 'true').lower() == 'true',
            max_reconnect_attempts=int(os.getenv('IBKR_MAX_RECONNECT_ATTEMPTS', '5')),
            reconnect_delay=int(os.getenv('IBKR_RECONNECT_DELAY', '5')),
            max_requests_per_second=int(os.getenv('IBKR_MAX_REQUESTS_PER_SECOND', '50')),
            historical_data_timeout=int(os.getenv('IBKR_HISTORICAL_DATA_TIMEOUT', '60'))
        )
    
    def __str__(self) -> str:
        return f"IBKRConfig(host={self.host}, port={self.port}, account_type={self.account_type.value}, market_data_type={self.market_data_type.value})"
    
    def __repr__(self) -> str:
        return self.__str__()