# Trading Framework

A comprehensive Python framework for algorithmic trading strategy development, backtesting, and analysis.

## Features

- **Strategy Development**: Modular architecture with abstract base classes for consistent strategy implementation
- **Backtesting Engine**: Comprehensive backtesting with risk management integration and performance metrics
- **Live Trading Support**: 
  - **CCXT**: Cryptocurrency exchanges (Binance, Coinbase, Kraken, etc.)
  - **IBKR**: Interactive Brokers for stocks, ETFs, forex, and futures
  - **Paper Trading**: Risk-free testing with real market data
- **Data Management**: Support for multiple data sources (Yahoo Finance, CCXT exchanges, Interactive Brokers)
- **Risk Management**: Built-in position sizing, stop-loss, and portfolio risk controls
- **Performance Analysis**: Detailed metrics including Sharpe ratio, maximum drawdown, and win rates
- **Docker Integration**: Containerized deployment with IB Gateway support

## Installation

### 1. Install uv (Modern Python Package Manager)

```bash
# On macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternative: using pip
pip install uv
```

### 2. Install Dependencies

```bash
# Clone the repository
git clone https://github.com/pecan987/trading-bot-framework.git
cd trading-bot-framework

# Install all dependencies with uv (creates virtual environment automatically)
uv sync

# Activate the virtual environment
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate   # On Windows

# Install development dependencies (optional)
uv sync --extra dev
```

### Requirements
- Python >= 3.12.3
- All dependencies are managed via `pyproject.toml`

## Quick Start

### Download Data
```bash
# Download stock data
python scripts/download_data.py --source yahoo --symbol AAPL --start 2023-01-01

# Download crypto data
python scripts/download_data.py --source ccxt --symbol BTC/USDT --exchange binance
```

### Run Backtest
```bash
# Basic backtest
uv run python scripts/run_backtest.py --strategy sma --data-file data/cleaned/BTC_USDT.csv --symbol BTC_USDT

# With custom parameters
STRATEGY_PARAMS='{"short_window": 10, "long_window": 20, "position_size": 0.1}' \
uv run python scripts/run_backtest.py --strategy sma --data-file data/cleaned/BTC_USDT.csv --symbol BTC_USDT
```

## Architecture

- `framework/strategies/` - Trading strategy implementations
- `framework/backtesting/` - Backtesting engine and results
- `framework/data/` - Data sources and preprocessing
- `framework/risk/` - Risk management system
- `scripts/` - Utility scripts for data download and backtesting
- `tests/` - Comprehensive test suite

## Documentation

### Comprehensive Guides

- **[Data Downloading](docs/DATA_DOWNLOADING.md)**: Complete guide for downloading financial data from multiple sources (Yahoo Finance, CCXT exchanges)
- **[Data Preprocessing](docs/DATA_PREPROCESS.md)**: Data cleaning, validation, and feature engineering pipeline
- **[Backtesting](docs/BACKTEST.md)**: Professional backtesting with risk management and performance analysis
- **[Development Guide](CLAUDE.md)**: Developer instructions and framework architecture details

### Key Features Covered

- **Multi-Source Data**: Yahoo Finance (stocks, ETFs) and CCXT (cryptocurrency exchanges)
- **Data Quality**: Automated validation, cleaning, and gap filling
- **Professional Backtesting**: Industry-standard metrics with `backtesting.py` integration
- **Risk Management**: Built-in stop loss, take profit, and position sizing
- **Strategy Development**: Extensible framework for custom trading strategies

## Broker Support

### Cryptocurrency Exchanges (CCXT)
Supports 100+ cryptocurrency exchanges through CCXT:
- **Binance**, **Coinbase**, **Kraken**, **Bybit**, **OKX**, etc.
- Paper trading with real market data
- Live trading with API keys

### Interactive Brokers (IBKR) 
Professional broker for traditional assets:
- **Stocks**, **ETFs**, **Forex**, **Futures**, **Options**
- Paper trading and live trading
- Integrated with IB Gateway Docker for easy deployment
- See [IBKR Integration Guide](docs/IBKR_INTEGRATION.md) for setup

### Quick Broker Setup

#### CCXT Paper Trading (Recommended for beginners)
```bash
# Copy environment template
cp .env.example .env

# Edit .env file:
BROKER=paper_ccxt
EXCHANGE_NAME=binance
SYMBOLS=BTC/USDT:USDT
STRATEGY_NAME=test

# Run trading bot
uv run python main.py
```

#### IBKR Trading (Advanced)
```bash
# 1. Set up IB Gateway with Docker
cp .env.example .env

# 2. Configure IBKR settings in .env:
BROKER=ibkr
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password
SYMBOLS=AAPL,SPY,EUR.USD
IBKR_ACCOUNT_TYPE=paper

# 3. Start with IBKR profile (includes IB Gateway)
docker-compose --profile ibkr up

# See docs/IBKR_INTEGRATION.md for detailed setup
```

## Testing

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=framework

# Test IBKR integration
python simple_ibkr_test.py
```

## Contributing

See `CLAUDE.md` for detailed development guidance and framework architecture.