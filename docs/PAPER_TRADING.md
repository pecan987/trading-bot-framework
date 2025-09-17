# Paper Trading Guide

## Overview

Paper trading allows you to test your strategies with real market data but using virtual money. This is the **safest way** to develop and test trading strategies before risking real capital.

## Features

- ✅ **Real market data** from live exchanges
- ✅ **Virtual portfolio** with $10,000 starting capital (configurable)
- ✅ **Realistic simulation** including commission and slippage
- ✅ **State persistence** - continue where you left off
- ✅ **Performance tracking** - monitor P&L, positions, and metrics
- ✅ **No API keys required** for public market data
- ✅ **Risk-free testing** - no real money at risk

## Quick Start

### 1. Setup Environment

Copy the example configuration:
```bash
cp .env.example .env
```

### 2. Configure Settings

Edit `.env` file with your preferences:

```bash
# Choose broker type
BROKER=paper_ccxt

# Use real market data (recommended)
USE_SANDBOX=false

# Choose your exchange
EXCHANGE_NAME=binance

# Select trading pair
SYMBOLS=BTC/USDT:USDT

# Set timeframe (1m for quick testing)
TIMEFRAME=1m

# Choose strategy
STRATEGY_NAME=sma

# Set virtual capital
INITIAL_CAPITAL=10000.0

# No API keys needed for paper trading!
EXCHANGE_API_KEY=
EXCHANGE_API_SECRET=
```

### 3. Run Paper Trading

```bash
python main.py
```

## How It Works

### Virtual Portfolio

The paper trader maintains a virtual portfolio that simulates real trading:

- **Starting balance**: Configured via `INITIAL_CAPITAL` (default $10,000)
- **Position tracking**: Simulated positions with entry prices
- **P&L calculation**: Real-time unrealized and realized P&L
- **Commission**: 0.1% per trade (configurable)
- **Slippage**: 0.05% market impact simulation

### State Persistence

Trading state is saved in the `trading_state/` directory:
- `BINANCE_positions.json` - Current positions
- `BINANCE_orders.json` - Order history
- `BINANCE_pnl.json` - Daily P&L tracking
- `BINANCE_checkpoint.json` - Full state backup

This allows you to:
- Stop and resume trading sessions
- Track performance over multiple days
- Analyze historical trades

### Trading Logic

1. **Market Data**: Fetches real OHLCV data from the exchange
2. **Signal Generation**: Your strategy analyzes data and generates signals
3. **Order Simulation**: Paper trader simulates order execution
4. **Portfolio Update**: Virtual balance and positions are updated
5. **Performance Tracking**: Metrics are calculated and logged

## Available Strategies

### SMA Strategy
Simple Moving Average crossover strategy:
- Long when short MA crosses above long MA
- Exit when short MA crosses below long MA

```bash
STRATEGY_NAME=sma
```

### Breakout Strategy
Trades breakouts with momentum confirmation:
- Enters on price breakouts with volume
- Uses ATR-based stops

```bash
STRATEGY_NAME=breakout
```

### Mean Reversion Strategy
Statistical arbitrage strategy:
- Trades when price deviates from mean
- Uses Z-score and RSI filters

```bash
STRATEGY_NAME=mean_reversion
```

### FVG Strategy
Fair Value Gap strategy:
- Multi-timeframe analysis
- Trades imbalances in price action

```bash
STRATEGY_NAME=fvg
```

## Performance Monitoring

### Console Output

The bot provides real-time feedback:
```
[11:58:05] Current market data - BTC/USDT:USDT $116,197 | Signal: 0 | Balance: $10,000
[11:58:05] Performance summary - P&L: $0 | Positions: 0 | Mode: PAPER
[11:58:05] 💤 Sleeping 55s until next 1m candle...
```

### Trade Notifications

When trades are executed:
```
🟢 PAPER BOUGHT 0.008607 BTC/USDT:USDT @ $116,234.50 (Commission: $1.00)
🔴 PAPER SOLD 0.008607 BTC/USDT:USDT @ $116,450.25 P&L: 💰 $1.86 (Commission: $1.00)
```

### Performance Metrics

- **Daily P&L**: Today's profit/loss
- **Total P&L**: All-time profit/loss
- **Realized P&L**: Closed position profits
- **Unrealized P&L**: Open position profits
- **Win Rate**: Percentage of profitable trades
- **Balance**: Current virtual account balance

## Tips for Effective Paper Trading

### 1. Start Small
- Use realistic position sizes (1-10% of portfolio)
- Don't overtrade - quality over quantity
- Respect risk management rules

### 2. Test Systematically
- Run each strategy for at least 100 trades
- Test in different market conditions
- Document what works and what doesn't

### 3. Use Fast Timeframes for Testing
- 1m timeframe for quick iteration
- 5m or 15m for more realistic signals
- 1h or 4h for swing trading strategies

### 4. Monitor Performance
- Track daily P&L trends
- Analyze losing trades for patterns
- Adjust strategy parameters based on results

### 5. Gradual Transition to Live
- Paper trade for at least 2-4 weeks
- Achieve consistent profitability
- Start live trading with minimal capital
- Scale up gradually as confidence grows

## Troubleshooting

### No signals generated
- Check if market is open
- Ensure sufficient data bars for strategy
- Verify strategy parameters

### Connection errors
- Check internet connection
- Verify exchange is accessible
- Try different exchange if issues persist

### State not persisting
- Ensure `trading_state/` directory exists
- Check file permissions
- Clean state files if corrupted

## Safety Features

- **Emergency Stop**: Automatic halt on 2% daily loss
- **Position Limits**: Maximum position size enforcement
- **State Validation**: Consistency checks on startup
- **Lock Files**: Prevents multiple instances

## Next Steps

Once comfortable with paper trading results:
1. Review the [Live Trading Guide](CCXT_LIVE_TRADING.md)
2. Get exchange API keys
3. Start with minimal capital
4. Scale gradually with success

Remember: **Paper trading success doesn't guarantee live trading success**, but it's an essential step in developing a profitable strategy!