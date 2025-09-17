"""
Main entry point for trading bot - adapted from old branch to work with current framework
"""
import os
import sys
import signal
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from framework.strategies.sma_strategy import SMAStrategy
from framework.strategies.breakout_strategy import BreakoutStrategy
from framework.strategies.fvg_strategy import FVGStrategy
from framework.strategies.mean_reversion_strategy import MeanReversionStrategy
from framework.strategies.test_strategy import TestStrategy


# Simple config class using environment variables
class SimpleConfig:
    def __init__(self):
        load_dotenv()
        
        # Broker settings
        self.broker = os.getenv('BROKER', 'paper_ccxt')
        self.exchange_name = os.getenv('EXCHANGE_NAME', 'binance')
        self.symbols = [s.strip() for s in os.getenv('SYMBOLS', 'BTC/USDT:USDT').split(',')]
        self.timeframe = os.getenv('TIMEFRAME', '1m')
        self.use_sandbox = os.getenv('USE_SANDBOX', 'true').lower() == 'true'
        
        # API keys
        self.exchange_api_key = os.getenv('EXCHANGE_API_KEY', '')
        self.exchange_api_secret = os.getenv('EXCHANGE_API_SECRET', '')
        # Additional config for ccxt_trader compatibility
        self.api_key = self.exchange_api_key
        self.api_secret = self.exchange_api_secret
        
        # Trading configuration
        self.trading_type = os.getenv('TRADING_TYPE', 'future')  # 'spot' or 'future'
        self.allow_shorting = os.getenv('ALLOW_SHORTING', 'true').lower() == 'true'
        
        # Fees and slippage simulation (for paper trading)
        self.commission = float(os.getenv('COMMISSION_RATE', '0.001'))  # 0.1% default
        self.slippage = float(os.getenv('SLIPPAGE_RATE', '0.0005'))    # 0.05% default
        
        # Strategy
        self.strategy_name = os.getenv('STRATEGY_NAME', 'sma')
        self.strategy_params = {}
        
        # Risk management
        self.initial_capital = float(os.getenv('INITIAL_CAPITAL', '10000.0'))
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE', '0.1'))
        
        # Logging
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.use_json_logs = os.getenv('USE_JSON_LOGS', 'false').lower() == 'true'


def main() -> None:
    """Main trading bot function"""
    # Load configuration
    config = SimpleConfig()

    # Setup logging
    from framework.utils.logger import setup_logger
    logger = setup_logger(config.log_level)
    logger.info("Starting trading bot...")
    
    # Global trader reference for signal handler
    trader = None
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        if trader and hasattr(trader, 'shutdown'):
            trader.shutdown()
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Select strategy based on configuration
    if config.strategy_name.lower() == "sma":
        strategy = SMAStrategy()
    elif config.strategy_name.lower() == "breakout":
        strategy = BreakoutStrategy()
    elif config.strategy_name.lower() == "fvg":
        strategy = FVGStrategy()
    elif config.strategy_name.lower() == "mean_reversion":
        strategy = MeanReversionStrategy()
    elif config.strategy_name.lower() == "test":
        strategy = TestStrategy()
    else:
        # Default to SMA
        logger.warning(f"Unknown strategy {config.strategy_name}, defaulting to SMA")
        strategy = SMAStrategy()
    
    # Initialize trader based on broker selection
    if config.broker == "paper_ccxt":
        # Paper trading with real market data (SAFE)
        from framework.execution.ccxt.ccxt_paper_trader import CCXTPaperTrader
        trader = CCXTPaperTrader(config)
        logger.info("Using PAPER TRADING with real market data")
    elif config.broker == "ccxt":
        # Live trading with real money (DANGEROUS)
        from framework.execution.ccxt.ccxt_trader import CCXTTrader
        trader = CCXTTrader(config)
        logger.warning("🚨 USING LIVE TRADING WITH REAL MONEY 🚨")
    else:
        raise ValueError(f"Unknown broker: {config.broker}. Use 'paper_ccxt' or 'ccxt'")

    logger.info(f"Using strategy: {strategy.__class__.__name__}")

    # Announce trading mode
    data_source = "SANDBOX" if config.use_sandbox else "LIVE DATA"
    if config.broker == "paper_ccxt":
        logger.warning(f"Starting PAPER TRADING with {data_source} - Virtual money only!")
    else:
        logger.warning(f"Starting LIVE TRADING with {data_source} - REAL MONEY AT RISK!")

    # Main trading loop
    while True:
        try:
            # Process each symbol using the proven trading cycle
            for symbol in config.symbols:
                trader.run_trading_cycle(symbol, strategy)

            # Get performance summary
            performance = trader.get_performance_summary()
            logger.info(
                "Performance summary",
                extra={
                    'daily_pnl': performance.get('daily_pnl', 0),
                    'open_positions': performance.get('open_positions', 0),
                    'initial_balance': performance.get('initial_balance', 0),
                    'current_balance': performance.get('current_balance', 0),
                    'total_pnl': performance.get('total_pnl', 0),
                    'emergency_stop': performance.get('emergency_stop', False),
                    'trading_mode': performance.get('mode', 'UNKNOWN')
                }
            )

            # Calculate sleep time until next candle
            timeframe_map = {
                '1m': 60, '5m': 300, '15m': 900, '30m': 1800, 
                '1h': 3600, '4h': 14400, '1d': 86400
            }
            timeframe_seconds = timeframe_map.get(config.timeframe, 60)
            
            sleep_time = timeframe_seconds - (time.time() % timeframe_seconds)

            if sleep_time > 5:
                logger.info(f"💤 Sleeping {sleep_time:.0f}s until next {config.timeframe} candle...")
                time.sleep(sleep_time)
            else:
                # If too close to next candle, wait for the one after
                time.sleep(sleep_time + timeframe_seconds)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(60)  # Wait before retry


if __name__ == "__main__":
    main()