from polygon import RESTClient
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta
import time
import json

# ================== CONFIG ==================
POLYGON_API_KEY = ""  # ← PUT YOUR KEY HERE

BAR_SIZE = "5"  # 5 minute bars
TIMEZONE = pytz.timezone("America/New_York")

ENTRY_1 = 0.0012
ENTRY_2 = 0.0020
ENTRY_3 = 0.0030
INVALID_ZERO = 0.0
HARD_EXIT = 0.002
DAILY_KILL = -0.025

# ============================================

def fetch_polygon_intraday(symbol, start_date, end_date, api_key):
    """Fetch 5-minute intraday data from Polygon.io"""
    print(f"\nFetching {symbol} from Polygon.io...")
    
    client = RESTClient(api_key)
    all_bars = []
    
    # Polygon free tier: max 2 years back
    current_start = start_date
    
    while current_start < end_date:
        # Fetch one day at a time to manage rate limits
        current_end = min(current_start + timedelta(days=1), end_date)
        
        try:
            # Format dates for Polygon API
            from_date = current_start.strftime('%Y-%m-%d')
            to_date = current_end.strftime('%Y-%m-%d')
            
            print(f"  {from_date}", end="", flush=True)
            
            # Request aggregates (bars)
            aggs = client.get_aggs(
                ticker=symbol,
                multiplier=5,
                timespan="minute",
                from_=from_date,
                to=to_date,
                limit=50000
            )
            
            if aggs:
                for agg in aggs:
                    # Convert timestamp (ms) to datetime
                    dt = pd.to_datetime(agg.timestamp, unit='ms', utc=True).tz_convert(TIMEZONE)
                    
                    # Only include regular trading hours (9:30 AM - 4:00 PM ET)
                    hour = dt.hour
                    minute = dt.minute
                    
                    if (hour == 9 and minute >= 30) or (10 <= hour < 16) or (hour == 16 and minute == 0):
                        all_bars.append({
                            'date': dt,
                            'open': agg.open,
                            'high': agg.high,
                            'low': agg.low,
                            'close': agg.close,
                            'volume': agg.volume
                        })
                
                print(" ✓", end="")
            else:
                print(" -", end="")
            
            # Rate limiting: 5 calls/minute for free tier
            time.sleep(12)  # 12 seconds = 5 calls per minute
            
        except Exception as e:
            print(f" ✗ Error: {e}")
        
        current_start = current_end
    
    print()  # New line
    
    if not all_bars:
        print(f"  ❌ No data retrieved for {symbol}")
        return None
    
    df = pd.DataFrame(all_bars)
    df = df.sort_values('date').reset_index(drop=True)
    
    print(f"  ✓ Total: {len(df)} bars across {df['date'].dt.date.nunique()} days")
    return df


def compute_intraday_ret(df):
    """Calculate intraday returns from day's open"""
    df = df.copy()
    df["day"] = df["date"].dt.date
    df["day_open"] = df.groupby("day")["open"].transform("first")
    df["RET"] = (df["close"] - df["day_open"]) / df["day_open"]
    
    # Calculate persistence (minutes in same direction)
    df["positive"] = df["RET"] > 0
    df["negative"] = df["RET"] < 0
    
    # Cumulative count of consecutive positives/negatives per day
    df["pos_streak"] = df.groupby(["day", (df["positive"] != df["positive"].shift()).cumsum()])["positive"].cumsum() * 5
    df["neg_streak"] = df.groupby(["day", (df["negative"] != df["negative"].shift()).cumsum()])["negative"].cumsum() * 5
    
    df["LONG_PERSISTENCE_MIN"] = df["pos_streak"]
    df["SHORT_PERSISTENCE_MIN"] = df["neg_streak"]
    
    return df


