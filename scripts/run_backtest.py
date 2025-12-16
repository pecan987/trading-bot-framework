#!/usr/bin/env python3
"""
Backtest Runner using backtesting.py library

This script provides backtesting functionality using the industry-standard 
backtesting.py library. It includes a wrapper to adapt our existing 
framework strategies to work with backtesting.py.
"""

import argparse
import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import json
import warnings
import time

# Add framework to path
script_dir = Path(__file__).parent
framework_dir = script_dir.parent
sys.path.append(str(framework_dir))

# Import backtesting.py library
try:
    from backtesting import Backtest, Strategy
    from backtesting.lib import crossover, FractionalBacktest
except ImportError:
    print("Error: backtesting library not found. Install it with: uv add backtesting")
    sys.exit(1)

from framework.utils.logger import setup_logger
from framework.strategies.sma_strategy import SMAStrategy
from framework.strategies.fvg_strategy import FVGStrategy
from framework.strategies.breakout_strategy import BreakoutStrategy
from framework.strategies.silver_bullet_fvg_strategy import SilverBulletFVGStrategy
from framework.strategies.mean_reversion_strategy import MeanReversionStrategy
from framework.strategies.test_strategy import TestStrategy
from framework.backtesting.strategy_wrapper import create_wrapper_class
from framework.risk.fixed_position_size_manager import FixedPositionSizeManager
from framework.risk.fixed_risk_manager import FixedRiskManager
from framework.risk.strategy_position_size_manager import StrategyPositionSizeManager


def load_data(file_path: str, start_date: Optional[str] = None, 
              end_date: Optional[str] = None) -> pd.DataFrame:
    """Load and prepare data for backtesting.py"""
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Data file not found: {file_path}")
    
    print(f"Loading data from: {file_path}")
    
    # Load CSV file
    df = pd.read_csv(file_path, index_col=0, parse_dates=True)

    # Ensure index is DatetimeIndex (handles timezone-aware strings)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)

    # Filter by date range
    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]

    # Ensure we have the required columns
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    print(f"Loaded {len(df)} data points")
    print(f"Data range: {df.index[0]} to {df.index[-1]}")
    print(f"Price range: ${df['Close'].min():.2f} - ${df['Close'].max():.2f}")
    
    return df


