# Trading Bot Monitoring Setup

This monitoring stack provides comprehensive observability for the trading bot using PostgreSQL, Prometheus, and Grafana.

## Components

1. **PostgreSQL** - State store for trades, positions, and performance metrics
2. **Prometheus** - Metrics collection and alerting
3. **Grafana** - Visualization and dashboards
4. **Node Exporter** - System metrics (CPU, Memory, Disk)
5. **PostgreSQL Exporter** - Database metrics
6. **Adminer** - Web-based database management interface

## Getting Started

1. Copy the environment file:
```bash
cp .env.example .env
```

2. Update the `.env` file with your configuration

3. Start the monitoring stack:
```bash
docker-compose up -d postgres prometheus grafana
```

4. Access services:
- Grafana: http://localhost:3000 (admin/admin or your configured password)
- Prometheus: http://localhost:9090
- Adminer: http://localhost:8080 (database management)
- PostgreSQL: localhost:5432

### Adminer Login
- System: PostgreSQL
- Server: postgres (or localhost if accessing from host)
- Username: trading_user
- Password: trading_password (or from .env)
- Database: trading

## Database Schema

The PostgreSQL database includes the following tables:

- `trades` - All executed trades
- `positions` - Open and closed positions
- `balance_snapshots` - Account balance over time
- `performance_metrics` - Aggregated trading performance
- `api_metrics` - API latency tracking
- `alerts` - Trading alerts and notifications

## Grafana Dashboard

The main trading dashboard includes:

- Account balance over time
- Total realized PnL
- Win rate
- Total trades and open positions
- Recent trades table
- Daily PnL chart
- API latency metrics
- System resource usage

## Prometheus Alerts

Configured alerts include:
- PostgreSQL connectivity
- High database connections
- High CPU/Memory usage
- Low disk space
- Trading bot availability
- High API latency
- Failed trade rate

## Integrating with Trading Bot

To log trades and positions from your trading bot:

```python
import psycopg2
from datetime import datetime

# Connect to database
conn = psycopg2.connect(
    host="localhost",
    database="trading",
    user="trading_user",
    password="trading_password"
)

# Log a trade
cursor = conn.cursor()
cursor.execute("""
    INSERT INTO trades (trade_id, symbol, strategy, side, quantity, price, status, executed_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
""", (trade_id, symbol, strategy, side, quantity, price, status, datetime.now()))
conn.commit()
```

## Metrics Endpoint

The trading bot exposes metrics on port 8000 at `/metrics` endpoint for Prometheus scraping.

## Troubleshooting

1. Check container logs:
```bash
docker-compose logs -f [service_name]
```

2. Verify database connection:
```bash
docker-compose exec postgres psql -U trading_user -d trading -c "\dt"
```

3. Test Prometheus targets:
- Visit http://localhost:9090/targets to see scrape status

4. Grafana datasource issues:
- Ensure PostgreSQL and Prometheus datasources are configured
- Check network connectivity between containers