def run_backtest(data):
    """Run the complete strategy backtest"""
    state = {
        "mode": "NEUTRAL",
        "pf": 0.0,
        "trading": True,
        "daily_pnl": 0.0,
        "current_day": None,
        "daily_bars": []
    }
    
    rows = []
    
    for idx, r in data.iterrows():
        day = r["date"].date()
        
        # Daily reset
        if state["current_day"] != day:
            state["current_day"] = day
            state["daily_pnl"] = 0.0
            state["trading"] = True
            state["pf"] = 0.0
            state["mode"] = "NEUTRAL"
            state["daily_bars"] = []
        
        SMH_RET = r["SMH_RET"]
        SOXX_RET = r["SOXX_RET"]
        QQQ_RET = r["QQQ_RET"]
        VIX = r["VIX_close"]
        LONG_PERSIST = r["LONG_PERSISTENCE_MIN"]
        SHORT_PERSIST = r["SHORT_PERSISTENCE_MIN"]
        
        # Kill switch
        if state["daily_pnl"] <= DAILY_KILL:
            state["trading"] = False
            state["pf"] = 0.0
        
        # Detect mode
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
        elif state["mode"] == "SHORT":
            asset_ret = min(SMH_RET, SOXX_RET)
        else:
            asset_ret = 0.0
        
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
        
        # Anti-churn policy
        if state["mode"] == "LONG" and 0.003 <= QQQ_RET <= 0.007 and LONG_PERSIST >= 30:
            pf = max(pf, 0.5)  # Keep at least 50% position
        
        if state["mode"] == "SHORT" and -0.007 <= QQQ_RET <= -0.003 and SHORT_PERSIST >= 30:
            pf = max(pf, 0.5)  # Keep at least 50% position
        
        # Invalidation / hard exit
        if state["mode"] == "LONG" and asset_ret <= INVALID_ZERO:
            pf = max(pf * 0.5, 0.0)
        if state["mode"] == "SHORT" and asset_ret >= INVALID_ZERO:
            pf = max(pf * 0.5, 0.0)
        
        if state["mode"] == "LONG" and asset_ret <= -HARD_EXIT:
            pf = 0.0
        if state["mode"] == "SHORT" and asset_ret >= HARD_EXIT:
            pf = 0.0
        
        # Leverage based on VIX
        leverage = 0.0
        if state["mode"] == "LONG":
            if VIX < 12:
                base = 4.0
            elif VIX < 15:
                base = 3.0
            elif VIX < 20:
                base = 2.0
            else:
                base = 2.0
            leverage = base * pf
        
        if state["mode"] == "SHORT":
            if VIX < 20:
                base = 2.0
            elif VIX < 25:
                base = 4.0
            else:
                base = 5.0
            leverage = base * pf
        
        state["pf"] = pf
        
        # Calculate bar PnL (simplified)
        bar_pnl = asset_ret * pf * leverage if pf > 0 else 0.0
        state["daily_pnl"] += bar_pnl
        
        rows.append({
            "timestamp": r["date"],
            "mode": state["mode"],
            "position_fraction": pf,
            "leverage": leverage,
            "asset_ret": asset_ret,
            "bar_pnl": bar_pnl,
            "daily_pnl": state["daily_pnl"],
            "smh_ret": SMH_RET,
            "soxx_ret": SOXX_RET,
            "qqq_ret": QQQ_RET,
            "vix": VIX,
            "long_persist_min": LONG_PERSIST,
            "short_persist_min": SHORT_PERSIST
        })
    
    return pd.DataFrame(rows)


def analyze_results(results):
    """Analyze backtest results"""
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    
    # Daily aggregation
    daily = results.groupby(results['timestamp'].dt.date).agg({
        'daily_pnl': 'last',
        'mode': lambda x: x.mode()[0] if len(x.mode()) > 0 else 'NEUTRAL',
        'leverage': 'mean'
    }).reset_index()
    daily.columns = ['date', 'daily_ret', 'primary_mode', 'avg_leverage']
    
    # Calculate cumulative returns
    daily['cumulative'] = (1 + daily['daily_ret']).cumprod()
    
    print(f"\nTotal Trading Days: {len(daily)}")
    print(f"Date Range: {daily['date'].min()} to {daily['date'].max()}")
    
    # Annual returns
    daily['year'] = pd.to_datetime(daily['date']).dt.year
    print(f"\n=== Annual Returns ===")
    for year in sorted(daily['year'].unique()):
        year_data = daily[daily['year'] == year]
        year_ret = (1 + year_data['daily_ret']).prod() - 1
        print(f"  {year}: {year_ret*100:+.2f}%")
    
    # Overall metrics
    total_ret = daily['cumulative'].iloc[-1] - 1
    daily_sharpe = daily['daily_ret'].mean() / daily['daily_ret'].std() if daily['daily_ret'].std() > 0 else 0
    annual_sharpe = daily_sharpe * np.sqrt(252)
    
    max_dd = ((daily['cumulative'].cummax() - daily['cumulative']) / daily['cumulative'].cummax()).max()
    
    print(f"\n=== Overall Performance ===")
    print(f"  Total Return: {total_ret*100:+.2f}%")
    print(f"  CAGR: {(daily['cumulative'].iloc[-1] ** (252/len(daily)) - 1)*100:.2f}%")
    print(f"  Max Drawdown: {max_dd*100:.2f}%")
    print(f"  Sharpe Ratio (Annual): {annual_sharpe:.2f}")
    print(f"  Win Rate: {len(daily[daily['daily_ret']>0])/len(daily)*100:.2f}%")
    print(f"  Avg Win: {daily[daily['daily_ret']>0]['daily_ret'].mean()*100:.3f}%")
    print(f"  Avg Loss: {daily[daily['daily_ret']<0]['daily_ret'].mean()*100:.3f}%")
    
    print(f"\n=== Mode Distribution ===")
    mode_counts = daily['primary_mode'].value_counts()
    for mode, count in mode_counts.items():
        print(f"  {mode}: {count} days ({count/len(daily)*100:.1f}%)")
    
    print(f"\n=== Leverage Statistics ===")
    print(f"  Avg Daily Leverage: {daily['avg_leverage'].mean():.2f}x")
    print(f"  Max Daily Leverage: {daily['avg_leverage'].max():.2f}x")
    
    return daily


