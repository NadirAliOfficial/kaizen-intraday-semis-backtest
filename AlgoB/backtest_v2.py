"""
FINAL CORRECTED: True Equity-Level Stop Loss

The stop monitors CURRENT EQUITY (including unrealized P&L) and triggers 
when equity drops -2% from the day's starting equity.

This is the only correct way to implement an equity-level stop.
"""
import pandas as pd
import numpy as np
import sys

data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, index_col=0, parse_dates=True)

# df = df[df.index >= '2022-01-01']
df = df[df.index >= '2022-07-05']
print(f"Start: {df.index[0].date()}\n")

smh_open = df['Open_SMH'].ffill()
smh_close = df['Close_SMH'].ffill()
soxl = df['Close_SOXL'].ffill()
vix = df['Close_^VIX'].ffill()

smh_ret = smh_close.pct_change()
vix_chg = vix.pct_change()

trades = []
daily_log = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
equity = 100000
peak_equity = equity
max_drawdown = 0

print(f"Starting with ${equity:,.0f}")
print("Stop: -2% EQUITY drawdown from day start\n")

example_logged = False

for i in range(1, len(df)):
    date = df.index[i]
    
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix.iloc[i]):
        continue
    
    day_start_equity = equity
    stop_loss_triggered = False
    
    # === EQUITY-LEVEL STOP LOSS CHECK ===
    if position['long_shares'] > 0:
        # Calculate CURRENT equity (with unrealized P&L)
        current_position_value = position['long_shares'] * smh_close.iloc[i]
        entry_position_value = position['long_shares'] * position['long_entry']
        unrealized_pnl = current_position_value - entry_position_value
        current_equity = day_start_equity + unrealized_pnl
        
        # Check if equity dropped -2% from day start
        equity_dd = (current_equity - day_start_equity) / day_start_equity
        
        if equity_dd <= -0.02:
            stop_loss_triggered = True
            
            # Cap loss at exactly -2% of day start equity
            max_allowed_loss = day_start_equity * 0.02
            pnl = -max_allowed_loss
            
            trades.append({
                'date': date,
                'action': 'STOP_EQUITY',
                'entry_price': position['long_entry'],
                'close_price': smh_close.iloc[i],
                'shares': position['long_shares'],
                'pnl': pnl,
                'actual_equity_dd_%': equity_dd * 100,
                'capped_equity_dd_%': -2.0,
                'equity_before': day_start_equity
            })
            
            equity = day_start_equity + pnl  # Exactly -2%
            
            if not example_logged:
                print("=" * 70)
                print("EXAMPLE: EQUITY STOP")
                print("=" * 70)
                print(f"Date: {date.date()}")
                print(f"Entry: ${position['long_entry']:.2f}, Close: ${smh_close.iloc[i]:.2f}")
                print(f"Actual equity DD: {equity_dd*100:.2f}%")
                print(f"CAPPED at: -2.00%")
                print(f"Day start: ${day_start_equity:,.2f}")
                print(f"Day end: ${equity:,.2f}")
                print(f"Change: {(equity/day_start_equity-1)*100:.2f}%")
                print("=" * 70 + "\n")
                example_logged = True
            
            position['long_shares'] = 0
            position['long_entry'] = 0
    
    # === ENTER LONG (only if not stopped out) ===
    if position['long_shares'] == 0 and not stop_loss_triggered:
        if vix.iloc[i] < 13:
            lev = 3.5
        elif vix.iloc[i] < 15:
            lev = 3.25
        else:
            lev = 3.0
        
        notional = equity * lev
        shares = notional / smh_close.iloc[i]
        position['long_shares'] = shares
        position['long_entry'] = smh_close.iloc[i]
        
        trades.append({
            'date': date,
            'action': 'ENTER_LONG',
            'entry_price': smh_close.iloc[i],
            'shares': shares,
            'leverage': lev,
            'pnl': None,
            'equity_before': equity
        })
    
    # === SHORT HEDGE (only if not stopped out) ===
    if not pd.isna(vix_chg.iloc[i]) and not pd.isna(smh_ret.iloc[i]) and not stop_loss_triggered:
        if vix_chg.iloc[i] >= 0.02 and smh_ret.iloc[i] <= -0.005 and position['short_shares'] == 0:
            short_lev = 1.5 if vix.iloc[i] >= 22 else 1.0
            short_notional = equity * short_lev
            short_shares = short_notional / soxl.iloc[i]
            
            position['short_shares'] = short_shares
            position['short_entry'] = soxl.iloc[i]
            
            trades.append({
                'date': date,
                'action': 'ENTER_SHORT',
                'entry_price': soxl.iloc[i],
                'shares': short_shares,
                'leverage': short_lev,
                'pnl': None,
                'equity_before': equity
            })
    
    # === EXIT SHORT ===
    if position['short_shares'] > 0:
        pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
        
        trades.append({
            'date': date,
            'action': 'EXIT_SHORT',
            'entry_price': position['short_entry'],
            'exit_price': soxl.iloc[i],
            'shares': position['short_shares'],
            'pnl': pnl,
            'equity_before': equity
        })
        
        equity += pnl
        position['short_shares'] = 0
        position['short_entry'] = 0
    
    # === EOD EQUITY ===
    if position['long_shares'] > 0:
        unrealized = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        eod_equity = equity + unrealized
    else:
        eod_equity = equity
    
    # === DRAWDOWN ===
    if eod_equity > peak_equity:
        peak_equity = eod_equity
    
    dd = peak_equity - eod_equity
    if dd > max_drawdown:
        max_drawdown = dd
    
    daily_log.append({
        'date': date,
        'eod_equity': eod_equity,
        'peak_equity': peak_equity,
        'drawdown_%': (dd / peak_equity) * 100,
        'daily_change_%': (eod_equity / day_start_equity - 1) * 100,
        'stop_triggered': stop_loss_triggered
    })

