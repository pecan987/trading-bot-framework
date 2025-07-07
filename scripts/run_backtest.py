"""
Enhanced backtest runner supporting multiple data sources
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtesting import Backtest, Strategy
import pandas as pd
from datetime import datetime, timedelta
import json
from pathlib import Path
from config.settings import load_config
from data import YahooFinanceSource, CCXTSource, CSVDataSource
from strategies.trend_following import SMAStrategy
from strategies.mean_reversion import MeanReversion
from strategies.breakout_strategy import BreakoutStrategy
from strategies.sfp_strategy import SFPStrategy
from utils.logger import setup_logger

def run_backtest(strategy_name: str, symbol: str, start_date: str, end_date: str, data_source: str = None, timeframe: str = None, debug: bool = False, no_sl_tp: bool = False):
    """Run backtest for given strategy and symbol with flexible data sources"""

    config = load_config()
    logger = setup_logger(config.log_level)

    # Use specified data source or config default
    if data_source:
        config.data_source = data_source
    
    # Use specified timeframe or config default
    if timeframe:
        config.timeframe = timeframe

    logger.info(f"Running backtest: {strategy_name} on {symbol} using {config.data_source} data ({config.timeframe})")
    if no_sl_tp:
        logger.info("Stop Loss and Take Profit DISABLED - using fixed 1% position sizing")

    # Initialize data source
    if config.data_source == "yahoo":
        source = YahooFinanceSource()
    elif config.data_source == "ccxt":
        source = CCXTSource(
            exchange_name=config.exchange_name,
            api_key=config.api_key,
            api_secret=config.api_secret,
            sandbox=config.use_sandbox
        )
    elif config.data_source == "csv":
        source = CSVDataSource(data_directory=config.csv_data_directory)
    elif config.data_source == "csv_processed":
        source = CSVDataSource(data_directory=config.csv_data_directory, use_processed=True)
    else:
        logger.error(f"Unknown data source: {config.data_source}")
        return None

    # Load data
    data = source.get_historical_data(symbol, start_date, end_date, config.timeframe)
        
    if data.empty:
        logger.error(f"Failed to load data for {symbol} from {config.data_source}")
        return None
    
    # Convert to microBTC for fractional trading if dealing with BTC data
    # BUT only if we're NOT using preprocessed data (which is already in microBTC)
    if 'BTC' in symbol.upper():
        logger.info("Converting prices to microBTC for fractional trading")
        # Convert OHLC prices to microBTC (divide by 1e6)
        price_columns = ['Open', 'High', 'Low', 'Close']
        for col in price_columns:
            if col in data.columns:
                data[col] = data[col] / 1e6
        # Adjust volume (multiply by 1e6 to compensate)
        if 'Volume' in data.columns:
            data['Volume'] = data['Volume'] * 1e6

    # Log available feature columns
    feature_columns = [col for col in data.columns if col not in ['Open', 'High', 'Low', 'Close', 'Volume']]
    if feature_columns:
        logger.info(f"Found additional feature columns: {', '.join(feature_columns)}")

    # Select strategy
    if strategy_name.lower() in ["sma", "sma_crossover", "trend_following"]:
        strategy_class = SMAStrategy
    elif strategy_name.lower() in ["rsi", "rsi_mean_reversion"]:
        strategy_class = MeanReversion
    elif strategy_name.lower() in ["breakout", "breakout_strategy"]:
        strategy_class = BreakoutStrategy
    elif strategy_name.lower() in ["sfp"]:
        strategy_class = SFPStrategy
    else:
        logger.error(f"Unknown strategy: {strategy_name}")
        return None

    # Create strategy with config parameters and debug option
    strategy_params = config.strategy_params.copy() if config.strategy_params else {}
    if debug:
        strategy_params['debug_export'] = True
    
    strategy_instance = strategy_class(strategy_params)
    
    # Add indicators if strategy supports it
    if hasattr(strategy_instance, 'add_indicators'):
        data = strategy_instance.add_indicators(data)

    # Create wrapper strategy for backtesting library
    class BacktestWrapper(Strategy):
        def init(self):
            super().init()
            # Convert backtesting data object to DataFrame for our strategy
            # Include ALL columns from the original data, not just OHLCV
            df_data = pd.DataFrame({
                'Open': self.data.Open,
                'High': self.data.High,
                'Low': self.data.Low,
                'Close': self.data.Close,
                'Volume': self.data.Volume
            })
            df_data.index = self.data.index
            
            # Add any additional columns from the original data (like daily/weekly opens)
            for col in data.columns:
                if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    df_data[col] = data[col]
            
            self.signals = strategy_instance.generate_signals(df_data)

        def next(self):
            super().next()
            current_idx = len(self.data.Close) - 1
            if current_idx >= len(self.signals):
                return

            # Handle both Series and DataFrame formats
            if isinstance(self.signals, pd.Series):
                signal = self.signals.iloc[current_idx]
                stop_loss = None
                take_profit = None
            else:
                signal = self.signals.iloc[current_idx]['signal']
                stop_loss = self.signals.iloc[current_idx].get('stop_loss', None)
                take_profit = self.signals.iloc[current_idx].get('take_profit', None)
            current_price = self.data.Close[-1]
            
            # Debug: print signal info
            if debug and signal != 0:
                pos_info = f"Long({self.position.size})" if self.position and self.position.is_long else f"Short({abs(self.position.size)})" if self.position and self.position.is_short else "None"
                price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                print(f"Day {current_idx}: Signal={signal}, Price={current_price:.2f}{price_unit}, Position={pos_info}")

            if current_idx < len(self.signals):
                # Check if strategy is long-only (none currently)
                is_long_only_strategy = False
                
                # Close any existing position first if signal changes direction
                if self.position and (
                    (signal == 1 and self.position.is_short) or 
                    (signal == -1 and self.position.is_long)
                ):
                    if debug:
                        direction = "short" if self.position.is_short else "long"
                        print(f"  Closing existing {direction} position: {self.position}")
                    self.position.close()
                
                if signal == 1:  # Buy signal (long)
                    if not self.position:
                        current_account_value = self.equity
                        risk_amount = current_account_value * 0.01  # 1% risk

                        if no_sl_tp:
                            # Fixed position sizing - 1% of equity in dollar terms
                            target_value = current_account_value * 0.01
                            units = max(1, int(target_value / current_price))
                            if debug:
                                price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                print(f"  Buying: {units} units @ {current_price:.2f}{price_unit} (target: ${target_value:.2f})")
                            self.buy(size=units)
                        else:
                            if stop_loss and stop_loss > 0:
                                risk_per_share = current_price - stop_loss
                                if risk_per_share > 0:
                                    units = max(1, int(risk_amount / risk_per_share))
                                    if debug:
                                        price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                        print(f"  Buying: {units} units @ {current_price:.2f}{price_unit} (SL: {stop_loss:.2f}{price_unit})")
                                    self.buy(size=units, sl=stop_loss, tp=take_profit)
                            else:
                                # No stop loss - use fixed sizing
                                target_value = current_account_value * 0.01
                                units = max(1, int(target_value / current_price))
                                if debug:
                                    price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                    print(f"  Buying: {units} units @ {current_price:.2f}{price_unit} (no SL)")
                                self.buy(size=units)

                elif signal == -1:  # Sell signal
                    # For long-only strategies, only close existing long positions
                    if is_long_only_strategy:
                        if self.position and self.position.is_long:
                            if debug:
                                print(f"  Closing long position: {self.position}")
                            self.position.close()
                    elif not self.position:  # Original short-selling logic for other strategies
                        current_account_value = self.equity
                        risk_amount = current_account_value * 0.01  # 1% risk

                        if no_sl_tp:
                            # Fixed position sizing - 1% of equity in dollar terms
                            target_value = current_account_value * 0.01
                            units = max(1, int(target_value / current_price))
                            if debug:
                                price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                print(f"  Selling short: {units} units @ {current_price:.2f}{price_unit} (target: ${target_value:.2f})")
                            self.sell(size=units)
                        else:
                            if stop_loss and stop_loss > 0:
                                risk_per_share = stop_loss - current_price
                                if risk_per_share > 0:
                                    units = max(1, int(risk_amount / risk_per_share))
                                    if debug:
                                        price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                        print(f"  Selling short: {units} units @ {current_price:.2f}{price_unit} (SL: {stop_loss:.2f}{price_unit})")
                                    self.sell(size=units, sl=stop_loss, tp=take_profit)
                            else:
                                # No stop loss - use fixed sizing
                                target_value = current_account_value * 0.01
                                units = max(1, int(target_value / current_price))
                                if debug:
                                    price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                                    print(f"  Selling short: {units} units @ {current_price:.2f}{price_unit} (no SL)")
                                self.sell(size=units)

    # Run backtest with sufficient capital for Bitcoin trading
    bt = Backtest(
        data,
        BacktestWrapper,
        cash=config.initial_capital,
        commission=config.commission,
        trade_on_close=True,
        hedging=True,
        exclusive_orders=True,
        spread=config.slippage,
        margin=0.01
    )

    results = bt.run()

    # Create output filename with strategy, symbol, and timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Replace / with _ in symbol for filename
    symbol_safe = symbol.replace('/', '_')
    run_dir = f"{strategy_name}_{symbol_safe}_{timestamp}"
    output_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "output" / "backtests" / run_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_filename = f"{strategy_name}_{symbol_safe}_{timestamp}"
    
    # Save results to JSON file
    results_dict = {}
    for key, value in results.items():
        if isinstance(value, (int, float, str, bool)):
            results_dict[key] = value
        elif hasattr(value, 'isoformat'):  # datetime objects
            results_dict[key] = value.isoformat()
        else:
            results_dict[key] = str(value)
    
    # Add metadata
    results_dict['metadata'] = {
        'strategy': strategy_name,
        'symbol': symbol,
        'start_date': start_date,
        'end_date': end_date,
        'data_source': config.data_source,
        'timeframe': config.timeframe,
        'data_points': len(data),
        'date_range_start': data.index[0].isoformat(),
        'date_range_end': data.index[-1].isoformat(),
        'timestamp': datetime.now().isoformat(),
        'no_sl_tp': no_sl_tp
    }
    
    json_file = output_dir / f"{output_filename}_results.json"
    with open(json_file, 'w') as f:
        json.dump(results_dict, f, indent=2, default=str)
    
    logger.info(f"Results saved to: {json_file}")

    # Print all available results
    logger.info("=== BACKTEST RESULTS ===")
    for key, value in results.items():
        if isinstance(value, (int, float)):
            if 'Return' in key or 'Drawdown' in key or 'Rate' in key:
                logger.info(f"{key}: {value:.2f}%" if '%' not in key else f"{key}: {value:.2f}")
            elif 'Ratio' in key or 'Factor' in key:
                logger.info(f"{key}: {value:.3f}")
            else:
                logger.info(f"{key}: {value}")
        else:
            logger.info(f"{key}: {value}")
    logger.info(f"Data points: {len(data)}")
    logger.info(f"Date range: {data.index[0]} to {data.index[-1]}")

    # Save and show plot
    try:
        plot_file = output_dir / f"{output_filename}_plot.html"
        # Try plotting without superimpose first (which causes issues with some timeframes)
        try:
            bt.plot(filename=str(plot_file), open_browser=True, superimpose=False)
        except:
            # If that fails, try with resample=False to avoid upsampling issues
            bt.plot(filename=str(plot_file), open_browser=True, resample=False)
        logger.info(f"Plot saved to: {plot_file}")
    except Exception as e:
        logger.warning(f"Could not save plot: {e}")

    # Save and print trades for detailed analysis
    try:
        trades = bt._results._trades
        if not trades.empty:
            # Save trades to CSV
            trades_file = output_dir / f"{output_filename}_trades.csv"
            trades.to_csv(trades_file, index=False)
            logger.info(f"Trades saved to: {trades_file}")
            
            logger.info("\n=== TRADE DETAILS ===")
            for i, trade in trades.iterrows():
                entry_time = trade['EntryTime']
                exit_time = trade['ExitTime']
                size = trade['Size']
                entry_price = trade['EntryPrice']
                exit_price = trade['ExitPrice']
                pnl = trade['PnL']
                pnl_pct = trade['ReturnPct']
                duration = trade['Duration']
                
                price_unit = "μBTC" if 'BTC' in symbol.upper() else ""
                logger.info(f"Trade {i+1}: {entry_time} -> {exit_time}")
                if 'BTC' in symbol.upper():
                    logger.info(f"  Size: {size:.0f} units | Entry: {entry_price:.2f}{price_unit} | Exit: {exit_price:.2f}{price_unit}")
                else:
                    logger.info(f"  Size: {size:.0f} units | Entry: {entry_price:.6f} | Exit: {exit_price:.6f}")
                logger.info(f"  P&L: ${pnl:.2f} ({pnl_pct:.2f}%) | Duration: {duration}")
        else:
            logger.info("No trades executed")
    except Exception as e:
        logger.warning(f"Could not display trade details: {e}")
    
    logger.info(f"\nAll backtest outputs saved to: {output_dir}")
    logger.info(f"Output files: {output_filename}_results.json, {output_filename}_plot.html" + 
               (f", {output_filename}_trades.csv" if 'trades' in locals() and not trades.empty else ""))
    
    return results

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Run trading strategy backtest')
    parser.add_argument('--strategy', help='Strategy name (sma, rsi)')
    parser.add_argument('--symbol', help='Symbol to test')
    parser.add_argument('--start', default='2024-06-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2025-01-01', help='End date (YYYY-MM-DD)')
    parser.add_argument('--data-source', help='Data source (yahoo, ccxt, csv, csv_processed) - overrides config')
    parser.add_argument('--timeframe', help='Timeframe (1m, 5m, 15m, 30m, 1h, 1d) - overrides config')
    parser.add_argument('--debug', action='store_true', help='Enable debug data export')
    parser.add_argument('--no-sl-tp', action='store_true', help='Disable stop loss and take profit (use fixed position sizing instead)')

    args = parser.parse_args()

    # Load config to get defaults if arguments not provided
    config = load_config()
    
    # Use config defaults if arguments not provided
    strategy = args.strategy or config.strategy_name
    symbol = args.symbol or (config.symbols[0] if config.symbols else "AAPL")
    
    run_backtest(strategy, symbol, args.start, args.end, args.data_source, args.timeframe, args.debug, args.no_sl_tp)