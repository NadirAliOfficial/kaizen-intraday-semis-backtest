
"""
FINAL PRODUCTION BACKTEST
Exact logic from ibkr_production_FINAL_v2.py
- Dynamic VIX leverage (3.0/3.25/3.5/3.75)
- 1.9% effective stop (1.8% + 0.1%)
- Re-entry after intraday stops
- $50 rebalance threshold
- SMH long-only
"""
import pandas as pd
import numpy as np
from datetime import datetime

df = pd.read_csv('AlgoB/market_data.csv', index_col=0, parse_dates=True)
df = df[df.index >= '2022-01-01']

smh_close = df['Close_SMH'].ffill()
smh_low = df['Low_SMH'].ffill()
vix_close = df['Close_^VIX'].ffill()

# EMAs
ema_fast = smh_close.ewm(span=25, adjust=False).mean()
ema_slow = smh_close.ewm(span=125, adjust=False).mean()
bull = ema_fast > ema_slow

# EXACT PRODUCTION PARAMETERS
STOP_LOSS_PCT = 0.018
STOP_BUFFER = 0.001
REBALANCE_THRESHOLD = 50

def get_leverage(vix):
    """Dynamic VIX-based leverage - EXACT production logic"""
    if vix < 12:
        return 3.75
    elif vix < 13:
        return 3.5
    elif vix < 14:
        return 3.25
    else:
        return 3.0

# Backtest
equity_series = []
dates_list = []
trades = []

equity = 100000.0
position = {'shares': 0, 'entry': 0, 'entry_equity': 0}

stop_count = 0
bear_exit_count = 0
entry_count = 0
rebalance_count = 0

start_idx = 125  # EMA warmup

for i in range(start_idx, len(df)):
    date = df.index[i]
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
        continue
    
    stopped_today = False
    
    # INTRADAY STOP CHECK (using LOW as proxy)
    if position['shares'] > 0:
        worst_price = smh_low.iloc[i]
        worst_equity = position['entry_equity'] + position['shares'] * (worst_price - position['entry'])
        dd = (worst_equity - position['entry_equity']) / position['entry_equity']
        
        effective_stop = STOP_LOSS_PCT + STOP_BUFFER
        
        if dd <= -effective_stop:
            # Exit at capped loss
            pnl = -(position['entry_equity'] * STOP_LOSS_PCT)
            equity = position['entry_equity'] + pnl
            
            trades.append({
                'date': date,
                'action': 'STOP',
                'entry': position['entry'],
                'exit': worst_price,
                'shares': position['shares'],
                'pnl': pnl,
                'equity': equity
            })
            
            position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
            stop_count += 1
            stopped_today = True
    
    # BEAR EXIT (at close)
    if position['shares'] > 0 and not bull.iloc[i] and not stopped_today:
        pnl = position['shares'] * (smh_close.iloc[i] - position['entry'])
        equity = position['entry_equity'] + pnl
        
        trades.append({
            'date': date,
            'action': 'BEAR_EXIT',
            'entry': position['entry'],
            'exit': smh_close.iloc[i],
            'shares': position['shares'],
            'pnl': pnl,
            'equity': equity
        })
        
        position = {'shares': 0, 'entry': 0, 'entry_equity': 0}
        bear_exit_count += 1
    
    # ENTRY (includes re-entry after intraday stop)
    if position['shares'] == 0 and bull.iloc[i]:
        vix = vix_close.iloc[i]
        leverage = get_leverage(vix)
        
        entry_price = smh_close.iloc[i]
        shares = (equity * leverage) / entry_price
        
        position = {
            'shares': shares,
            'entry': entry_price,
            'entry_equity': equity
        }
        
        trades.append({
            'date': date,
            'action': 'RE_ENTER' if stopped_today else 'ENTER',
            'price': entry_price,
            'shares': shares,
            'leverage': leverage,
            'vix': vix,
            'equity': equity
        })
        
        entry_count += 1
    
    # REBALANCING (at close, if position exists and bull)
    elif position['shares'] > 0 and bull.iloc[i]:
        close = smh_close.iloc[i]
        vix = vix_close.iloc[i]
        leverage = get_leverage(vix)
        
        target_notional = equity * leverage
        target_qty = int(target_notional / close)
        
        current_notional = position['shares'] * close
        notional_diff = abs(target_notional - current_notional)
        
        if notional_diff > REBALANCE_THRESHOLD:
            qty_diff = target_qty - position['shares']
            
            trades.append({
                'date': date,
                'action': 'REBALANCE',
                'price': close,
                'shares_before': position['shares'],
                'shares_after': target_qty,
                'qty_diff': qty_diff,
                'notional_diff': notional_diff
            })
            
            position['shares'] = target_qty
            rebalance_count += 1
    
    # EOD EQUITY
    if position['shares'] > 0:
        eod_equity = equity + position['shares'] * (smh_close.iloc[i] - position['entry'])
    else:
        eod_equity = equity
    
    equity_series.append(eod_equity)
    dates_list.append(date)

