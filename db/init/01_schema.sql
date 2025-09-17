-- Trading Bot Database Schema
-- Supports multiple brokers (CCXT, IBKR, etc.)

-- Create schema
CREATE SCHEMA IF NOT EXISTS trading;

-- Set default schema
SET search_path TO trading, public;

-- Trades table - record of all executed trades
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    strategy VARCHAR(100) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    commission DECIMAL(20, 8) DEFAULT 0,
    pnl DECIMAL(20, 8),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    broker_trade_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Positions table - current open positions
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    avg_entry_price DECIMAL(20, 8) NOT NULL,
    current_price DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8),
    realized_pnl DECIMAL(20, 8) DEFAULT 0,
    is_open BOOLEAN DEFAULT true,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(broker, symbol, is_open) WHERE is_open = true
);

-- Orders table - all order attempts
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    broker_order_id VARCHAR(255),
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8),
    stop_price DECIMAL(20, 8),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'submitted', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')),
    filled_quantity DECIMAL(20, 8) DEFAULT 0,
    avg_fill_price DECIMAL(20, 8),
    commission DECIMAL(20, 8) DEFAULT 0,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio snapshots - track portfolio value over time
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    total_value DECIMAL(20, 8) NOT NULL,
    cash_balance DECIMAL(20, 8) NOT NULL,
    positions_value DECIMAL(20, 8) NOT NULL,
    daily_pnl DECIMAL(20, 8),
    total_pnl DECIMAL(20, 8),
    metadata JSONB
);

-- Broker configuration and status
CREATE TABLE IF NOT EXISTS broker_status (
    broker VARCHAR(50) PRIMARY KEY,
    is_active BOOLEAN DEFAULT false,
    is_paper_trading BOOLEAN DEFAULT true,
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    connection_status VARCHAR(50),
    error_message TEXT,
    config JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Strategy state - for storing strategy-specific state
CREATE TABLE IF NOT EXISTS strategy_state (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    strategy VARCHAR(100) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    state_key VARCHAR(255) NOT NULL,
    state_value JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(broker, strategy, symbol, state_key)
);

-- Performance metrics - calculated periodically
CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    broker VARCHAR(50) NOT NULL,
    strategy VARCHAR(100) NOT NULL,
    period VARCHAR(20) NOT NULL, -- 'daily', 'weekly', 'monthly', 'all_time'
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_return DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    win_rate DECIMAL(10, 4),
    profit_factor DECIMAL(10, 4),
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    avg_win DECIMAL(20, 8),
    avg_loss DECIMAL(20, 8),
    largest_win DECIMAL(20, 8),
    largest_loss DECIMAL(20, 8),
    metadata JSONB,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(broker, strategy, period, end_date)
);

-- Create indexes for better query performance
CREATE INDEX idx_trades_broker_symbol ON trades(broker, symbol);
CREATE INDEX idx_trades_timestamp ON trades(timestamp DESC);
CREATE INDEX idx_trades_strategy ON trades(strategy);

CREATE INDEX idx_positions_broker_symbol ON positions(broker, symbol);
CREATE INDEX idx_positions_is_open ON positions(is_open) WHERE is_open = true;

CREATE INDEX idx_orders_broker_symbol ON orders(broker, symbol);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);

CREATE INDEX idx_portfolio_snapshots_broker_timestamp ON portfolio_snapshots(broker, timestamp DESC);

CREATE INDEX idx_performance_metrics_broker_strategy ON performance_metrics(broker, strategy);

-- Create update trigger for updated_at columns
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_broker_status_updated_at BEFORE UPDATE ON broker_status
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions (adjust as needed)
GRANT ALL PRIVILEGES ON SCHEMA trading TO trading_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA trading TO trading_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA trading TO trading_user;