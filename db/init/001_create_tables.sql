-- Create database schema for trading bot
-- Stores trades, positions, and performance metrics

-- Create enum types for trade side and status
CREATE TYPE trade_side AS ENUM ('buy', 'sell', 'long', 'short');
CREATE TYPE trade_status AS ENUM ('pending', 'filled', 'cancelled', 'rejected', 'expired');
CREATE TYPE position_status AS ENUM ('open', 'closed', 'liquidated');

-- Trades table - stores all executed trades
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(255) UNIQUE,
    symbol VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    side trade_side NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    fee DECIMAL(20, 8) DEFAULT 0,
    fee_currency VARCHAR(10),
    status trade_status NOT NULL DEFAULT 'pending',
    order_type VARCHAR(50),
    stop_loss DECIMAL(20, 8),
    take_profit DECIMAL(20, 8),
    executed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Positions table - tracks open and closed positions
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    position_id VARCHAR(255) UNIQUE,
    symbol VARCHAR(50) NOT NULL,
    strategy VARCHAR(100),
    side trade_side NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    exit_price DECIMAL(20, 8),
    quantity DECIMAL(20, 8) NOT NULL,
    realized_pnl DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8),
    status position_status NOT NULL DEFAULT 'open',
    stop_loss DECIMAL(20, 8),
    take_profit DECIMAL(20, 8),
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Balance snapshots - track account balance over time
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(100),
    total_balance DECIMAL(20, 8) NOT NULL,
    free_balance DECIMAL(20, 8) NOT NULL,
    used_balance DECIMAL(20, 8) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    snapshot_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Performance metrics - aggregated trading performance
CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    strategy VARCHAR(100),
    symbol VARCHAR(50),
    metric_date DATE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl DECIMAL(20, 8) DEFAULT 0,
    win_rate DECIMAL(5, 4),
    average_win DECIMAL(20, 8),
    average_loss DECIMAL(20, 8),
    profit_factor DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(20, 8),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    UNIQUE(strategy, symbol, metric_date)
);

-- API metrics - track API latency and performance
CREATE TABLE IF NOT EXISTS api_metrics (
    id SERIAL PRIMARY KEY,
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(50) NOT NULL,
    latency_ms DECIMAL(10, 3) NOT NULL,
    status_code INTEGER,
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Alerts table - store trading alerts and notifications
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    symbol VARCHAR(50),
    strategy VARCHAR(100),
    triggered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes for better query performance
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_strategy ON trades(strategy);
CREATE INDEX idx_trades_executed_at ON trades(executed_at);
CREATE INDEX idx_trades_status ON trades(status);

CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_strategy ON positions(strategy);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_opened_at ON positions(opened_at);

CREATE INDEX idx_balance_snapshots_account ON balance_snapshots(account_id);
CREATE INDEX idx_balance_snapshots_time ON balance_snapshots(snapshot_time);

CREATE INDEX idx_performance_metrics_date ON performance_metrics(metric_date);
CREATE INDEX idx_performance_metrics_strategy_symbol ON performance_metrics(strategy, symbol);

CREATE INDEX idx_api_metrics_endpoint ON api_metrics(endpoint);
CREATE INDEX idx_api_metrics_timestamp ON api_metrics(timestamp);

CREATE INDEX idx_alerts_type ON alerts(alert_type);
CREATE INDEX idx_alerts_triggered ON alerts(triggered_at);
CREATE INDEX idx_alerts_acknowledged ON alerts(acknowledged);

-- Create update trigger for updated_at columns
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS trading;

-- Trading state table - stores all trading bot state
CREATE TABLE IF NOT EXISTS trading.trading_state (
    id SERIAL PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    state_type VARCHAR(50) NOT NULL,  -- 'positions', 'orders', 'daily_pnl', 'checkpoint'
    state_key VARCHAR(255) NOT NULL,   -- symbol for positions, order_id for orders, date for pnl
    state_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instance_id, exchange, state_type, state_key)
);

-- Trading locks table - for distributed lock management
CREATE TABLE IF NOT EXISTS trading.trading_locks (
    lock_id VARCHAR(255) PRIMARY KEY,
    instance_id VARCHAR(255) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    acquired_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Create indexes for trading state
CREATE INDEX idx_trading_state_instance ON trading.trading_state(instance_id);
CREATE INDEX idx_trading_state_exchange ON trading.trading_state(exchange);
CREATE INDEX idx_trading_state_type ON trading.trading_state(state_type);
CREATE INDEX idx_trading_state_updated ON trading.trading_state(updated_at);

-- Create index for trading locks
CREATE INDEX idx_trading_locks_expires ON trading.trading_locks(expires_at);

-- Create update trigger for trading_state updated_at column
CREATE TRIGGER update_trading_state_updated_at BEFORE UPDATE ON trading.trading_state
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions to the trading user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO trading_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO trading_user;
GRANT ALL PRIVILEGES ON SCHEMA trading TO trading_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA trading TO trading_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA trading TO trading_user;
