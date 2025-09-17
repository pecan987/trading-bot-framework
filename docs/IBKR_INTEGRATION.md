# IBKR Integration Guide

This guide covers setting up Interactive Brokers (IBKR) integration with the trading framework using Docker Gateway.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [IBKR Account Setup](#ibkr-account-setup)
3. [Docker Gateway Setup](#docker-gateway-setup)
4. [Configuration](#configuration)
5. [Running IBKR Trading](#running-ibkr-trading)
6. [Troubleshooting](#troubleshooting)
7. [Security Considerations](#security-considerations)

## Prerequisites

### IBKR Account Requirements
- Active Interactive Brokers account (Paper or Live)
- TWS or IB Gateway access enabled
- API permissions enabled in your account
- Market data subscriptions (optional, delayed data is free)

### System Requirements
- Docker and Docker Compose installed
- Python 3.12+ (if running outside Docker)
- Stable internet connection
- Port access (4001, 4002, 5900)

## IBKR Account Setup

### 1. Enable API Access
1. Log into IBKR Account Management
2. Go to Settings → API → Settings
3. Enable "Enable ActiveX and Socket Clients"
4. Set "Socket port" to 7496 (live) or 7497 (paper)
5. Optional: Configure "Master API client ID" restrictions

### 2. Market Data Permissions
- **Free**: Delayed data (15-minute delay)
- **Paid**: Real-time data (requires subscriptions)
- Configure in Account Management → Market Data Subscriptions

### 3. Trading Permissions
- Ensure your account has permissions for desired instruments
- Stocks, ETFs, and Forex typically included
- Options and Futures may require separate permissions

## Docker Gateway Setup

### Method 1: Using Docker Compose (Recommended)

1. **Copy environment template:**
```bash
cp .env.example .env
```

2. **Configure IBKR settings in `.env`:**
```bash
# Set broker type
BROKER=ibkr

# IBKR Gateway credentials
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password
GATEWAY_TRADING_MODE=paper  # or 'live'

# IBKR connection settings
IBKR_HOST=ib-gateway  # Docker service name
IBKR_PORT=4002        # 4001 for live, 4002 for paper
IBKR_ACCOUNT_TYPE=paper
IBKR_CLIENT_ID=1

# Trading configuration
SYMBOLS=AAPL,TSLA,SPY  # Stock symbols
STRATEGY_NAME=test
INITIAL_CAPITAL=100000.0
```

3. **Start services:**
```bash
docker-compose --profile ibkr up -d
```

### Method 2: Manual IB Gateway

1. **Start IB Gateway container:**
```bash
docker run -d --name ib-gateway \
  -e TWS_USERID=your_username \
  -e TWS_PASSWORD=your_password \
  -e TRADING_MODE=paper \
  -p 127.0.0.1:4001:4001 \
  -p 127.0.0.1:4002:4002 \
  -p 127.0.0.1:5900:5900 \
  ghcr.io/gnzsnz/ib-gateway:stable
```

2. **Configure trading bot:**
```bash
# Set connection to localhost
IBKR_HOST=127.0.0.1
IBKR_PORT=4002  # Paper trading port
```

## Configuration

### Environment Variables

#### Core IBKR Settings
```bash
# Broker selection
BROKER=ibkr

# Connection settings
IBKR_HOST=127.0.0.1     # or 'ib-gateway' for Docker
IBKR_PORT=4002          # 4001=live, 4002=paper, 7496=TWS live, 7497=TWS paper
IBKR_CLIENT_ID=1        # Unique client ID (0-32)
IBKR_ACCOUNT_TYPE=paper # 'paper' or 'live'
IBKR_ACCOUNT_ID=        # Optional: specific account ID

# Market data type
IBKR_MARKET_DATA_TYPE=3 # 1=live, 2=frozen, 3=delayed, 4=delayed_frozen

# Connection management
IBKR_CONNECT_TIMEOUT=10
IBKR_AUTO_RECONNECT=true
IBKR_MAX_RECONNECT_ATTEMPTS=5
```

#### Gateway Docker Settings (Optional)
```bash
# IB Gateway credentials
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password
GATEWAY_TRADING_MODE=paper  # 'paper' or 'live'
VNC_SERVER_PASSWORD=        # Optional VNC access
```

#### Trading Configuration
```bash
# Trading symbols (stocks, ETFs, forex)
SYMBOLS=AAPL,TSLA,SPY,EUR.USD

# Strategy selection
STRATEGY_NAME=sma  # or breakout, fvg, etc.

# Risk management
RISK_MANAGER_TYPE=fixed_risk
RISK_PERCENT=0.01           # 1% risk per trade
INITIAL_CAPITAL=100000.0
```

### Supported Instruments

#### Stocks and ETFs
```bash
SYMBOLS=AAPL,TSLA,SPY,QQQ,IWM
```

#### Forex Pairs
```bash
SYMBOLS=EUR.USD,GBP.USD,USD.JPY,AUD.USD
```

#### Mixed Portfolio
```bash
SYMBOLS=AAPL,SPY,EUR.USD,QQQ
```

## Running IBKR Trading

### Docker Method (Recommended)

1. **Start with logs:**
```bash
docker-compose --profile ibkr up
```

2. **Start in background:**
```bash
docker-compose --profile ibkr up -d
```

3. **View logs:**
```bash
docker-compose logs -f trading_bot
```

4. **Stop services:**
```bash
docker-compose down
```

### Direct Python Method

1. **Install dependencies:**
```bash
uv sync
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your IBKR settings
```

3. **Run trading bot:**
```bash
uv run python main.py
```

### Connection Test

Test IBKR connection before trading:

```python
import asyncio
from framework.execution.ibkr.ibkr_config import IBKRConfig
from framework.execution.ibkr.ibkr_connection import test_connection

async def test():
    config = IBKRConfig.from_env()
    success = await test_connection(config)
    print(f"Connection test: {'SUCCESS' if success else 'FAILED'}")

asyncio.run(test())
```

## Troubleshooting

### Common Issues

#### Connection Refused
```
Error: Connection refused to 127.0.0.1:4002
```
**Solutions:**
- Ensure IB Gateway is running
- Check port configuration (4001/4002 vs 7496/7497)
- Verify firewall settings
- Wait for Gateway startup (can take 1-2 minutes)

#### Authentication Failed
```
Error: Authentication failed
```
**Solutions:**
- Verify TWS_USERID and TWS_PASSWORD
- Check account status in IBKR Account Management
- Ensure API access is enabled
- Try paper trading first

#### Market Data Issues
```
Warning: No market data for AAPL
```
**Solutions:**
- Check market hours (US stocks trade 9:30-16:00 ET)
- Verify instrument symbol format
- Use delayed data type (IBKR_MARKET_DATA_TYPE=3)
- Check market data subscriptions

#### Order Rejected
```
Error: Order rejected - insufficient buying power
```
**Solutions:**
- Check account balance
- Reduce position size
- Verify trading permissions for instrument
- Check margin requirements

### Debug Mode

Enable detailed logging:

```bash
LOG_LEVEL=DEBUG
```

### Health Checks

Monitor services:

```bash
# Check Gateway health
docker exec ib-gateway netstat -an | grep 4002

# Check trading bot status
docker logs trading-bot --tail 50

# Check PostgreSQL connection
docker exec trading-postgres pg_isready
```

## Security Considerations

### Credential Management
- **Never** commit credentials to version control
- Use `.env` file for local development
- Use Docker secrets for production
- Rotate passwords regularly

### Network Security
- Bind ports to localhost only (`127.0.0.1:4002`)
- Use SSH tunneling for remote access
- Consider VPN for cloud deployments
- Monitor access logs

### Account Safety
- Start with paper trading
- Use position limits and stop losses
- Monitor daily P&L limits
- Set up alerts for unusual activity

### Production Deployment
```bash
# Use secrets for credentials
echo "your_password" | docker secret create ibkr_password -

# Bind to localhost only
ports:
  - "127.0.0.1:4002:4002"

# Use read-only filesystem
read_only: true
tmpfs:
  - /tmp
  - /var/tmp
```

## VNC Access (Optional)

Access Gateway GUI remotely:

1. **Enable VNC:**
```bash
VNC_SERVER_PASSWORD=your_vnc_password
```

2. **Connect:**
- Host: `localhost:5900`
- Password: your_vnc_password
- Use VNC viewer (TigerVNC, RealVNC, etc.)

3. **Security:**
- Only enable for debugging
- Use strong password
- Consider SSH tunneling

## Advanced Configuration

### Multiple Client IDs
Run multiple strategies by scaling the trading bot service:

```bash
# Scale to multiple instances with different client IDs
docker-compose --profile ibkr up --scale trading_bot=2

# Or create additional services in docker-compose.yml:
# trading-bot-2:
#   extends: trading_bot
#   environment:
#     - IBKR_CLIENT_ID=2
#     - STRATEGY_NAME=breakout
```

### Custom Gateway Image
Build with additional tools:

```dockerfile
FROM ghcr.io/gnzsnz/ib-gateway:stable
RUN apt-get update && apt-get install -y your-tools
```

### High Frequency Trading
Optimize for speed:

```bash
# Reduce API delays
IBKR_MAX_REQUESTS_PER_SECOND=100
IBKR_CONNECT_TIMEOUT=5

# Use live data
IBKR_MARKET_DATA_TYPE=1

# Shorter timeframes
TIMEFRAME=1m
```

## Support

- **Framework Issues**: Create issue on GitHub repository
- **IBKR Gateway**: https://github.com/gnzsnz/ib-gateway-docker
- **Interactive Brokers**: IBKR Client Portal support
- **ib_async Library**: https://github.com/erdewit/ib_async

---

**⚠️ Risk Warning**: Trading involves substantial risk. Start with paper trading and never risk more than you can afford to lose. This software is provided as-is without warranties.