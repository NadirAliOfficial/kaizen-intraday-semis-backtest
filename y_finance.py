import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta

# ================== CONFIG ==================
BAR_SIZE = "5m"
TIMEZONE = pytz.timezone("America/New_York")

ENTRY_1 = 0.0012
ENTRY_2 = 0.0020
ENTRY_3 = 0.0030
INVALID_ZERO = 0.0
HARD_EXIT = 0.002
DAILY_KILL = -0.025

# ============================================

def fetch_yfinance_intraday(symbol, lookback_days=60):
    """Fetch 5-minute intraday data from Yahoo Finance"""
    print(f"Fetching {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        df = ticker.history(start=start_date, end=end_date, interval=BAR_SIZE, prepost=False)
        
        if df.empty:
            print(f"  ❌ No data for {symbol}")
            return None
        
        df = df.reset_index()
        df = df.rename(columns={'Datetime': 'date', 'Open': 'open', 'Close': 'close'})
        
        if df['date'].dt.tz is None:
            df['date'] = df['date'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
        else:
            df['date'] = df['date'].dt.tz_convert(TIMEZONE)
        
        print(f"  ✓ {len(df)} bars ({df['date'].dt.date.nunique()} days)")
        return df[['date', 'open', 'close']]
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def compute_intraday_ret(df):
    """Calculate intraday returns from day's open"""
    df = df.copy()
    df["day"] = df["date"].dt.date
    df["day_open"] = df.groupby("day")["open"].transform("first")
    df["RET"] = (df["close"] - df["day_open"]) / df["day_open"]
    
    # Calculate persistence
    df["positive"] = df["RET"] > 0
    df["negative"] = df["RET"] < 0
    df["pos_streak"] = df.groupby(["day", (df["positive"] != df["positive"].shift()).cumsum()])["positive"].cumsum() * 5
    df["neg_streak"] = df.groupby(["day", (df["negative"] != df["negative"].shift()).cumsum()])["negative"].cumsum() * 5
    df["LONG_PERSISTENCE_MIN"] = df["pos_streak"]
    df["SHORT_PERSISTENCE_MIN"] = df["neg_streak"]
    
    return df


def run_backtest_strict(data, initial_capital=100000):
    """
    STRICT IMPLEMENTATION - NO COMPROMISES
    
    Rules:
    1. One entry per signal, one exit when conditions change
    2. PnL calculated ONLY from entry price to exit price
    3. NO intrabar rebalancing
    4. SHORT rules are MORE defensive than LONG (no anti-churn)
    5. Kill switch is HARD STOP (no more trading that day)
    """
    
    capital = initial_capital
    daily_results = []
    bar_results = []
    
    # Group by day
    for day, day_data in data.groupby(data['date'].dt.date):
        day_start_capital = capital
        day_pnl = 0.0
        
        # State
        state = {
            "trading_enabled": True,
            "position_open": False,
            "entry_price": 0.0,
            "entry_symbol": None,
            "entry_mode": None,
            "entry_size": 0.0,
            "entry_leverage": 0.0
        }
        
        prev_bar = None
        
        # Process each bar
        for idx, bar in day_data.iterrows():
            
            # Skip first bar (need previous bar for decisions)
            if prev_bar is None:
                prev_bar = bar
                bar_results.append({
                    'timestamp': bar['date'],
                    'day': day,
                    'signal': 'WAIT',
                    'position_open': False,
                    'bar_pnl': 0,
                    'day_pnl': 0,
                    'capital': capital
                })
                continue
            
            # Check kill switch FIRST
            if day_pnl / day_start_capital <= DAILY_KILL:
                # HARD STOP - close position and disable trading
                if state["position_open"]:
                    exit_price = bar[f"{state['entry_symbol']}_open"]
                    if state["entry_mode"] == "LONG":
                        pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
                    else:
                        pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
                    day_pnl += pnl
                    state["position_open"] = False
                
                state["trading_enabled"] = False
                
                bar_results.append({
                    'timestamp': bar['date'],
                    'day': day,
                    'signal': 'KILL_SWITCH',
                    'position_open': False,
                    'bar_pnl': pnl if state["position_open"] else 0,
                    'day_pnl': day_pnl,
                    'capital': day_start_capital + day_pnl
                })
                continue
            
            if not state["trading_enabled"]:
                bar_results.append({
                    'timestamp': bar['date'],
                    'day': day,
                    'signal': 'DISABLED',
                    'position_open': False,
                    'bar_pnl': 0,
                    'day_pnl': day_pnl,
                    'capital': day_start_capital + day_pnl
                })
                continue
            
            # Use PREVIOUS bar for signal generation
            SMH_RET = prev_bar["SMH_RET"]
            SOXX_RET = prev_bar["SOXX_RET"]
            QQQ_RET = prev_bar["QQQ_RET"]
            VIX = prev_bar["VIX_close"]
            LONG_PERSIST = prev_bar["LONG_PERSISTENCE_MIN"]
            SHORT_PERSIST = prev_bar["SHORT_PERSISTENCE_MIN"]
            
            # Detect signal
            if SMH_RET > 0 and SOXX_RET > 0:
                signal_mode = "LONG"
                asset_ret = max(SMH_RET, SOXX_RET)
                asset_symbol = "SMH" if SMH_RET >= SOXX_RET else "SOXX"
            elif SMH_RET < 0 and SOXX_RET < 0:
                signal_mode = "SHORT"
                asset_ret = min(SMH_RET, SOXX_RET)
                asset_symbol = "SMH" if SMH_RET <= SOXX_RET else "SOXX"
            else:
                signal_mode = "NEUTRAL"
                asset_ret = 0.0
                asset_symbol = None
            
            # Calculate position fraction
            pf = 0.0
            if signal_mode == "LONG":
                if asset_ret >= ENTRY_3:
                    pf = 1.0
                elif asset_ret >= ENTRY_2:
                    pf = 0.7
                elif asset_ret >= ENTRY_1:
                    pf = 0.5
                
                # Anti-churn for LONG only
                if 0.003 <= QQQ_RET <= 0.007 and LONG_PERSIST >= 30:
                    pf = max(pf, 0.5)
                
                # Invalidation
                if asset_ret <= INVALID_ZERO:
                    pf = 0.0  # Immediate exit
                if asset_ret <= -HARD_EXIT:
                    pf = 0.0
            
            elif signal_mode == "SHORT":
                if asset_ret <= -ENTRY_3:
                    pf = 1.0
                elif asset_ret <= -ENTRY_2:
                    pf = 0.7
                elif asset_ret <= -ENTRY_1:
                    pf = 0.5
                
                # NO anti-churn for SHORT - more defensive
                
                # Immediate invalidation for SHORT
                if asset_ret >= INVALID_ZERO:
                    pf = 0.0  # Immediate exit
                if asset_ret >= HARD_EXIT:
                    pf = 0.0
            
            # Calculate leverage
            if signal_mode == "LONG" and pf > 0:
                if VIX < 12:
                    base_lev = 4.0
                elif VIX < 15:
                    base_lev = 3.0
                elif VIX < 20:
                    base_lev = 2.0
                else:
                    base_lev = 2.0
                leverage = base_lev * pf
            elif signal_mode == "SHORT" and pf > 0:
                if VIX < 20:
                    base_lev = 2.0
                elif VIX < 25:
                    base_lev = 4.0
                else:
                    base_lev = 5.0
                leverage = base_lev * pf
            else:
                leverage = 0.0
            
            # Position management
            bar_pnl = 0.0
            signal_action = "HOLD"
            
            # Check if we need to exit current position
            should_exit = False
            if state["position_open"]:
                # Exit if signal changed
                if signal_mode != state["entry_mode"]:
                    should_exit = True
                # Exit if asset switched
                elif asset_symbol != state["entry_symbol"]:
                    should_exit = True
                # Exit if position fraction went to zero
                elif pf == 0.0:
                    should_exit = True
                # Exit if leverage changed significantly
                elif abs(leverage - state["entry_leverage"]) > 0.5:
                    should_exit = True
            
            # Execute exit
            if state["position_open"] and should_exit:
                exit_price = bar[f"{state['entry_symbol']}_open"]
                if state["entry_mode"] == "LONG":
                    bar_pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
                else:
                    bar_pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
                
                day_pnl += bar_pnl
                state["position_open"] = False
                signal_action = "EXIT"
            
            # Execute entry (only if not already in position)
            if not state["position_open"] and pf > 0 and signal_mode != "NEUTRAL":
                current_capital = day_start_capital + day_pnl
                state["entry_price"] = bar[f"{asset_symbol}_open"]
                state["entry_symbol"] = asset_symbol
                state["entry_mode"] = signal_mode
                state["entry_size"] = current_capital * leverage
                state["entry_leverage"] = leverage
                state["position_open"] = True
                signal_action = "ENTRY"
            
            # Calculate unrealized PnL if position is open
            unrealized = 0.0
            if state["position_open"]:
                current_price = bar[f"{state['entry_symbol']}_close"]
                if state["entry_mode"] == "LONG":
                    unrealized = state["entry_size"] * (current_price - state["entry_price"]) / state["entry_price"]
                else:
                    unrealized = state["entry_size"] * (state["entry_price"] - current_price) / state["entry_price"]
            
            bar_results.append({
                'timestamp': bar['date'],
                'day': day,
                'signal': signal_action,
                'mode': signal_mode,
                'position_open': state["position_open"],
                'position_fraction': pf,
                'leverage': leverage,
                'entry_price': state["entry_price"] if state["position_open"] else 0,
                'current_price': bar[f"{asset_symbol}_close"] if asset_symbol else 0,
                'bar_pnl': bar_pnl,
                'unrealized_pnl': unrealized,
                'day_pnl': day_pnl,
                'day_total': day_pnl + unrealized,
                'capital': day_start_capital + day_pnl
            })
            
            prev_bar = bar
        
        # End of day - force close any open position
        if state["position_open"]:
            last_bar = day_data.iloc[-1]
            exit_price = last_bar[f"{state['entry_symbol']}_close"]
            if state["entry_mode"] == "LONG":
                final_pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
            else:
                final_pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
            day_pnl += final_pnl
        
        # Update capital
        capital = day_start_capital + day_pnl
        
        daily_results.append({
            'date': day,
            'start_capital': day_start_capital,
            'day_pnl_dollars': day_pnl,
            'day_pnl_pct': day_pnl / day_start_capital,
            'end_capital': capital
        })
    
    return pd.DataFrame(bar_results), pd.DataFrame(daily_results), capital


def analyze_backtest(bar_df, daily_df, final_capital, initial_capital=100000):
    """Analyze results"""
    
    print("\n" + "="*70)
    print("STRICT IMPLEMENTATION RESULTS")
    print("="*70)
    
    print(f"\nInitial Capital: ${initial_capital:,.2f}")
    print(f"Final Capital: ${final_capital:,.2f}")
    total_return = (final_capital / initial_capital - 1) * 100
    print(f"Total Return: {total_return:+.2f}%")
    
    print(f"\nPeriod: {daily_df['date'].min()} to {daily_df['date'].max()}")
    print(f"Trading Days: {len(daily_df)}")
    
    print(f"\n{'='*70}")
    print("DAILY PERFORMANCE")
    print(f"{'='*70}")
    
    winning_days = daily_df[daily_df['day_pnl_pct'] > 0]
    losing_days = daily_df[daily_df['day_pnl_pct'] < 0]
    flat_days = daily_df[daily_df['day_pnl_pct'] == 0]
    
    print(f"Winning Days: {len(winning_days)} ({len(winning_days)/len(daily_df)*100:.1f}%)")
    print(f"Losing Days: {len(losing_days)} ({len(losing_days)/len(daily_df)*100:.1f}%)")
    print(f"Flat Days: {len(flat_days)} ({len(flat_days)/len(daily_df)*100:.1f}%)")
    
    if len(winning_days) > 0:
        print(f"\nAvg Win: {winning_days['day_pnl_pct'].mean()*100:+.3f}%")
    if len(losing_days) > 0:
        print(f"Avg Loss: {losing_days['day_pnl_pct'].mean()*100:+.3f}%")
    
    print(f"\nAvg Daily Return: {daily_df['day_pnl_pct'].mean()*100:+.3f}%")
    print(f"Daily Std Dev: {daily_df['day_pnl_pct'].std()*100:.3f}%")
    print(f"Best Day: {daily_df['day_pnl_pct'].max()*100:+.2f}%")
    print(f"Worst Day: {daily_df['day_pnl_pct'].min()*100:+.2f}%")
    
    if daily_df['day_pnl_pct'].std() > 0:
        sharpe = (daily_df['day_pnl_pct'].mean() / daily_df['day_pnl_pct'].std()) * np.sqrt(252)
        print(f"\nSharpe Ratio: {sharpe:.2f}")
    
    # Drawdown
    daily_df['cumulative'] = (1 + daily_df['day_pnl_pct']).cumprod()
    daily_df['peak'] = daily_df['cumulative'].cummax()
    daily_df['drawdown'] = (daily_df['cumulative'] - daily_df['peak']) / daily_df['peak']
    max_dd = daily_df['drawdown'].min()
    print(f"Max Drawdown: {max_dd*100:.2f}%")
    
    # CAGR
    days = len(daily_df)
    years = days / 252
    if years > 0:
        cagr = (pow(final_capital / initial_capital, 1/years) - 1) * 100
        print(f"CAGR (annualized): {cagr:+.2f}%")
    
    # Signal analysis
    print(f"\n{'='*70}")
    print("SIGNAL ANALYSIS")
    print(f"{'='*70}")
    entries = bar_df[bar_df['signal'] == 'ENTRY']
    exits = bar_df[bar_df['signal'] == 'EXIT']
    print(f"Total Entries: {len(entries)}")
    print(f"Total Exits: {len(exits)}")
    
    kill_switches = len(bar_df[bar_df['signal'] == 'KILL_SWITCH'])
    print(f"Kill Switch Triggers: {kill_switches}")
    
    print(f"\n{'='*70}")
    print("SAMPLE - First Day Trades")
    print(f"{'='*70}")
    first_day = bar_df[bar_df['signal'].isin(['ENTRY', 'EXIT', 'KILL_SWITCH'])].head(10)
    if len(first_day) > 0:
        print(first_day[['timestamp', 'signal', 'mode', 'leverage', 'bar_pnl', 'day_pnl']].to_string(index=False))
    
    return daily_df


if __name__ == "__main__":
    print("="*70)
    print("STRICT BACKTEST - CONSERVATIVE IMPLEMENTATION")
    print("="*70)
    print("\nRules:")
    print("• Single entry → single exit (no intrabar rebalancing)")
    print("• SHORT more defensive than LONG (no anti-churn)")
    print("• Kill switch is HARD STOP")
    print("• PnL only from entry to exit price")
    print("="*70)
    
    try:
        # Fetch data
        print("\nFetching data...")
        smh = fetch_yfinance_intraday("SMH", lookback_days=60)
        soxx = fetch_yfinance_intraday("SOXX", lookback_days=60)
        qqq = fetch_yfinance_intraday("QQQ", lookback_days=60)
        
        vix_ticker = yf.Ticker("^VIX")
        vix_df = vix_ticker.history(period="60d", interval="1d")
        vix_df = vix_df.reset_index()
        
        if vix_df['Date'].dt.tz is None:
            vix_df['date'] = pd.to_datetime(vix_df['Date']).dt.tz_localize(TIMEZONE)
        else:
            vix_df['date'] = pd.to_datetime(vix_df['Date']).dt.tz_convert(TIMEZONE)
        
        vix_df = vix_df[['date', 'Close']].rename(columns={'Close': 'VIX_close'})
        
        if any(df is None for df in [smh, soxx, qqq]):
            print("\n❌ Failed to fetch data")
            exit(1)
        
        # Compute returns
        print("\nComputing returns...")
        smh = compute_intraday_ret(smh)
        soxx = compute_intraday_ret(soxx)
        qqq = compute_intraday_ret(qqq)
        
        # Merge
        data = smh.merge(soxx, on="date", suffixes=("_SMH", "_SOXX"), how='inner')
        data = data.merge(qqq, on="date", how='inner', suffixes=("", "_QQQ"))
        
        data = data.rename(columns={
            "open_SMH": "SMH_open", "close_SMH": "SMH_close",
            "open_SOXX": "SOXX_open", "close_SOXX": "SOXX_close",
            "open": "QQQ_open", "close": "QQQ_close",
            "RET_SMH": "SMH_RET", "RET_SOXX": "SOXX_RET", "RET": "QQQ_RET"
        })
        
        data["LONG_PERSISTENCE_MIN"] = data["LONG_PERSISTENCE_MIN_SMH"]
        data["SHORT_PERSISTENCE_MIN"] = data["SHORT_PERSISTENCE_MIN_SMH"]
        
        data['merge_date'] = data['date'].dt.date
        vix_df['merge_date'] = vix_df['date'].dt.date
        data = data.merge(vix_df[['merge_date', 'VIX_close']], on='merge_date', how='left')
        data['VIX_close'] = data['VIX_close'].ffill()
        data = data.drop('merge_date', axis=1)
        
        print(f"✓ {len(data)} bars ready\n")
        
        # Run strict backtest
        print("Running STRICT backtest...")
        bar_results, daily_results, final_capital = run_backtest_strict(data, initial_capital=100000)
        
        # Analyze
        daily_results = analyze_backtest(bar_results, daily_results, final_capital)
        
        # Save
        bar_results.to_csv("backtest_strict_bars.csv", index=False)
        daily_results.to_csv("backtest_strict_daily.csv", index=False)
        
        print(f"\n{'='*70}")
        print("✓ Files saved: backtest_strict_bars.csv & backtest_strict_daily.csv")
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()