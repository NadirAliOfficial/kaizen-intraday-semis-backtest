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


def run_backtest_progressive_short(data, initial_capital=100000):
    """
    CORRECTED SHORT LOGIC with progressive reduction
    
    Key fix:
    - SHORTs progressively REDUCE (not exit) when price moves toward zero
    - position_fraction = position_fraction * 0.5 (as per spec)
    - Only hard exit at HARD_EXIT threshold
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
            "current_pf": 0.0,  # Track current position fraction
            "current_leverage": 0.0
        }
        
        prev_bar = None
        
        # Process each bar
        for idx, bar in day_data.iterrows():
            
            # Skip first bar
            if prev_bar is None:
                prev_bar = bar
                bar_results.append({
                    'timestamp': bar['date'],
                    'day': day,
                    'action': 'WAIT',
                    'mode': 'NEUTRAL',
                    'position_open': False,
                    'pf': 0,
                    'leverage': 0,
                    'bar_pnl': 0,
                    'day_pnl': 0,
                    'capital': capital
                })
                continue
            
            # Check kill switch
            if day_pnl / day_start_capital <= DAILY_KILL:
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
                    'action': 'KILL_SWITCH',
                    'mode': 'NEUTRAL',
                    'position_open': False,
                    'pf': 0,
                    'leverage': 0,
                    'bar_pnl': pnl if 'pnl' in locals() else 0,
                    'day_pnl': day_pnl,
                    'capital': day_start_capital + day_pnl
                })
                continue
            
            if not state["trading_enabled"]:
                bar_results.append({
                    'timestamp': bar['date'],
                    'day': day,
                    'action': 'DISABLED',
                    'mode': 'NEUTRAL',
                    'position_open': False,
                    'pf': 0,
                    'leverage': 0,
                    'bar_pnl': 0,
                    'day_pnl': day_pnl,
                    'capital': day_start_capital + day_pnl
                })
                continue
            
            # Use PREVIOUS bar for signals
            SMH_RET = prev_bar["SMH_RET"]
            SOXX_RET = prev_bar["SOXX_RET"]
            QQQ_RET = prev_bar["QQQ_RET"]
            VIX = prev_bar["VIX_close"]
            LONG_PERSIST = prev_bar["LONG_PERSISTENCE_MIN"]
            
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
            
            # Calculate target position fraction
            target_pf = 0.0
            
            if signal_mode == "LONG":
                # LONG progressive entry
                if asset_ret >= ENTRY_3:
                    target_pf = 1.0
                elif asset_ret >= ENTRY_2:
                    target_pf = 0.7
                elif asset_ret >= ENTRY_1:
                    target_pf = 0.5
                
                # Anti-churn for LONG
                if 0.003 <= QQQ_RET <= 0.007 and LONG_PERSIST >= 30:
                    target_pf = max(target_pf, 0.5)
                
                # LONG invalidation - PROGRESSIVE REDUCTION
                if state["position_open"] and state["entry_mode"] == "LONG":
                    if asset_ret <= INVALID_ZERO:
                        # Reduce by 50%
                        target_pf = state["current_pf"] * 0.5
                    if asset_ret <= -HARD_EXIT:
                        # Hard exit
                        target_pf = 0.0
            
            elif signal_mode == "SHORT":
                # SHORT progressive entry
                if asset_ret <= -ENTRY_3:
                    target_pf = 1.0
                elif asset_ret <= -ENTRY_2:
                    target_pf = 0.7
                elif asset_ret <= -ENTRY_1:
                    target_pf = 0.5
                
                # NO anti-churn for SHORT
                
                # SHORT invalidation - PROGRESSIVE REDUCTION (KEY FIX)
                if state["position_open"] and state["entry_mode"] == "SHORT":
                    if asset_ret >= INVALID_ZERO:
                        # Reduce by 50% (NOT full exit)
                        target_pf = state["current_pf"] * 0.5
                    if asset_ret >= HARD_EXIT:
                        # Hard exit only at threshold
                        target_pf = 0.0
            
            # Calculate leverage
            if signal_mode == "LONG" and target_pf > 0:
                if VIX < 12:
                    base_lev = 4.0
                elif VIX < 15:
                    base_lev = 3.0
                elif VIX < 20:
                    base_lev = 2.0
                else:
                    base_lev = 2.0
                target_leverage = base_lev * target_pf
            elif signal_mode == "SHORT" and target_pf > 0:
                if VIX < 20:
                    base_lev = 2.0
                elif VIX < 25:
                    base_lev = 4.0
                else:
                    base_lev = 5.0
                target_leverage = base_lev * target_pf
            else:
                target_leverage = 0.0
            
            # Position management
            bar_pnl = 0.0
            action = "HOLD"
            
            # Determine if we need to change position
            should_exit = False
            should_resize = False
            
            if state["position_open"]:
                # Exit if mode changed
                if signal_mode != state["entry_mode"]:
                    should_exit = True
                # Exit if asset switched
                elif asset_symbol != state["entry_symbol"]:
                    should_exit = True
                # Exit if target is zero
                elif target_pf == 0.0:
                    should_exit = True
                # Resize if leverage changed significantly
                elif abs(target_leverage - state["current_leverage"]) > 0.3:
                    should_resize = True
            
            # Execute exit
            if state["position_open"] and should_exit:
                exit_price = bar[f"{state['entry_symbol']}_open"]
                if state["entry_mode"] == "LONG":
                    bar_pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
                else:
                    bar_pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
                
                day_pnl += bar_pnl
                state["position_open"] = False
                state["current_pf"] = 0.0
                action = "EXIT"
            
            # Execute resize (close and reopen with new size)
            elif state["position_open"] and should_resize:
                # Close existing
                exit_price = bar[f"{state['entry_symbol']}_open"]
                if state["entry_mode"] == "LONG":
                    bar_pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
                else:
                    bar_pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
                
                day_pnl += bar_pnl
                
                # Reopen with new size
                current_capital = day_start_capital + day_pnl
                state["entry_price"] = bar[f"{asset_symbol}_open"]
                state["entry_symbol"] = asset_symbol
                state["entry_mode"] = signal_mode
                state["entry_size"] = current_capital * target_leverage
                state["current_pf"] = target_pf
                state["current_leverage"] = target_leverage
                state["position_open"] = True
                action = "RESIZE"
            
            # Execute entry (only if not in position)
            elif not state["position_open"] and target_pf > 0 and signal_mode != "NEUTRAL":
                current_capital = day_start_capital + day_pnl
                state["entry_price"] = bar[f"{asset_symbol}_open"]
                state["entry_symbol"] = asset_symbol
                state["entry_mode"] = signal_mode
                state["entry_size"] = current_capital * target_leverage
                state["current_pf"] = target_pf
                state["current_leverage"] = target_leverage
                state["position_open"] = True
                action = "ENTRY"
            
            # Calculate unrealized PnL
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
                'action': action,
                'mode': signal_mode,
                'position_open': state["position_open"],
                'pf': target_pf,
                'leverage': target_leverage,
                'entry_price': state["entry_price"] if state["position_open"] else 0,
                'current_price': bar[f"{asset_symbol}_close"] if asset_symbol else 0,
                'bar_pnl': bar_pnl,
                'unrealized_pnl': unrealized,
                'day_pnl': day_pnl,
                'day_total': day_pnl + unrealized,
                'capital': day_start_capital + day_pnl
            })
            
            prev_bar = bar
        
        # End of day - force close
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
    print("CORRECTED SHORT LOGIC - PROGRESSIVE REDUCTION")
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
    
    # Action analysis
    print(f"\n{'='*70}")
    print("ACTION ANALYSIS")
    print(f"{'='*70}")
    action_counts = bar_df['action'].value_counts()
    for action, count in action_counts.items():
        print(f"  {action}: {count}")
    
    # Mode analysis
    long_bars = bar_df[bar_df['mode'] == 'LONG']
    short_bars = bar_df[bar_df['mode'] == 'SHORT']
    
    if len(long_bars) > 0:
        long_trades = bar_df[(bar_df['mode'] == 'LONG') & (bar_df['action'].isin(['ENTRY', 'EXIT', 'RESIZE']))]
        print(f"\nLONG trades: {len(long_trades)}")
    
    if len(short_bars) > 0:
        short_trades = bar_df[(bar_df['mode'] == 'SHORT') & (bar_df['action'].isin(['ENTRY', 'EXIT', 'RESIZE']))]
        print(f"SHORT trades: {len(short_trades)}")
    
    print(f"\n{'='*70}")
    print("SAMPLE - First Day Activity")
    print(f"{'='*70}")
    first_day = bar_df[bar_df['action'].isin(['ENTRY', 'EXIT', 'RESIZE', 'KILL_SWITCH'])].head(15)
    if len(first_day) > 0:
        print(first_day[['timestamp', 'action', 'mode', 'pf', 'leverage', 'bar_pnl', 'day_pnl']].to_string(index=False))
    
    return daily_df


if __name__ == "__main__":
    print("="*70)
    print("CORRECTED BACKTEST - PROGRESSIVE SHORT REDUCTION")
    print("="*70)
    print("\nKey Fix:")
    print("• SHORTs now REDUCE by 50% (not exit) when price moves to zero")
    print("• Progressive invalidation: pf = pf * 0.5")
    print("• Hard exit only at HARD_EXIT threshold")
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
        
        # Run backtest
        print("Running backtest with corrected SHORT logic...")
        bar_results, daily_results, final_capital = run_backtest_progressive_short(data, initial_capital=100000)
        
        # Analyze
        daily_results = analyze_backtest(bar_results, daily_results, final_capital)
        
        # Save
        bar_results.to_csv("backtest_progressive_short_bars.csv", index=False)
        daily_results.to_csv("backtest_progressive_short_daily.csv", index=False)
        
        print(f"\n{'='*70}")
        print("✓ Files saved")
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()