def run_backtest(strategy_name: str, data: pd.DataFrame, 
                strategy_params: Dict[str, Any], 
                symbol: str,
                initial_capital: float = 10000,
                commission: float = 0.0005,
                use_fractional: bool = True,
                risk_manager_type: str = "fixed_position",
                risk_manager_params: Dict[str, Any] = None,
                margin: float = 0.01,
                debug: bool = False) -> None:
    """Run backtest using backtesting.py with our framework strategies"""
    
    # Map strategy names to our framework strategy classes
    framework_strategies = {
        'sma': SMAStrategy,
        'fvg': FVGStrategy,
        'breakout': BreakoutStrategy,
        'silver_bullet_fvg': SilverBulletFVGStrategy,
        'mean_reversion': MeanReversionStrategy,
        'test': TestStrategy
        # Add more strategies here as they become available
        # 'rsi': RSIStrategy,
        # 'macd': MACDStrategy,
    }
    
    if strategy_name not in framework_strategies:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(framework_strategies.keys())}")
    
    # Get the framework strategy class
    FrameworkStrategyClass = framework_strategies[strategy_name]
    
    # Create risk manager
    risk_manager = None
    if risk_manager_params is None:
        risk_manager_params = {}
        
    if risk_manager_type == "fixed_position":
        risk_manager = FixedPositionSizeManager(
            position_size=risk_manager_params.get('position_size', 0.1)
        )
    elif risk_manager_type == "fixed_risk":
        risk_manager = FixedRiskManager(
            risk_percent=risk_manager_params.get('risk_percent', 0.01),
            default_stop_distance=risk_manager_params.get('default_stop_distance', 0.02)
        )
    elif risk_manager_type == "strategy_position":
        risk_manager = StrategyPositionSizeManager(
            max_position_size=risk_manager_params.get('max_position_size', 1.0),
            min_position_size=risk_manager_params.get('min_position_size', 0.001),
            apply_safety_limits=risk_manager_params.get('apply_safety_limits', True)
        )
    else:
        raise ValueError(f"Unknown risk manager type: {risk_manager_type}. Available: ['fixed_position', 'fixed_risk', 'strategy_position']")
    
    # Create wrapper strategy class
    print(f"\n📈 Setting up {strategy_name.upper()} strategy...")
    print(f"🔧 Creating strategy wrapper...")
    
    WrapperClass = create_wrapper_class(
        FrameworkStrategyClass, 
        strategy_params,
        risk_manager=risk_manager,
        debug=debug
    )
    
    print(f"✅ Strategy wrapper created successfully")
    
    # Create and run backtest
    print(f"\nRunning backtest with strategy: {strategy_name}")
    print(f"Strategy parameters: {strategy_params}")
    print(f"Risk manager: {risk_manager.get_description()}")
    print(f"Initial capital: ${initial_capital:,.2f}")
    print(f"Commission: {commission:.3%}")
    print(f"Leverage: {int(1/margin)}x (margin={margin:.2%})")
    
    # Choose backtest engine based on use_fractional parameter
    if use_fractional:
        print("Using FractionalBacktest for high-precision fractional trading")
        bt = FractionalBacktest(
            data=data,
            strategy=WrapperClass,
            cash=initial_capital,
            commission=commission,
            margin=margin,
            exclusive_orders=True
        )
    else:
        bt = Backtest(
            data=data,
            strategy=WrapperClass,
            cash=initial_capital,
            commission=commission,
            margin=margin,
            exclusive_orders=True
        )
    
    # Run the backtest with progress indication
    print(f"\n{'='*60}")
    print("🚀 RUNNING BACKTEST...")
    print(f"📊 Processing {len(data):,} data points...")
    print(f"📅 Date range: {data.index[0].strftime('%Y-%m-%d %H:%M')} to {data.index[-1].strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print()  # Extra line for tqdm progress bar
    
    start_time = time.time()
    
    try:
        # Run backtest - tqdm will show progress bar automatically if installed
        result = bt.run()
        
        end_time = time.time()
        duration = end_time - start_time
        print(f"\n✅ Backtest completed successfully!")
        print(f"⏱️  Execution time: {duration:.2f} seconds")
        print(f"📈 Processed {len(data)/duration:.0f} data points per second")
        
    except Exception as e:
        print(f"\n❌ Backtest failed: {e}")
        raise
    
    # Display results
    print("\n" + "="*80)
    print(f"📊 BACKTEST RESULTS - {strategy_name.upper()} Strategy")
    print("="*80)
    
    # Extract key metrics for better formatting
    total_return = result.get('Return [%]', 0)
    win_rate = result.get('Win Rate [%]', 0)
    total_trades = result.get('# Trades', 0)
    max_dd = result.get('Max. Drawdown [%]', 0)
    sharpe = result.get('Sharpe Ratio', 0)
    
    print(f"🎯 Performance Summary:")
    print(f"   Total Return: {total_return:.2f}%")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   Total Trades: {total_trades}")
    print(f"   Max Drawdown: {max_dd:.2f}%")
    print(f"   Sharpe Ratio: {sharpe:.2f}")
    print()
    
    # Full results
    print("📋 Detailed Results:")
    print(result)
    
    # Save detailed results
    output_dir = Path("output/backtests")
    output_dir.mkdir(exist_ok=True)
    
    # Save results to JSON
    result_dict = result._asdict() if hasattr(result, '_asdict') else dict(result)
    
    # Convert non-serializable values
    for key, value in result_dict.items():
        if hasattr(value, 'isoformat'):  # datetime objects
            result_dict[key] = value.isoformat()
        elif isinstance(value, (np.integer, np.floating)):
            result_dict[key] = float(value)
    
    # Clean symbol name for filename (replace / with _)
    clean_symbol = symbol.replace('/', '_')
    
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    result_file = output_dir / f"{strategy_name}_{clean_symbol}_{timestamp}_results.json"
    
    with open(result_file, 'w') as f:
        json.dump(result_dict, f, indent=2, default=str)
    
    print(f"\nDetailed results saved to: {result_file}")
    
    # Save individual trades to CSV
    try:
        if hasattr(result, '_trades') and result._trades is not None:
            trades_df = result._trades.copy()
            
            # Clean up trades dataframe for better CSV output
            if not trades_df.empty:
                # Convert datetime columns to string for better CSV readability
                datetime_cols = ['EntryTime', 'ExitTime']
                for col in datetime_cols:
                    if col in trades_df.columns:
                        trades_df[col] = trades_df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                
                # Round numeric columns for cleaner output
                numeric_cols = ['EntryPrice', 'ExitPrice', 'PnL', 'ReturnPct', 'Size']
                for col in numeric_cols:
                    if col in trades_df.columns:
                        if col in ['PnL']:
                            trades_df[col] = trades_df[col].round(2)
                        elif col in ['EntryPrice', 'ExitPrice']:
                            trades_df[col] = trades_df[col].round(4)
                        elif col in ['ReturnPct']:
                            trades_df[col] = (trades_df[col] * 100).round(2)  # Convert to percentage
                        elif col in ['Size']:
                            trades_df[col] = trades_df[col].round(6)
                
                # Add additional useful columns
                if 'Duration' in trades_df.columns:
                    # Convert duration to hours for readability
                    trades_df['DurationHours'] = trades_df['Duration'].dt.total_seconds() / 3600
                    trades_df['DurationHours'] = trades_df['DurationHours'].round(1)
                
                # Save trades to CSV
                trades_file = output_dir / f"{strategy_name}_{clean_symbol}_{timestamp}_trades.csv"
                trades_df.to_csv(trades_file, index=False)
                print(f"Individual trades saved to: {trades_file}")
                print(f"Total trades: {len(trades_df)}")
            else:
                print("No trades were executed during the backtest period")
        else:
            print("Trade details not available in backtest results")
    except Exception as e:
        print(f"Could not save trades to CSV: {e}")
    
    # Generate plot if possible
    try:
        plot_file = output_dir / f"{strategy_name}_{clean_symbol}_{timestamp}_plot.html"
        bt.plot(filename=str(plot_file), open_browser=False)
        print(f"Interactive plot saved to: {plot_file}")
    except Exception as e:
        print(f"Could not generate plot: {e}")
    
    return result


def main():
    """Main function for running backtests."""
    parser = argparse.ArgumentParser(description="Run backtest using backtesting.py library")
    parser.add_argument("--strategy", type=str, required=True, 
                       choices=['sma', 'fvg', 'breakout', 'silver_bullet_fvg', 'mean_reversion', 'test'],
                       help="Strategy to use")
    parser.add_argument("--data-file", type=str, required=True,
                       help="Path to CSV data file")
    parser.add_argument("--symbol", type=str, default="UNKNOWN",
                       help="Symbol identifier")
    parser.add_argument("--start", type=str,
                       help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str,
                       help="End date (YYYY-MM-DD)")
    parser.add_argument("--initial-capital", type=float, default=10000,
                       help="Initial capital (default: 10000)")
    parser.add_argument("--commission", type=float, default=0.0005,
                       help="Commission rate (default: 0.0005 = 0.05%%)")
    parser.add_argument("--use-standard", action="store_true",
                       help="Use standard Backtest instead of FractionalBacktest (not recommended for high-priced assets)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    parser.add_argument("--risk-manager", type=str, default="fixed_risk",
                       choices=['fixed_position', 'fixed_risk', 'strategy_position'],
                       help="Risk manager type (default: fixed_risk)")
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = "DEBUG" if args.debug else "INFO"
    logger = setup_logger(log_level)
    
    try:
        # Get strategy parameters from environment variable
        strategy_params = {}
        if 'STRATEGY_PARAMS' in os.environ:
            strategy_params = json.loads(os.environ['STRATEGY_PARAMS'])
            logger.info(f"Loaded strategy parameters: {strategy_params}")
        
        # Get risk manager parameters from environment variable
        risk_manager_params = {}
        if 'RISK_PARAMS' in os.environ:
            risk_manager_params = json.loads(os.environ['RISK_PARAMS'])
            logger.info(f"Loaded risk manager parameters: {risk_manager_params}")
        
        # Load data
        data = load_data(args.data_file, args.start, args.end)
        
        # Run backtest
        result = run_backtest(
            strategy_name=args.strategy,
            data=data,
            strategy_params=strategy_params,
            symbol=args.symbol,
            initial_capital=args.initial_capital,
            commission=args.commission,
            margin=0.01,
            use_fractional=not args.use_standard,
            risk_manager_type=args.risk_manager,
            risk_manager_params=risk_manager_params,
            debug=args.debug
        )
        
        logger.info("Backtest completed successfully")
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()