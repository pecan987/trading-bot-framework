# PostgreSQL State Store Migration Guide

## Overview
The trading framework now uses PostgreSQL as the primary state store instead of file-based storage in `trading_state/*`. This provides better reliability, concurrent access support, and centralized state management.

## Key Changes

### 1. State Storage Location
- **Before**: Files in `trading_state/` directory
- **After**: PostgreSQL database tables in `trading.trading_state` schema

### 2. Automatic Fallback
All traders (CCXT, IBKR, Paper) now attempt to use PostgreSQL first and automatically fallback to file storage if the database is unavailable:

```python
# Automatic in all traders - no code changes needed
try:
    state_store = PostgreSQLStateStore(...)  # Primary
except:
    state_store = SimpleStateStore(...)      # Fallback
```

### 3. Database Schema
The following tables are created for state management:

- `trading.trading_state` - Stores positions, orders, checkpoints, and PnL data
- `trading.trading_locks` - Distributed lock management
- `trades` - Trade execution history
- `positions` - Position tracking with PnL
- `balance_snapshots` - Account balance over time
- `performance_metrics` - Aggregated performance data

## Migration Steps

### 1. Start PostgreSQL Service
```bash
docker-compose up -d postgres
```

### 2. Verify Database Schema
The schema is automatically created from `db/init/001_create_tables.sql` on first startup.

```bash
docker-compose exec postgres psql -U trading_user -d trading -c "\dt trading.*"
```

### 3. Run Trading Bot
No code changes required. The bot will automatically use PostgreSQL if available:

```bash
# Paper trading
python scripts/run_paper_trading.py

# Live trading
python scripts/run_live_trading.py
```

## Configuration

### Environment Variables
Set in `.env` file:
```env
DB_HOST=postgres       # or localhost if running outside Docker
DB_PORT=5432
DB_NAME=trading
DB_USER=trading_user
DB_PASSWORD=trading_password
DB_SCHEMA=trading
```

### Docker Compose
All services are configured to use the PostgreSQL state store:
```yaml
trading_bot:
  environment:
    - DB_HOST=postgres
    - DB_PORT=5432
    - DB_NAME=${DB_NAME:-trading}
    - DB_USER=${DB_USER:-trading_user}
    - DB_PASSWORD=${DB_PASSWORD:-trading_password}
```

## Data Migration (Optional)

If you have existing state in `trading_state/*` files and want to migrate to PostgreSQL:

```python
# Manual migration script example
import json
import os
from framework.utils.postgres_state_store import PostgreSQLStateStore

# Initialize PostgreSQL store
pg_store = PostgreSQLStateStore(exchange="YOUR_EXCHANGE")

# Migrate positions
if os.path.exists("trading_state/YOUR_EXCHANGE_positions.json"):
    with open("trading_state/YOUR_EXCHANGE_positions.json", "r") as f:
        positions = json.load(f)
        pg_store.save_positions(positions)

# Migrate orders
if os.path.exists("trading_state/YOUR_EXCHANGE_orders.json"):
    with open("trading_state/YOUR_EXCHANGE_orders.json", "r") as f:
        orders = json.load(f)
        pg_store.save_orders(orders)
```

## Benefits

1. **Reliability**: ACID-compliant storage with transaction support
2. **Concurrent Access**: Multiple processes can safely access state
3. **Monitoring**: Integrated with Prometheus/Grafana for metrics
4. **Querying**: SQL access for analysis and reporting
5. **Backup**: Standard PostgreSQL backup/restore procedures
6. **Scalability**: Can handle large volumes of trading data

## Rollback

To rollback to file-based storage:

1. Set environment variable to disable PostgreSQL:
```bash
export DISABLE_POSTGRES=true
```

2. Or modify the trader initialization to use SimpleStateStore directly:
```python
self.state_store = SimpleStateStore(exchange=self.config.exchange_name.upper())
```

## Monitoring

View trading state in Grafana dashboard:
- http://localhost:3000 (default: admin/admin)

Query database directly:
```bash
# View recent trades
docker-compose exec postgres psql -U trading_user -d trading \
  -c "SELECT * FROM trades ORDER BY executed_at DESC LIMIT 10;"

# View open positions
docker-compose exec postgres psql -U trading_user -d trading \
  -c "SELECT * FROM positions WHERE status = 'open';"

# View trading state
docker-compose exec postgres psql -U trading_user -d trading \
  -c "SELECT * FROM trading.trading_state ORDER BY updated_at DESC LIMIT 10;"
```

## Troubleshooting

### Database Connection Issues
Check logs:
```bash
docker-compose logs postgres
docker-compose logs trading_bot
```

### Verify Connectivity
```bash
docker-compose exec trading_bot python -c "
from framework.utils.postgres_state_store import PostgreSQLStateStore
store = PostgreSQLStateStore()
print('Connection successful!')
"
```

### Reset State
```sql
-- Clear trading state (careful!)
DELETE FROM trading.trading_state WHERE instance_id = 'YOUR_INSTANCE_ID';
DELETE FROM trading.trading_locks WHERE instance_id = 'YOUR_INSTANCE_ID';
```