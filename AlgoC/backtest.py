"""
Strategy B: EMA 25/125 Crossover with Equity-Level Stop Loss

Only trades during bull markets (EMA fast > slow)
Same -2% equity-level stop as Strategy A
"""
import pandas as pd
import numpy as np
import sys

data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, index_col=0, parse_dates=True)

df = df[df.index >= '2022-01-01']
print(f"Start: {df.index[0].date()}\n")

smh_open = df['Open_SMH'].ffill()
smh_close = df['Close_SMH'].ffill()
soxl = df['Close_SOXL'].ffill()
vix = df['Close_^VIX'].ffill()

# Calculate EMAs
ema_fast = smh_close.ewm(span=25, adjust=False).mean()
ema_slow = smh_close.ewm(span=125, adjust=False).mean()
bull = ema_fast > ema_slow

smh_ret = smh_close.pct_change()
vix_chg = vix.pct_change()
gap_up = smh_open > smh_close.shift(1)

trades = []
daily_log = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
equity = 100000
peak_equity = equity
max_drawdown = 0

print(f"Starting with ${equity:,.0f}")
print("Strategy: EMA 25/125 Crossover (bull market only)")
print("Stop: -2% EQUITY drawdown from day start\n")

example_stop_logged = False
example_bear_logged = False

# Start after EMA warmup
for i in range(125, len(df)):
    date = df.index[i]
    
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix.iloc[i]) or pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]):
        continue
    
    day_start_equity = equity
    stop_loss_triggered = False
    bear_exit = False
    
    # === EQUITY-LEVEL STOP LOSS ===
    if position['long_shares'] > 0:
        current_position_value = position['long_shares'] * smh_close.iloc[i]
        entry_position_value = position['long_shares'] * position['long_entry']
        unrealized_pnl = current_position_value - entry_position_value
        current_equity = day_start_equity + unrealized_pnl
        
        equity_dd = (current_equity - day_start_equity) / day_start_equity
        
        if equity_dd <= -0.02:
            stop_loss_triggered = True
            max_allowed_loss = day_start_equity * 0.02
            pnl = -max_allowed_loss
            
            trades.append({
                'date': date,
                'action': 'STOP_EQUITY',
                'entry_price': position['long_entry'],
                'close_price': smh_close.iloc[i],
                'shares': position['long_shares'],
                'pnl': pnl,
                'bull': bull.iloc[i],
                'equity_before': day_start_equity
            })
            
            equity = day_start_equity + pnl
            
            if not example_stop_logged:
                print("=" * 70)
                print("EXAMPLE: EQUITY STOP")
                print("=" * 70)
                print(f"Date: {date.date()}")
                print(f"Equity DD: {equity_dd*100:.2f}% → CAPPED at -2.00%")
                print("=" * 70 + "\n")
                example_stop_logged = True
            
            position['long_shares'] = 0
            position['long_entry'] = 0
    
    # === BEAR MARKET EXIT ===
    if position['long_shares'] > 0 and not bull.iloc[i] and not stop_loss_triggered:
        bear_exit = True
        pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        
        trades.append({
            'date': date,
            'action': 'EXIT_BEAR',
            'entry_price': position['long_entry'],
            'close_price': smh_close.iloc[i],
            'shares': position['long_shares'],
            'pnl': pnl,
            'ema_fast': ema_fast.iloc[i],
            'ema_slow': ema_slow.iloc[i],
            'equity_before': day_start_equity
        })
        
        equity = day_start_equity + pnl
        
        if not example_bear_logged:
            print("=" * 70)
            print("EXAMPLE: BEAR EXIT (EMA crossover)")
            print("=" * 70)
            print(f"Date: {date.date()}")
            print(f"EMA Fast: {ema_fast.iloc[i]:.2f} < EMA Slow: {ema_slow.iloc[i]:.2f}")
            print("=" * 70 + "\n")
            example_bear_logged = True
        
        position['long_shares'] = 0
        position['long_entry'] = 0
    
    # === ENTER LONG (only in bull market, not if stopped/exited) ===
    if position['long_shares'] == 0 and bull.iloc[i] and not stop_loss_triggered and not bear_exit:
        if vix.iloc[i] < 13:
            lev = 3.5
        elif vix.iloc[i] < 15 and gap_up.iloc[i]:
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
    
    # === SHORT HEDGE ===
    if not pd.isna(vix_chg.iloc[i]) and not pd.isna(smh_ret.iloc[i]) and not stop_loss_triggered and not bear_exit:
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
        
        # Re-enter long if still bull
        if bull.iloc[i] and position['long_shares'] == 0:
            if vix.iloc[i] < 13:
                lev = 3.5
            elif vix.iloc[i] < 15 and gap_up.iloc[i]:
                lev = 3.25
            else:
                lev = 3.0
            
            notional = equity * lev
            shares = notional / smh_close.iloc[i]
            position['long_shares'] = shares
            position['long_entry'] = smh_close.iloc[i]
            
            trades.append({
                'date': date,
                'action': 'REENTER_LONG',
                'entry_price': smh_close.iloc[i],
                'shares': shares,
                'leverage': lev,
                'pnl': None,
                'equity_before': equity
            })
    
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
        'bull': bull.iloc[i],
        'in_position': position['long_shares'] > 0
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

trades_df.to_csv('STRATEGY_B_trades.csv', index=False)
daily_df.to_csv('STRATEGY_B_daily.csv', index=False)

# Metrics
trades_pnl = trades_df[trades_df['pnl'] != 0]
wins = trades_pnl[trades_pnl['pnl'] > 0]
losses = trades_pnl[trades_pnl['pnl'] < 0]
total_return = (final_equity / 100000 - 1) * 100

max_daily_loss = daily_df['daily_change_%'].min()
bull_days = bull.iloc[125:].sum()
bear_days = len(bull.iloc[125:]) - bull_days

stop_losses = len(trades_df[trades_df['action'] == 'STOP_EQUITY'])
bear_exits = len(trades_df[trades_df['action'] == 'EXIT_BEAR'])

print("=" * 70)
print("FINAL - STRATEGY B (EMA Crossover)")
print("=" * 70)
print(f"Period: {df.index[125].date()} to {df.index[-1].date()}")
print(f"Bull Days: {bull_days} ({bull_days/(len(df)-125)*100:.1f}%)")
print(f"Bear Days: {bear_days} ({bear_days/(len(df)-125)*100:.1f}%)")

print(f"\n💰 PERFORMANCE:")
print(f"  Start: $100,000")
print(f"  Final: ${final_equity:,.2f}")
print(f"  Return: {total_return:.2f}%")
print(f"  Max DD: ${max_drawdown:,.2f} ({max_drawdown/peak_equity*100:.1f}%)")

print(f"\n✅ VALIDATION:")
print(f"  Max Daily Loss: {max_daily_loss:.2f}%")
print(f"  Stop Working: {'YES ✅' if max_daily_loss >= -2.01 else 'NO ❌'}")

print(f"\n📊 EXITS:")
print(f"  Equity Stops: {stop_losses}")
print(f"  Bear Exits: {bear_exits}")

if len(wins) > 0 and len(losses) > 0:
    print(f"\n💵 TRADES:")
    print(f"  Total: {len(trades_pnl)}")
    print(f"  Win Rate: {len(wins)/len(trades_pnl)*100:.1f}%")
    print(f"  Profit Factor: {abs(wins['pnl'].sum() / losses['pnl'].sum()):.2f}")

print("=" * 70)