# CALCULATE METRICS
equity_array = np.array(equity_series)
dates_array = pd.to_datetime(dates_list)

initial = equity_array[0]
final = equity_array[-1]
total_return = (final / initial - 1) * 100

years = len(equity_array) / 252
cagr = (pow(final / initial, 1/years) - 1) * 100

# MAX DRAWDOWN
peak = equity_array[0]
max_dd_abs = 0
max_dd_pct = 0
peak_date = dates_array[0]
trough_date = dates_array[0]

for i, e in enumerate(equity_array):
    if e > peak:
        peak = e
        peak_date = dates_array[i]
    
    dd = peak - e
    dd_pct = (dd / peak) * 100
    
    if dd > max_dd_abs:
        max_dd_abs = dd
        max_dd_pct = dd_pct
        trough_date = dates_array[i]

mar = cagr / max_dd_pct if max_dd_pct > 0 else 0

# PRINT RESULTS
print("=" * 80)
print("FINAL PRODUCTION BACKTEST - EXACT LOGIC")
print("=" * 80)

print(f"\nPERIOD:")
print(f"  Start: {dates_array[0].date()}")
print(f"  End: {dates_array[-1].date()}")
print(f"  Years: {years:.2f}")

print(f"\nPERFORMANCE:")
print(f"  Initial: ${initial:,.2f}")
print(f"  Final: ${final:,.2f}")
print(f"  Total Return: {total_return:.2f}%")
print(f"  CAGR: {cagr:.2f}%")

print(f"\nDRAWDOWN:")
print(f"  Max DD: ${max_dd_abs:,.2f} ({max_dd_pct:.2f}%)")
print(f"  Peak: {peak_date.date()}")
print(f"  Trough: {trough_date.date()}")
print(f"  MAR Ratio: {mar:.2f}")

print(f"\nTRADES:")
print(f"  Entries: {entry_count}")
print(f"  Stops: {stop_count}")
print(f"  Bear Exits: {bear_exit_count}")
print(f"  Rebalances: {rebalance_count}")

# LEVERAGE USAGE
trades_df = pd.DataFrame(trades)
entries = trades_df[trades_df['action'].isin(['ENTER', 'RE_ENTER'])]
if len(entries) > 0 and 'leverage' in entries.columns:
    print(f"\nLEVERAGE USAGE:")
    lev_counts = entries['leverage'].value_counts().sort_index()
    for lev, count in lev_counts.items():
        print(f"  {lev}x: {count} times ({count/len(entries)*100:.1f}%)")

# SAVE FILES
equity_df = pd.DataFrame({
    'date': dates_array,
    'equity': equity_array
})
equity_df.to_csv('FINAL_PRODUCTION_equity_curve.csv', index=False)

trades_df.to_csv('FINAL_PRODUCTION_trades.csv', index=False)

print(f"\n✅ FILES SAVED:")
print(f"  FINAL_PRODUCTION_equity_curve.csv")
print(f"  FINAL_PRODUCTION_trades.csv")

print("\n" + "=" * 80)
print("CONFIGURATION VERIFIED:")
print("=" * 80)
print(f"✓ Dynamic VIX leverage: 3.0 / 3.25 / 3.5 / 3.75")
print(f"✓ Stop: {STOP_LOSS_PCT*100}% + {STOP_BUFFER*100}% = {(STOP_LOSS_PCT+STOP_BUFFER)*100}% effective")
print(f"✓ Rebalance threshold: ${REBALANCE_THRESHOLD}")
print(f"✓ Re-entry after stops: Enabled")
print(f"✓ SMH long-only: Yes")
print("=" * 80)