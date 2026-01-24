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


def run_backtest_correct(data, initial_capital=100000):
    """
    CORRECTED backtest with proper position tracking
    
    KEY FIX:
    - Track entry price when opening position
    - Calculate PnL based on current price vs entry price
    - Only realize PnL when position changes or closes
    """
    
    capital = initial_capital
    daily_results = []
    bar_results = []
    
    # Group by day
    for day, day_data in data.groupby(data['date'].dt.date):
        day_start_capital = capital
        day_realized_pnl = 0.0
        
        # State for this day
        state = {
            "mode": "NEUTRAL",
            "pf": 0.0,
            "trading": True,
            "position_open": False,
            "entry_price": 0.0,
            "entry_symbol": None,
            "entry_size": 0.0,
            "current_leverage": 0.0
        }
        
        # Process each bar
        for idx, bar in day_data.iterrows():
            SMH_RET = bar["SMH_RET"]
            SOXX_RET = bar["SOXX_RET"]
            QQQ_RET = bar["QQQ_RET"]
            VIX = bar["VIX_close"]
            LONG_PERSIST = bar["LONG_PERSISTENCE_MIN"]
            SHORT_PERSIST = bar["SHORT_PERSISTENCE_MIN"]
            
            # Kill switch
            if day_realized_pnl / day_start_capital <= DAILY_KILL:
                # Close position if open
                if state["position_open"]:
                    exit_price = bar[f"{state['entry_symbol']}_close"]
                    if state["mode"] == "LONG":
                        pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
                    else:  # SHORT
                        pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
                    day_realized_pnl += pnl
                    state["position_open"] = False
                
                state["trading"] = False
                state["pf"] = 0.0
            
            # Detect mode
            prev_mode = state["mode"]
            if state["trading"]:
                if SMH_RET > 0 and SOXX_RET > 0:
                    state["mode"] = "LONG"
                elif SMH_RET < 0 and SOXX_RET < 0:
                    state["mode"] = "SHORT"
                else:
                    state["mode"] = "NEUTRAL"
                
                if state["mode"] == "NEUTRAL":
                    state["pf"] = 0.0
            
            # Select asset
            if state["mode"] == "LONG":
                asset_ret = max(SMH_RET, SOXX_RET)
                asset_symbol = "SMH" if SMH_RET >= SOXX_RET else "SOXX"
            elif state["mode"] == "SHORT":
                asset_ret = min(SMH_RET, SOXX_RET)
                asset_symbol = "SMH" if SMH_RET <= SOXX_RET else "SOXX"
            else:
                asset_ret = 0.0
                asset_symbol = None
            
            pf = state["pf"]
            
            # Progressive entry
            if state["mode"] == "LONG":
                if asset_ret >= ENTRY_3:
                    pf = 1.0
                elif asset_ret >= ENTRY_2:
                    pf = max(pf, 0.7)
                elif asset_ret >= ENTRY_1:
                    pf = max(pf, 0.5)
            
            if state["mode"] == "SHORT":
                if asset_ret <= -ENTRY_3:
                    pf = 1.0
                elif asset_ret <= -ENTRY_2:
                    pf = max(pf, 0.7)
                elif asset_ret <= -ENTRY_1:
                    pf = max(pf, 0.5)
            
            # Anti-churn
            if state["mode"] == "LONG" and 0.003 <= QQQ_RET <= 0.007 and LONG_PERSIST >= 30:
                pf = max(pf, 0.5)
            if state["mode"] == "SHORT" and -0.007 <= QQQ_RET <= -0.003 and SHORT_PERSIST >= 30:
                pf = max(pf, 0.5)
            
            # Invalidation
            if state["mode"] == "LONG" and asset_ret <= INVALID_ZERO:
                pf = max(pf * 0.5, 0.0)
            if state["mode"] == "SHORT" and asset_ret >= INVALID_ZERO:
                pf = max(pf * 0.5, 0.0)
            
            if state["mode"] == "LONG" and asset_ret <= -HARD_EXIT:
                pf = 0.0
            if state["mode"] == "SHORT" and asset_ret >= HARD_EXIT:
                pf = 0.0
            
            # Leverage (CONSERVATIVE)
            base_leverage = 0.0
            if state["mode"] == "LONG":
                if VIX < 12:
                    base_leverage = 2.0
                elif VIX < 15:
                    base_leverage = 1.5
                else:
                    base_leverage = 1.0
            
            if state["mode"] == "SHORT":
                if VIX < 20:
                    base_leverage = 1.0
                elif VIX < 25:
                    base_leverage = 1.5
                else:
                    base_leverage = 2.0
            
            target_leverage = base_leverage * pf
            state["pf"] = pf
            
            # CRITICAL: Position Management Logic
            bar_pnl = 0.0
            unrealized_pnl = 0.0
            
            # Calculate unrealized PnL if position is open
            if state["position_open"]:
                current_price = bar[f"{state['entry_symbol']}_close"]
                if state["mode"] == "LONG":
                    unrealized_pnl = state["entry_size"] * (current_price - state["entry_price"]) / state["entry_price"]
                else:  # SHORT
                    unrealized_pnl = state["entry_size"] * (state["entry_price"] - current_price) / state["entry_price"]
            
            # Check if we need to close or adjust position
            mode_changed = prev_mode != state["mode"]
            symbol_changed = asset_symbol != state["entry_symbol"]
            leverage_changed = abs(target_leverage - state["current_leverage"]) > 0.1
            should_close = pf == 0.0 or mode_changed or symbol_changed
            
            # Close existing position if needed
            if state["position_open"] and should_close:
                # Realize PnL
                bar_pnl = unrealized_pnl
                day_realized_pnl += bar_pnl
                state["position_open"] = False
                unrealized_pnl = 0.0
            
            # Open new position or adjust size
            if pf > 0 and asset_symbol and state["trading"]:
                if not state["position_open"] or leverage_changed:
                    # Close old position if resizing
                    if state["position_open"]:
                        bar_pnl = unrealized_pnl
                        day_realized_pnl += bar_pnl
                        unrealized_pnl = 0.0
                    
                    # Open new position at current prices
                    current_capital = day_start_capital + day_realized_pnl
                    state["entry_price"] = bar[f"{asset_symbol}_close"]
                    state["entry_symbol"] = asset_symbol
                    state["entry_size"] = current_capital * target_leverage
                    state["current_leverage"] = target_leverage
                    state["position_open"] = True
            
            # Store bar result
            bar_results.append({
                'timestamp': bar['date'],
                'day': day,
                'mode': state['mode'],
                'position_fraction': pf,
                'leverage': target_leverage,
                'asset_symbol': asset_symbol,
                'asset_intraday_ret': asset_ret,
                'position_open': state['position_open'],
                'entry_price': state['entry_price'] if state['position_open'] else 0,
                'current_price': bar[f"{asset_symbol}_close"] if asset_symbol else 0,
                'position_size': state['entry_size'] if state['position_open'] else 0,
                'bar_realized_pnl': bar_pnl,
                'unrealized_pnl': unrealized_pnl,
                'day_realized_pnl': day_realized_pnl,
                'day_total_pnl': day_realized_pnl + unrealized_pnl,
                'vix': VIX
            })
        
        # End of day: close any open positions
        if state["position_open"]:
            last_bar = day_data.iloc[-1]
            exit_price = last_bar[f"{state['entry_symbol']}_close"]
            if state["mode"] == "LONG":
                final_pnl = state["entry_size"] * (exit_price - state["entry_price"]) / state["entry_price"]
            else:
                final_pnl = state["entry_size"] * (state["entry_price"] - exit_price) / state["entry_price"]
            day_realized_pnl += final_pnl
        
        # Update capital
        end_day_capital = day_start_capital + day_realized_pnl
        daily_return = day_realized_pnl / day_start_capital
        
        daily_results.append({
            'date': day,
            'start_capital': day_start_capital,
            'pnl_dollars': day_realized_pnl,
            'pnl_pct': daily_return,
            'end_capital': end_day_capital
        })
        
        capital = end_day_capital
    
    return pd.DataFrame(bar_results), pd.DataFrame(daily_results), capital