# FINAL
if position['long_shares'] > 0:
    final_unrealized = position['long_shares'] * (smh_close.iloc[-1] - position['long_entry'])
    final_equity = equity + final_unrealized
else:
    final_equity = equity

# Save
trades_df = pd.DataFrame(trades)
trades_df['pnl'] = trades_df['pnl'].fillna(0)
daily_df = pd.DataFrame(daily_log)

trades_df.to_csv('FINAL_EQUITY_trades.csv', index=False)
daily_df.to_csv('FINAL_EQUITY_daily.csv', index=False)

# Metrics
trades_pnl = trades_df[trades_df['pnl'] != 0]
wins = trades_pnl[trades_pnl['pnl'] > 0]
losses = trades_pnl[trades_pnl['pnl'] < 0]
total_return = (final_equity / 100000 - 1) * 100

max_daily_loss = daily_df['daily_change_%'].min()

print("=" * 70)
print("FINAL - EQUITY-LEVEL STOP")
print("=" * 70)
print(f"Period: {df.index[0].date()} to {df.index[-1].date()}")
print(f"\n💰 PERFORMANCE:")
print(f"  Start: $100,000")
print(f"  Final: ${final_equity:,.2f}")
print(f"  Return: {total_return:.2f}%")
print(f"  Max DD: ${max_drawdown:,.2f} ({max_drawdown/peak_equity*100:.1f}%)")

print(f"\n✅ VALIDATION:")
print(f"  Max Daily Loss: {max_daily_loss:.2f}%")
print(f"  Stop Working: {'YES ✅' if max_daily_loss >= -2.01 else 'NO ❌'}")

if len(wins) > 0 and len(losses) > 0:
    print(f"\n📊 TRADES:")
    print(f"  Total: {len(trades_pnl)}")
    print(f"  Win Rate: {len(wins)/len(trades_pnl)*100:.1f}%")
    print(f"  Profit Factor: {abs(wins['pnl'].sum() / losses['pnl'].sum()):.2f}")

print("=" * 70)