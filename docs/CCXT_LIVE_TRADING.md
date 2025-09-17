# CCXT Live Trading Guide

## ⚠️ WARNING

**LIVE TRADING INVOLVES REAL MONEY AND REAL RISK**

- You can lose your entire investment
- Start with minimal capital you can afford to lose
- Test thoroughly in paper trading first
- Never trade with borrowed money
- Past performance doesn't guarantee future results

## Prerequisites

Before starting live trading:

✅ **Successful paper trading** for at least 2-4 weeks  
✅ **Consistent profitable results** in paper trading  
✅ **Understanding of the strategy** you're using  
✅ **Risk management plan** in place  
✅ **Exchange account** with API access enabled  
✅ **Small test capital** to start (recommend $100-500)

## Setting Up Live Trading

### Step 1: Get Exchange API Keys

#### Binance
1. Log into [Binance](https://www.binance.com)
2. Go to Account → API Management
3. Create new API key with label "Trading Bot"
4. **Important Security Settings**:
   - Enable **Spot & Margin Trading**
   - Enable **Futures** (if trading futures)
   - Restrict IP access to your server IP
   - Never enable withdrawals
5. Save API Key and Secret securely

#### Other Exchanges
- **Kraken**: Account → Security → API
- **Coinbase**: Settings → API → New API Key
- **Bybit**: Account & Security → API Management

### Step 2: Configure for Live Trading

Create a new configuration file for live trading:
```bash
cp .env.example .env.live
```

Edit `.env.live`:
```bash
# LIVE TRADING CONFIGURATION
DATA_SOURCE=ccxt
EXCHANGE_NAME=binance
USE_SANDBOX=false  # IMPORTANT: false for real trading

# Your real API credentials
EXCHANGE_API_KEY=your_real_api_key_here
EXCHANGE_API_SECRET=your_real_api_secret_here

# Start with small capital
INITIAL_CAPITAL=500.0

# Conservative risk settings
MAX_POSITION_SIZE=0.05  # Only 5% per trade

# Your tested strategy
STRATEGY_NAME=sma

# Production logging
LOG_LEVEL=INFO
USE_JSON_LOGS=true
```

### Step 3: Switch from Paper to Live

To use the live configuration:
```bash
# Method 1: Use specific env file
cp .env.live .env
python main.py

# Method 2: Export directly
export EXCHANGE_API_KEY="your_key"
export EXCHANGE_API_SECRET="your_secret"
python main.py
```

### Step 4: Modify main.py for Live Trading

Change the trader initialization in `main.py`:

```python
# For LIVE trading - use CCXTTrader
from framework.live.execution.ccxt_trader import CCXTTrader
trader = CCXTTrader(config)

# Instead of paper trader:
# from framework.live.execution.ccxt_paper_trader import CCXTPaperTrader
# trader = CCXTPaperTrader(config)
```

## Live Trading Configuration

### Essential Settings

```bash
# Exchange Configuration
EXCHANGE_NAME=binance         # Your exchange
TRADING_TYPE=future           # 'spot' or 'future'
SYMBOLS=BTC/USDT:USDT        # Trading pairs

# Risk Management (CRITICAL)
INITIAL_CAPITAL=500.0         # Your actual capital
MAX_POSITION_SIZE=0.05        # Max 5% per trade
STOP_LOSS_PCT=0.02           # 2% stop loss
MAX_DAILY_LOSS=0.05          # Stop trading after 5% daily loss

# Execution Settings
COMMISSION=0.001             # Exchange commission rate
SLIPPAGE=0.0005             # Expected slippage
ALLOW_SHORT=false           # Enable short selling (futures only)
```

### Strategy Selection

Choose based on your paper trading results:

```bash
# Conservative - SMA Strategy
STRATEGY_NAME=sma
# Good for: Trending markets, beginners

# Aggressive - Breakout Strategy  
STRATEGY_NAME=breakout
# Good for: Volatile markets, experienced traders

# Statistical - Mean Reversion
STRATEGY_NAME=mean_reversion
# Good for: Range-bound markets, quant traders
```

## Safety Features

### 1. Position Sizing
The system automatically calculates safe position sizes:
- Never risks more than configured `MAX_POSITION_SIZE`
- Accounts for leverage if using futures
- Adjusts for available balance

### 2. Emergency Stop
Trading halts automatically when:
- Daily loss exceeds limit (default 2%)
- Connection issues persist
- Invalid market conditions detected

### 3. State Management
- Positions tracked in database
- Recovery from disconnections
- Prevents duplicate orders

### 4. Risk Controls
```python
# In ccxt_trader.py
self.daily_loss_limit = config.initial_capital * 0.02  # 2% max daily loss
self.max_position_pct = config.max_position_size       # Position limit
self.emergency_stop = False                            # Circuit breaker
```

## Monitoring Live Trading

### Real-time Monitoring
```bash
# Watch logs in real-time
tail -f logs/trading_bot_*.log

# Monitor specific events
tail -f logs/trading_bot_*.log | grep -E "(BUY|SELL|P&L)"
```

### Performance Metrics
The system tracks:
- **Current positions**: Size, entry price, P&L
- **Daily P&L**: Today's profit/loss
- **Total P&L**: Cumulative results
- **Win rate**: Success percentage
- **Emergency stops**: Safety triggers

### Database Monitoring
If using PostgreSQL:
```sql
-- Check recent trades
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;

-- View current positions
SELECT * FROM positions WHERE is_open = true;

-- Daily performance
SELECT date, SUM(pnl) as daily_pnl 
FROM trades 
GROUP BY date 
ORDER BY date DESC;
```

## Best Practices

### 1. Start Small
- Begin with $100-500 maximum
- Use minimum position sizes (0.01 BTC)
- Trade only one pair initially
- Increase gradually with success

### 2. Risk Management
- **Never risk more than 1-2% per trade**
- Use stop losses on every position
- Don't average down on losses
- Take profits regularly

### 3. Operational Safety
- Run on reliable VPS/cloud server
- Use systemd/supervisor for auto-restart
- Enable exchange IP whitelist
- Regular backup of state files
- Monitor system health

### 4. Continuous Improvement
- Log every trade for analysis
- Review performance weekly
- Adjust strategy parameters carefully
- Keep paper trading new ideas

## Deployment

### VPS Deployment
```bash
# On Ubuntu/Debian VPS
# Install dependencies
sudo apt update
sudo apt install python3.12 python3-pip git

# Clone and setup
git clone <your-repo>
cd robotdreams-trading-fw
pip install -r requirements.txt

# Configure
cp .env.live .env
nano .env  # Add your API keys

# Run with screen/tmux
screen -S trading
python main.py
# Detach: Ctrl+A, D
```

### Docker Deployment
```bash
# Build image
docker build -t trading-bot .

# Run container
docker run -d \
  --name trading-bot \
  --restart=unless-stopped \
  -e EXCHANGE_API_KEY=$EXCHANGE_API_KEY \
  -e EXCHANGE_API_SECRET=$EXCHANGE_API_SECRET \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/trading_state:/app/trading_state \
  trading-bot
```

### Systemd Service
Create `/etc/systemd/system/trading-bot.service`:
```ini
[Unit]
Description=Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/robotdreams-trading-fw
ExecStart=/usr/bin/python3 /home/ubuntu/robotdreams-trading-fw/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

## Troubleshooting

### API Key Issues
- Verify API key has trading permissions
- Check IP whitelist if configured
- Ensure futures enabled for futures trading
- Test with small market order first

### Connection Problems
- Check exchange status page
- Verify network connectivity
- Increase timeout settings
- Use different exchange endpoint

### Order Failures
- Insufficient balance
- Minimum order size not met
- Market closed/halted
- Rate limits exceeded

### Performance Issues
- Reduce position sizes
- Increase timeframe (5m → 15m)
- Optimize strategy parameters
- Check latency to exchange

## Emergency Procedures

### Stop Trading Immediately
```bash
# Method 1: Kill process
pkill -f "python main.py"

# Method 2: Create emergency stop file
touch EMERGENCY_STOP

# Method 3: Set environment variable
export EMERGENCY_STOP=true
```

### Close All Positions
```python
# Add to main.py for emergency close
if os.path.exists("CLOSE_ALL_POSITIONS"):
    trader.close_all_positions()
    sys.exit(0)
```

### Disable API Keys
1. Log into exchange immediately
2. Disable/delete API keys
3. Review all positions
4. Close manually if needed

## Legal and Tax Considerations

- **Keep detailed records** of all trades
- **Understand tax obligations** in your jurisdiction
- **Comply with regulations** for your country
- **Consider business structure** for larger operations
- **Consult professionals** for tax/legal advice

## Final Checklist

Before going live, confirm:

- [ ] Paper traded successfully for 2+ weeks
- [ ] Achieved consistent profits in paper trading
- [ ] Understand the strategy completely
- [ ] Have risk management plan
- [ ] API keys configured correctly
- [ ] Using minimal test capital
- [ ] Monitoring system in place
- [ ] Emergency procedures understood
- [ ] Backup and recovery plan ready
- [ ] Accepted the risks involved

## Support and Resources

- Exchange API Documentation
- CCXT Documentation: https://docs.ccxt.com
- Strategy discussions: GitHub Issues
- Risk management: Read "Trading in the Zone"

Remember: **Start small, trade responsibly, and never risk more than you can afford to lose!**