def analyze_backtest(bar_df, daily_df, final_capital, initial_capital=100000):
    """Comprehensive analysis"""
    
    print("\n" + "="*70)
    print("CORRECTED BACKTEST RESULTS")
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
    
    winning_days = daily_df[daily_df['pnl_pct'] > 0]
    losing_days = daily_df[daily_df['pnl_pct'] < 0]
    flat_days = daily_df[daily_df['pnl_pct'] == 0]
    
    print(f"Winning Days: {len(winning_days)} ({len(winning_days)/len(daily_df)*100:.1f}%)")
    print(f"Losing Days: {len(losing_days)} ({len(losing_days)/len(daily_df)*100:.1f}%)")
    print(f"Flat Days: {len(flat_days)} ({len(flat_days)/len(daily_df)*100:.1f}%)")
    
    print(f"\nAvg Daily Return: {daily_df['pnl_pct'].mean()*100:+.3f}%")
    print(f"Daily Std Dev: {daily_df['pnl_pct'].std()*100:.3f}%")
    print(f"Best Day: {daily_df['pnl_pct'].max()*100:+.2f}%")
    print(f"Worst Day: {daily_df['pnl_pct'].min()*100:+.2f}%")
    
    if daily_df['pnl_pct'].std() > 0:
        sharpe = (daily_df['pnl_pct'].mean() / daily_df['pnl_pct'].std()) * np.sqrt(252)
        print(f"\nSharpe Ratio: {sharpe:.2f}")
    
    # Drawdown
    daily_df['cumulative'] = (1 + daily_df['pnl_pct']).cumprod()
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
    
    print(f"\n{'='*70}")
    print("FIRST DAY SAMPLE (Manual Verification)")
    print(f"{'='*70}")
    first_day = bar_df.head(15)[['timestamp', 'mode', 'position_fraction', 'leverage', 
                                  'position_open', 'bar_realized_pnl', 'unrealized_pnl', 
                                  'day_realized_pnl', 'day_total_pnl']]
    print(first_day.to_string(index=False))
    
    return daily_df


if __name__ == "__main__":
    print("="*70)
    print("CORRECTED BACKTEST - PROPER POSITION TRACKING")
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
        
        # Run corrected backtest
        print("Running CORRECTED backtest...")
        bar_results, daily_results, final_capital = run_backtest_correct(data, initial_capital=100000)
        
        # Analyze
        daily_results = analyze_backtest(bar_results, daily_results, final_capital)
        
        # Save
        bar_results.to_csv("backtest_corrected_bars.csv", index=False)
        daily_results.to_csv("backtest_corrected_daily.csv", index=False)
        
        print(f"\n{'='*70}")
        print("✓ Files saved: backtest_corrected_bars.csv & backtest_corrected_daily.csv")
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()