#!/usr/bin/env python3
"""
Main entry point for live trading bot
"""
import os
import sys
import json
import logging
import signal
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from framework.utils.logger import setup_logger
from framework.live.db_manager import DatabaseManager
from framework.live.trading_engine import TradingEngine
from framework.live.brokers.ccxt_broker import CCXTBroker
from framework.live.brokers.paper_broker import PaperBroker

# Import strategies
from framework.strategies.sma_strategy import SMAStrategy
from framework.strategies.breakout_strategy import BreakoutStrategy
from framework.strategies.fvg_strategy import FVGStrategy
from framework.strategies.mean_reversion_strategy import MeanReversionStrategy


def create_broker(broker_type: str, config: dict = None):
    """
    Factory function to create appropriate broker
    
    Args:
        broker_type: Type of broker (ccxt, paper_ccxt, ibkr, paper_ibkr)
        config: Broker configuration
    
    Returns:
        Broker instance
    """
    if broker_type == "ccxt":
        return CCXTBroker(
            exchange_name=os.getenv('CCXT_EXCHANGE', 'binance'),
            api_key=os.getenv('CCXT_API_KEY'),
            api_secret=os.getenv('CCXT_API_SECRET'),
            testnet=os.getenv('CCXT_TESTNET', 'true').lower() == 'true',
            config=config
        )
    
    elif broker_type == "paper_ccxt":
        # Create CCXT broker for data
        data_broker = CCXTBroker(
            exchange_name=os.getenv('CCXT_EXCHANGE', 'binance'),
            api_key=os.getenv('CCXT_API_KEY'),
            api_secret=os.getenv('CCXT_API_SECRET'),
            testnet=os.getenv('CCXT_TESTNET', 'true').lower() == 'true',
            config=config
        )
        
        # Wrap in paper trading
        return PaperBroker(
            data_broker=data_broker,
            initial_capital=float(os.getenv('INITIAL_CAPITAL', 10000)),
            commission_rate=float(os.getenv('COMMISSION_RATE', 0.001)),
            slippage_rate=float(os.getenv('SLIPPAGE_RATE', 0.0005))
        )
    
    # TODO: Add IBKR broker support
    elif broker_type in ["ibkr", "paper_ibkr"]:
        raise NotImplementedError(f"Broker {broker_type} not yet implemented")
    
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")


def create_strategy(strategy_name: str, params: dict = None):
    """
    Factory function to create strategy
    
    Args:
        strategy_name: Name of strategy
        params: Strategy parameters
    
    Returns:
        Strategy instance
    """
    # Parse strategy params from environment
    if params is None:
        params_str = os.getenv('STRATEGY_PARAMS', '{}')
        try:
            params = json.loads(params_str)
        except:
            params = {}
    
    # Create strategy - all strategies use same pattern
    if strategy_name.lower() == "sma":
        return SMAStrategy(**params) if params else SMAStrategy()
    elif strategy_name.lower() == "breakout":
        return BreakoutStrategy(**params) if params else BreakoutStrategy()
    elif strategy_name.lower() == "fvg":
        return FVGStrategy(**params) if params else FVGStrategy()
    elif strategy_name.lower() == "mean_reversion":
        return MeanReversionStrategy(**params) if params else MeanReversionStrategy()
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")


def main():
    """Main function"""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    logger = setup_logger(log_level)
    
    # Global reference for cleanup
    engine = None
    
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}, shutting down gracefully...")
        if engine:
            engine.is_running = False  # Stop the loop immediately
            engine.stop()
        logger.info("✅ Trading bot stopped")
        sys.exit(0)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("=" * 50)
    logger.info("Starting Trading Bot")
    logger.info("=" * 50)
    
    try:
        # Get configuration from environment
        broker_type = os.getenv('BROKER', 'paper_ccxt')
        strategy_name = os.getenv('STRATEGY', 'breakout')
        symbol = os.getenv('SYMBOL', 'BTC/USDT')
        timeframe = os.getenv('TIMEFRAME', '15m')
        
        # Risk management settings
        position_size = float(os.getenv('MAX_POSITION_PCT', 0.1))
        stop_loss_pct = float(os.getenv('STOP_LOSS_PCT', 0.02))
        take_profit_pct = float(os.getenv('TAKE_PROFIT_PCT', 0.04))
        risk_per_trade = float(os.getenv('RISK_PER_TRADE', 0.01))
        
        # Safety settings
        paper_trading = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        
        # Override broker if paper trading is forced
        if paper_trading and not broker_type.startswith('paper_'):
            logger.warning(f"Paper trading mode enabled, switching from {broker_type} to paper_{broker_type}")
            broker_type = f"paper_{broker_type}"
        
        logger.info(f"Configuration:")
        logger.info(f"  Broker: {broker_type}")
        logger.info(f"  Strategy: {strategy_name}")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Timeframe: {timeframe}")
        logger.info(f"  Position Size: {position_size * 100}%")
        logger.info(f"  Stop Loss: {stop_loss_pct * 100}%")
        logger.info(f"  Take Profit: {take_profit_pct * 100}%")
        
        # Create broker
        logger.info(f"Creating {broker_type} broker...")
        broker = create_broker(broker_type)
        
        # Create strategy
        logger.info(f"Creating {strategy_name} strategy...")
        strategy = create_strategy(strategy_name)
        
        # Create database manager (optional)
        db_manager = None
        if os.getenv('DB_HOST'):
            logger.info("Connecting to database...")
            db_manager = DatabaseManager()
        
        # Create trading engine
        engine = TradingEngine(
            broker=broker,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            lookback_periods=int(os.getenv('LOOKBACK_PERIODS', 100)),
            db_manager=db_manager,
            position_size=position_size,
            max_positions=int(os.getenv('MAX_POSITIONS', 1)),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_per_trade=risk_per_trade,
            use_risk_management=os.getenv('USE_RISK_MANAGEMENT', 'true').lower() == 'true'
        )
        
        # Start trading
        logger.info("Starting trading engine...")
        logger.info("Press Ctrl+C to stop")
        
        try:
            engine.start()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            engine.stop()
        except Exception as e:
            logger.error(f"Engine error: {e}")
            engine.stop()
            raise
        
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        if 'engine' in locals():
            engine.stop()
        if 'db_manager' in locals() and db_manager:
            db_manager.close()
        logger.info("Trading bot stopped")


if __name__ == "__main__":
    main()