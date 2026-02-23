"""
Tight Stop Loss Analysis with 0.1% Buffer
Test: 1.8%, 2.0%, 2.15%
"""
import pandas as pd
import numpy as np

df = pd.read_csv('AlgoB/market_data.csv', index_col=0, parse_dates=True)
df = df[df.index >= '2022-01-01']

smh_close = df['Close_SMH'].ffill()
smh_low = df['Low_SMH'].ffill()
vix_close = df['Close_^VIX'].ffill()

ema_fast = smh_close.ewm(span=25, adjust=False).mean()
ema_slow = smh_close.ewm(span=125, adjust=False).mean()
bull = ema_fast > ema_slow

def run_backtest(stop_pct, buffer_pct, name):
    equity_series = []
    equity = 100000.0
    position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
    
    stop_count = 0
    bear_exit_count = 0
    entry_count = 0
    
    # Effective stop = stop_pct + buffer_pct
    effective_stop = stop_pct + buffer_pct
    
    for i in range(125, len(df)):
        if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
            continue
        
        # STOP CHECK
        if position['shares'] > 0:
            worst_price = smh_low.iloc[i]
            worst_equity = position['entry_equity'] + position['shares'] * (worst_price - position['entry'])
            dd = (worst_equity - position['entry_equity']) / position['entry_equity']
            
            if dd <= -effective_stop:
                pnl = -(position['entry_equity'] * stop_pct)
                equity = position['entry_equity'] + pnl
                position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
                stop_count += 1
        
        # BEAR EXIT
        if position['shares'] > 0 and not bull.iloc[i]:
            pnl = position['shares'] * (smh_close.iloc[i] - position['entry'])
            equity = position['entry_equity'] + pnl
            position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
            bear_exit_count += 1
        
        # ENTRY
        if position['shares'] == 0 and bull.iloc[i]:
            vix = vix_close.iloc[i]
            lev = 3.75 if vix < 12 else (3.5 if vix < 13 else (3.25 if vix < 14 else 3.0))
            
            entry_price = smh_close.iloc[i]
            shares = (equity * lev) / entry_price
            position = {'shares': shares, 'entry': entry_price, 'entry_equity': equity}
            entry_count += 1
        
        # EOD
        eod_equity = equity + (position['shares'] * (smh_close.iloc[i] - position['entry']) if position['shares'] > 0 else 0)
        equity_series.append(eod_equity)
    
    # Stats
    equity_array = np.array(equity_series)
    initial = equity_array[0]
    final = equity_array[-1]
    
    years = len(equity_array) / 252
    cagr = (pow(final / initial, 1/years) - 1) * 100
    
    peak = equity_array[0]
    max_dd = 0
    for e in equity_array:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    mar = cagr / max_dd if max_dd > 0 else 0
    
    return {
        'name': name,
        'stop_%': stop_pct * 100,
        'buffer_%': buffer_pct * 100,
        'effective_%': effective_stop * 100,
        'final': final,
        'cagr': cagr,
        'max_dd': max_dd,
        'mar': mar,
        'stops': stop_count,
        'entries': entry_count
    }

print("=" * 90)
print("TIGHT STOP LOSS ANALYSIS - 0.1% Buffer")
print("Period: July 2022 - Jan 2026")
print("=" * 90)

# Run all three with 0.1% buffer
results = []
for stop_pct, name in [(0.018, "1.8%"), (0.020, "2.0%"), (0.0215, "2.15%")]:
    result = run_backtest(stop_pct, 0.001, name)  # 0.1% buffer
    results.append(result)
    
    print(f"\n{name} Stop (Effective {result['effective_%']:.2f}%):")
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Max DD: {result['max_dd']:.2f}%")
    print(f"  MAR Ratio: {result['mar']:.2f}")
    print(f"  Stops Hit: {result['stops']}")
    print(f"  Entries: {result['entries']}")

# Comparison table
print("\n" + "=" * 90)
print("COMPARISON TABLE")
print("=" * 90)

df_results = pd.DataFrame(results)
print(f"\n{'Stop':<8} {'Effective':<12} {'CAGR':<10} {'Max DD':<10} {'MAR':<10} {'Stops':<10}")
print("-" * 85)
for _, row in df_results.iterrows():
    print(f"{row['stop_%']:>6.2f}% {row['effective_%']:>10.2f}% {row['cagr']:>8.2f}% {row['max_dd']:>8.2f}% {row['mar']:>8.2f} {row['stops']:>8}")

print("\n" + "=" * 90)
print("ANALYSIS")
print("=" * 90)

best_mar = df_results.loc[df_results['mar'].idxmax()]
best_cagr = df_results.loc[df_results['cagr'].idxmax()]
most_stops = df_results.loc[df_results['stops'].idxmax()]

print(f"\nBest CAGR: {best_cagr['name']} ({best_cagr['cagr']:.2f}%)")
print(f"Best MAR: {best_mar['name']} (MAR {best_mar['mar']:.2f})")
print(f"Most Disciplined: {most_stops['name']} ({most_stops['stops']} stops)")

print("\n" + "=" * 90)
print("RECOMMENDATION")
print("=" * 90)

if best_mar['name'] == best_cagr['name']:
    print(f"✅ CLEAR WINNER: {best_mar['name']}")
    print(f"   Best CAGR AND best MAR ratio")
else:
    print(f"⚖️  TRADE-OFF:")
    print(f"   {best_cagr['name']}: Highest returns ({best_cagr['cagr']:.2f}% CAGR)")
    print(f"   {best_mar['name']}: Best risk-adjusted (MAR {best_mar['mar']:.2f})")
    print(f"\n   Recommend: {best_mar['name']} for better risk management")

print("=" * 90)