if __name__ == "__main__":
    print("="*60)
    print("POLYGON.IO INTRADAY BACKTEST")
    print("="*60)
    
    # Check API key
    if POLYGON_API_KEY == "YOUR_API_KEY_HERE":
        print("\n❌ ERROR: Please set your Polygon.io API key!")
        print("   1. Sign up at https://polygon.io/")
        print("   2. Get your API key from dashboard")
        print("   3. Replace 'YOUR_API_KEY_HERE' in the code")
        exit(1)
    
    # Date range (Polygon free tier: 2 years max)
    end_date = datetime.now()
    start_date = datetime(2024, 1, 1)  # Start from 2024 for free tier
    
    print(f"\nPeriod: {start_date.date()} to {end_date.date()}")
    print(f"Note: Free tier limited to last 2 years")
    print("This will take 10-20 minutes due to rate limiting...")
    print("="*60)
    
    try:
        # Fetch intraday data
        smh = fetch_polygon_intraday("SMH", start_date, end_date, POLYGON_API_KEY)
        soxx = fetch_polygon_intraday("SOXX", start_date, end_date, POLYGON_API_KEY)
        qqq = fetch_polygon_intraday("QQQ", start_date, end_date, POLYGON_API_KEY)
        
        # Fetch VIX daily
        print("\nFetching VIX (daily)...")
        import yfinance as yf
        vix_ticker = yf.Ticker("^VIX")
        vix_df = vix_ticker.history(start=start_date, end=end_date, interval="1d")
        vix_df = vix_df.reset_index()
        vix_df['date'] = pd.to_datetime(vix_df['Date']).dt.tz_localize(TIMEZONE)
        vix_df = vix_df[['date', 'Close']].rename(columns={'Close': 'VIX_close'})
        print(f"  ✓ {len(vix_df)} days")
        
        if any(df is None for df in [smh, soxx, qqq]):
            print("\n❌ Failed to fetch all data")
            exit(1)
        
        # Compute returns
        print("\nComputing intraday returns...")
        smh = compute_intraday_ret(smh)
        soxx = compute_intraday_ret(soxx)
        qqq = compute_intraday_ret(qqq)
        
        # Merge datasets
        print("Merging datasets...")
        data = smh.merge(soxx, on="date", suffixes=("_SMH", "_SOXX"))
        data = data.merge(qqq, on="date")
        
        # Merge VIX (daily to intraday - forward fill)
        data['merge_date'] = data['date'].dt.date
        vix_df['merge_date'] = vix_df['date'].dt.date
        data = data.merge(vix_df[['merge_date', 'VIX_close']], on='merge_date', how='left')
        data['VIX_close'] = data['VIX_close'].fillna(method='ffill')
        data = data.drop('merge_date', axis=1)
        
        # Rename columns
        data = data.rename(columns={
            "RET_SMH": "SMH_RET",
            "RET_SOXX": "SOXX_RET",
            "RET": "QQQ_RET",
            "LONG_PERSISTENCE_MIN_SMH": "LONG_PERSISTENCE_MIN",
            "SHORT_PERSISTENCE_MIN_SMH": "SHORT_PERSISTENCE_MIN"
        })
        
        print(f"✓ {len(data)} bars ready for backtest")
        
        # Run backtest
        print("\nRunning backtest...")
        results = run_backtest(data)
        
        # Analyze
        daily_results = analyze_results(results)
        
        # Save
        results.to_csv("backtest_intraday_full.csv", index=False)
        daily_results.to_csv("backtest_daily_summary.csv", index=False)
        print(f"\n✓ Saved detailed results to backtest_intraday_full.csv")
        print(f"✓ Saved daily summary to backtest_daily_summary.csv")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()