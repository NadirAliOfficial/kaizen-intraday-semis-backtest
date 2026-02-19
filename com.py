"""
EMA Comparison: 25/125 vs 20/100
Both with aggressive leverage scaling
"""
import pandas as pd
import numpy as np

df = pd.read_csv('AlgoB/market_data.csv', index_col=0, parse_dates=True)
df = df[df.index >= '2022-01-01']

smh_close = df['Close_SMH'].ffill()
smh_low = df['Low_SMH'].ffill()
vix_close = df['Close_^VIX'].ffill()

def run_strategy(fast_period, slow_period, name):
    """Run strategy with given EMA periods"""
    
    ema_fast = smh_close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = smh_close.ewm(span=slow_period, adjust=False).mean()
    bull = ema_fast > ema_slow
    
    equity_series = [100000.0]
    equity = 100000.0
    position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
    
    trades = 0
    stops = 0
    bear_exits = 0
    
    # Start after warmup
    start_idx = slow_period
    
    for i in range(start_idx, len(df)):
        if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
            continue
        
        # STOP CHECK
        if position['shares'] > 0:
            worst_price = smh_low.iloc[i]
            worst_equity = position['entry_equity'] + position['shares'] * (worst_price - position['entry'])
            dd = (worst_equity - position['entry_equity']) / position['entry_equity']
            
            if dd <= -0.02:
                pnl = -(position['entry_equity'] * 0.02)
                equity = position['entry_equity'] + pnl
                position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
                stops += 1
        
        # BEAR EXIT
        if position['shares'] > 0 and not bull.iloc[i]:
            pnl = position['shares'] * (smh_close.iloc[i] - position['entry'])
            equity = position['entry_equity'] + pnl
            position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
            bear_exits += 1
        
        # ENTRY with aggressive leverage
        if position['shares'] == 0 and bull.iloc[i]:
            vix = vix_close.iloc[i]
            if vix < 12:
                lev = 3.75
            elif vix < 13:
                lev = 3.5
            elif vix < 14:
                lev = 3.25
            else:
                lev = 3.0
            
            entry_price = smh_close.iloc[i]
            shares = (equity * lev) / entry_price
            position = {'shares': shares, 'entry': entry_price, 'entry_equity': equity}
            trades += 1
        
        # EOD
        if position['shares'] > 0:
            eod_equity = equity + position['shares'] * (smh_close.iloc[i] - position['entry'])
        else:
            eod_equity = equity
        
        equity_series.append(eod_equity)
    
    # Statistics
    equity_array = np.array(equity_series)
    daily_returns = np.diff(equity_array) / equity_array[:-1]
    
    initial = equity_array[0]
    final = equity_array[-1]
    total_return = (final / initial - 1) * 100
    years = len(equity_array) / 252
    cagr = (pow(final / initial, 1/years) - 1) * 100
    
    # Drawdown
    peak = equity_array[0]
    max_dd_abs = 0
    max_dd_pct = 0
    for e in equity_array:
        if e > peak:
            peak = e
        dd = peak - e
        dd_pct = (dd / peak) * 100
        if dd > max_dd_abs:
            max_dd_abs = dd
            max_dd_pct = dd_pct
    
    # Risk metrics
    mean_ret = daily_returns.mean()
    std_ret = daily_returns.std()
    annual_vol = std_ret * np.sqrt(252) * 100
    sharpe = (mean_ret * 252) / (std_ret * np.sqrt(252)) if std_ret > 0 else 0
    mar = cagr / max_dd_pct if max_dd_pct > 0 else 0
    
    return {
        'name': name,
        'ema_config': f'{fast_period}/{slow_period}',
        'days': len(equity_array),
        'years': years,
        'final': final,
        'total_return': total_return,
        'cagr': cagr,
        'max_dd_pct': max_dd_pct,
        'max_dd_abs': max_dd_abs,
        'annual_vol': annual_vol,
        'sharpe': sharpe,
        'mar': mar,
        'max_daily_loss': daily_returns.min() * 100,
        'max_daily_gain': daily_returns.max() * 100,
        'trades': trades,
        'stops': stops,
        'bear_exits': bear_exits,
        'equity_curve': equity_array
    }

