import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# ================== CONFIG ==================
TIMEZONE = pytz.timezone("America/New_York")

ENTRY_1 = 0.0012
ENTRY_2 = 0.0020
ENTRY_3 = 0.0030
INVALID_ZERO = 0.0
HARD_EXIT = 0.002
DAILY_KILL = -0.025

# ============================================

def fetch_daily_data(symbol, start_date, end_date):
    """Fetch daily data from Yahoo Finance"""
    print(f"Fetching {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date, interval="1d")
        
        if df.empty:
            print(f"  ❌ No data for {symbol}")
            return None
        
        df = df.reset_index()
        df = df.rename(columns={'Date': 'date', 'Open': 'open', 'Close': 'close'})
        
        if df['date'].dt.tz is None:
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(TIMEZONE)
        else:
            df['date'] = pd.to_datetime(df['date']).dt.tz_convert(TIMEZONE)
        
        print(f"  ✓ {len(df)} days")
        return df[['date', 'open', 'close']]
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def compute_daily_ret(df):
    """Calculate daily returns from open to close"""
    df = df.copy()
    df["RET"] = (df["close"] - df["open"]) / df["open"]
    return df


def run_backtest(data):
    rows = []
    
    for _, r in data.iterrows():
        SMH_RET = r["SMH_RET"]
        SOXX_RET = r["SOXX_RET"]
        QQQ_RET = r["QQQ_RET"]
        VIX = r["VIX_close"]
        
        # Detect mode
        if SMH_RET > 0 and SOXX_RET > 0:
            mode = "LONG"
        elif SMH_RET < 0 and SOXX_RET < 0:
            mode = "SHORT"
        else:
            mode = "NEUTRAL"
        
        if mode == "NEUTRAL":
            pf = 0.0
            asset_ret = 0.0
        else:
            asset_ret = max(SMH_RET, SOXX_RET) if mode == "LONG" else min(SMH_RET, SOXX_RET)
            
            # Progressive entry
            pf = 0.0
            if mode == "LONG":
                if asset_ret >= ENTRY_3:
                    pf = 1.0
                elif asset_ret >= ENTRY_2:
                    pf = 0.7
                elif asset_ret >= ENTRY_1:
                    pf = 0.5
            
            if mode == "SHORT":
                if asset_ret <= -ENTRY_3:
                    pf = 1.0
                elif asset_ret <= -ENTRY_2:
                    pf = 0.7
                elif asset_ret <= -ENTRY_1:
                    pf = 0.5
            
            # Invalidation / hard exit
            if mode == "LONG" and asset_ret <= INVALID_ZERO:
                pf *= 0.5
            if mode == "SHORT" and asset_ret >= INVALID_ZERO:
                pf *= 0.5
            
            if mode == "LONG" and asset_ret <= -HARD_EXIT:
                pf = 0.0
            if mode == "SHORT" and asset_ret >= HARD_EXIT:
                pf = 0.0
        
        # Leverage based on VIX
        leverage = 0.0
        if mode == "LONG":
            base = 4.0 if VIX < 12 else 3.0 if VIX < 15 else 2.0
            leverage = base * pf
        
        if mode == "SHORT":
            base = 2.0 if VIX < 20 else 4.0 if VIX < 25 else 5.0
            leverage = base * pf
        
        rows.append({
            "date": r["date"],
            "mode": mode,
            "position_fraction": pf,
            "leverage": leverage,
            "asset_ret": asset_ret,
            "smh_ret": SMH_RET,
            "soxx_ret": SOXX_RET,
            "qqq_ret": QQQ_RET,
            "vix": VIX
        })
    
    return pd.DataFrame(rows)


def analyze_results(results):
    """Deep dive analysis of backtest results"""
    
    # Calculate strategy returns
    results['strategy_ret'] = results['asset_ret'] * results['position_fraction'] * results['leverage']
    results['cumulative_ret'] = (1 + results['strategy_ret']).cumprod()
    
    print("\n" + "="*60)
    print("DETAILED ANALYSIS")
    print("="*60)
    
    # By mode analysis
    print("\n=== Performance by Mode ===")
    for mode in ['LONG', 'SHORT', 'NEUTRAL']:
        mode_data = results[results['mode'] == mode]
        if len(mode_data) > 0:
            avg_ret = mode_data['strategy_ret'].mean() * 100
            total_ret = ((1 + mode_data['strategy_ret']).prod() - 1) * 100
            win_rate = len(mode_data[mode_data['strategy_ret'] > 0]) / len(mode_data) * 100
            print(f"\n  {mode}:")
            print(f"    Days: {len(mode_data)}")
            print(f"    Avg Daily: {avg_ret:.3f}%")
            print(f"    Total: {total_ret:.2f}%")
            print(f"    Win Rate: {win_rate:.2f}%")
            print(f"    Avg Leverage: {mode_data['leverage'].mean():.2f}x")
    
    # Leverage analysis
    print("\n=== Performance by Leverage Level ===")
    for lev in sorted(results['leverage'].unique()):
        if lev > 0:
            lev_data = results[results['leverage'] == lev]
            avg_ret = lev_data['strategy_ret'].mean() * 100
            win_rate = len(lev_data[lev_data['strategy_ret'] > 0]) / len(lev_data) * 100
            print(f"  {lev:.1f}x: {len(lev_data)} days, avg={avg_ret:.3f}%, win rate={win_rate:.2f}%")
    
    # VIX regime analysis
    print("\n=== Performance by VIX Regime ===")
    bins = [0, 15, 20, 25, 100]
    labels = ['<15 (low)', '15-20', '20-25', '>25 (high)']
    results['vix_regime'] = pd.cut(results['vix'], bins=bins, labels=labels)
    
    for regime in labels:
        regime_data = results[results['vix_regime'] == regime]
        if len(regime_data) > 0:
            avg_ret = regime_data['strategy_ret'].mean() * 100
            win_rate = len(regime_data[regime_data['strategy_ret'] > 0]) / len(regime_data) * 100
            print(f"  {regime}: {len(regime_data)} days, avg={avg_ret:.3f}%, win rate={win_rate:.2f}%")
    
    # Worst days
    print("\n=== Top 10 Worst Days ===")
    worst = results.nsmallest(10, 'strategy_ret')[['date', 'mode', 'leverage', 'asset_ret', 'strategy_ret', 'vix']]
    worst['date'] = worst['date'].dt.date
    worst['asset_ret'] = worst['asset_ret'] * 100
    worst['strategy_ret'] = worst['strategy_ret'] * 100
    print(worst.to_string(index=False))
    
    # Best days
    print("\n=== Top 10 Best Days ===")
    best = results.nlargest(10, 'strategy_ret')[['date', 'mode', 'leverage', 'asset_ret', 'strategy_ret', 'vix']]
    best['date'] = best['date'].dt.date
    best['asset_ret'] = best['asset_ret'] * 100
    best['strategy_ret'] = best['strategy_ret'] * 100
    print(best.to_string(index=False))
    
    # Monthly analysis
    print("\n=== Monthly Performance ===")
    results['year_month'] = results['date'].dt.to_period('M')
    monthly = results.groupby('year_month').agg({
        'strategy_ret': lambda x: ((1 + x).prod() - 1) * 100,
        'date': 'count'
    }).rename(columns={'strategy_ret': 'return_%', 'date': 'days'})
    print(monthly.tail(12).to_string())
    
    return results


if __name__ == "__main__":
    print("="*60)
    print("ENHANCED BACKTEST ANALYSIS")
    print("="*60)
    
    start_date = datetime(2022, 1, 1)
    end_date = datetime.now()
    
    print(f"\nPeriod: {start_date.date()} to {end_date.date()}")
    print("="*60)
    print()
    
    # Fetch data
    smh = fetch_daily_data("SMH", start_date, end_date)
    soxx = fetch_daily_data("SOXX", start_date, end_date)
    qqq = fetch_daily_data("QQQ", start_date, end_date)
    vix = fetch_daily_data("^VIX", start_date, end_date)
    
    if any(df is None for df in [smh, soxx, qqq, vix]):
        print("\n❌ Failed to fetch data")
        exit(1)
    
    # Compute returns
    print("\nComputing returns...")
    smh = compute_daily_ret(smh)
    soxx = compute_daily_ret(soxx)
    qqq = compute_daily_ret(qqq)
    
    # Rename VIX close column before merging
    vix = vix.rename(columns={'close': 'VIX_close'})
    
    # Merge
    print("Merging datasets...")
    data = smh.merge(soxx, on="date", suffixes=("_SMH", "_SOXX"))
    data = data.merge(qqq, on="date", suffixes=("", "_QQQ"))
    data = data.merge(vix[['date', 'VIX_close']], on="date")
    
    data = data.rename(columns={
        "RET_SMH": "SMH_RET",
        "RET_SOXX": "SOXX_RET",
        "RET": "QQQ_RET"
    })
    
    print(f"✓ {len(data)} trading days\n")
    
    # Run backtest
    print("Running backtest...")
    results = run_backtest(data)
    
    # Analyze results
    results = analyze_results(results)
    
    # Save results
    results.to_csv("backtest_detailed.csv", index=False)
    print(f"\n✓ Saved to backtest_detailed.csv")