print("=" * 80)
print("EMA CONFIGURATION COMPARISON")
print("Leverage: 3.0x base → 3.25x (VIX<14) → 3.5x (VIX<13) → 3.75x (VIX<12)")
print("=" * 80)

# Run both
results_25_125 = run_strategy(25, 125, "EMA 25/125")
results_20_100 = run_strategy(20, 100, "EMA 20/100")

def print_results(r):
    print(f"\n{'='*80}")
    print(f"{r['name']} ({r['ema_config']})")
    print(f"{'='*80}")
    print(f"\n💰 PERFORMANCE:")
    print(f"  Trading Days: {r['days']}")
    print(f"  Years: {r['years']:.2f}")
    print(f"  Final Equity: ${r['final']:,.2f}")
    print(f"  Total Return: {r['total_return']:.2f}%")
    print(f"  CAGR: {r['cagr']:.2f}%")
    
    print(f"\n📉 RISK:")
    print(f"  Max DD: {r['max_dd_pct']:.2f}% (${r['max_dd_abs']:,.2f})")
    print(f"  Annual Vol: {r['annual_vol']:.2f}%")
    print(f"  Sharpe: {r['sharpe']:.2f}")
    print(f"  MAR Ratio: {r['mar']:.2f}")
    print(f"  Max Daily Loss: {r['max_daily_loss']:.2f}%")
    print(f"  Max Daily Gain: {r['max_daily_gain']:.2f}%")
    
    print(f"\n📊 TRADES:")
    print(f"  Total Entries: {r['trades']}")
    print(f"  Stops: {r['stops']}")
    print(f"  Bear Exits: {r['bear_exits']}")

print_results(results_25_125)
print_results(results_20_100)

# COMPARISON
print(f"\n{'='*80}")
print("HEAD-TO-HEAD COMPARISON")
print(f"{'='*80}")

comparison = [
    ("CAGR", results_25_125['cagr'], results_20_100['cagr'], "%", True),
    ("Max DD", results_25_125['max_dd_pct'], results_20_100['max_dd_pct'], "%", False),
    ("Sharpe", results_25_125['sharpe'], results_20_100['sharpe'], "", True),
    ("MAR Ratio", results_25_125['mar'], results_20_100['mar'], "", True),
    ("Annual Vol", results_25_125['annual_vol'], results_20_100['annual_vol'], "%", False),
    ("Total Trades", results_25_125['trades'], results_20_100['trades'], "", None),
    ("Stops", results_25_125['stops'], results_20_100['stops'], "", None),
]

print(f"\n{'Metric':<20} {'25/125':<15} {'20/100':<15} {'Winner':<10}")
print("-" * 70)

for metric, val1, val2, unit, higher_better in comparison:
    if higher_better is None:
        winner = "-"
    elif higher_better:
        winner = "25/125" if val1 > val2 else "20/100"
    else:
        winner = "25/125" if val1 < val2 else "20/100"
    
    print(f"{metric:<20} {val1:>10.2f}{unit:<4} {val2:>10.2f}{unit:<4} {winner:<10}")

print("\n" + "=" * 80)
print("RECOMMENDATION")
print("=" * 80)

# Simple scoring
score_25_125 = 0
score_20_100 = 0

if results_25_125['cagr'] > results_20_100['cagr']:
    score_25_125 += 2
else:
    score_20_100 += 2

if results_25_125['max_dd_pct'] < results_20_100['max_dd_pct']:
    score_25_125 += 2
else:
    score_20_100 += 2

if results_25_125['sharpe'] > results_20_100['sharpe']:
    score_25_125 += 2
else:
    score_20_100 += 2

if results_25_125['mar'] > results_20_100['mar']:
    score_25_125 += 1
else:
    score_20_100 += 1

if score_25_125 > score_20_100:
    print(f"🏆 WINNER: EMA 25/125")
    print(f"   Score: {score_25_125} vs {score_20_100}")
    print(f"   Deploy this configuration to IBKR")
elif score_20_100 > score_25_125:
    print(f"🏆 WINNER: EMA 20/100")
    print(f"   Score: {score_20_100} vs {score_25_125}")
    print(f"   Deploy this configuration to IBKR")
else:
    print(f"⚖️  TIE: Both configurations perform similarly")
    print(f"   Recommend EMA 25/125 (more conservative)")

print("=" * 80)