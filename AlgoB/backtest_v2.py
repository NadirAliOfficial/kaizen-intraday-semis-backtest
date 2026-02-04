"""
Strategy B: EMA 25/125 Crossover - SAME methodology as Strategy A
Only trades during bull markets (EMA fast > slow)

Start Date: 2022-01-01
"""
import pandas as pd
import numpy as np
import sys

# Load data
data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, index_col=0, parse_dates=True)

# Filter to start from 2022-01-01
df = df[df.index >= '2022-01-01']
print(f"Filtered to start from: {df.index[0].date()}")

# Extract series
smh_open = df['Open_SMH'].ffill()
smh_close = df['Close_SMH'].ffill()
soxl = df['Close_SOXL'].ffill()
vix = df['Close_^VIX'].ffill()

# Calculate EMAs
ema_fast = smh_close.ewm(span=25, adjust=False).mean()
ema_slow = smh_close.ewm(span=125, adjust=False).mean()

# Calculate indicators
bull = ema_fast > ema_slow
smh_ret = smh_close.pct_change()
vix_chg = vix.pct_change()
prev_close = smh_close.shift(1)
gap_up = smh_open > prev_close

# Initialize
trades = []
daily_log = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
initial_capital = 100000
equity = initial_capital
peak_equity = initial_capital
max_drawdown = 0

print(f"Starting backtest with ${initial_capital:,.0f}...")
print(f"Strategy: EMA 25/125 Crossover")
print(f"Only enters long during bull markets (EMA fast > slow)\n")

gap_example_logged = False
intraday_example_logged = False
bear_exit_logged = False

# Main loop (start after EMA warmup)
for i in range(125, len(df)):
    date = df.index[i]
    
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix.iloc[i]) or pd.isna(smh_open.iloc[i]):
        continue
    
    day_start_equity = equity
    stop_loss_triggered = False
    is_gap_down = False
    
    # 1. CHECK FOR GAP DOWN STOP
    if position['long_shares'] > 0 and not pd.isna(prev_close.iloc[i]):
        gap_at_open = (smh_open.iloc[i] - prev_close.iloc[i]) / prev_close.iloc[i]
        
        if gap_at_open <= -0.02:
            stop_loss_triggered = True
            is_gap_down = True
            
            exit_price = max(smh_open.iloc[i], prev_close.iloc[i] * 0.98)
            pnl = position['long_shares'] * (exit_price - position['long_entry'])
            
            trades.append({
                'date': date, 'action': 'STOP_LOSS_GAP', 'asset': 'SMH',
                'entry_price': position['long_entry'], 'exit_price': exit_price,
                'shares': position['long_shares'], 'pnl': pnl,
                'gap_at_open_%': gap_at_open * 100, 'bull': bull.iloc[i],
                'equity_before': day_start_equity
            })
            
            equity = day_start_equity + pnl
            
            if not gap_example_logged:
                print("=" * 70)
                print("EXAMPLE GAP STOP")
                print("=" * 70)
                print(f"Date: {date.date()}")
                print(f"Gap: {gap_at_open*100:.2f}%")
                print(f"P&L: ${pnl:,.2f} ({pnl/day_start_equity*100:.2f}%)")
                print("=" * 70 + "\n")
                gap_example_logged = True
            
            position['long_shares'] = 0
            position['long_entry'] = 0
        
        # 2. INTRADAY STOP
        elif not stop_loss_triggered:
            close_dd = (smh_close.iloc[i] - prev_close.iloc[i]) / prev_close.iloc[i]
            
            if close_dd <= -0.02:
                stop_loss_triggered = True
                pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
                
                trades.append({
                    'date': date, 'action': 'STOP_LOSS_INTRADAY', 'asset': 'SMH',
                    'entry_price': position['long_entry'], 'exit_price': smh_close.iloc[i],
                    'shares': position['long_shares'], 'pnl': pnl,
                    'close_dd_%': close_dd * 100, 'bull': bull.iloc[i],
                    'equity_before': day_start_equity
                })
                
                equity = day_start_equity + pnl
                
                if not intraday_example_logged:
                    print("=" * 70)
                    print("EXAMPLE INTRADAY STOP")
                    print("=" * 70)
                    print(f"Date: {date.date()}")
                    print(f"DD: {close_dd*100:.2f}%")
                    print(f"P&L: ${pnl:,.2f} ({pnl/day_start_equity*100:.2f}%)")
                    print("=" * 70 + "\n")
                    intraday_example_logged = True
                
                position['long_shares'] = 0
                position['long_entry'] = 0
    
    # 3. BEAR MARKET EXIT
    if position['long_shares'] > 0 and not bull.iloc[i] and not stop_loss_triggered:
        pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        
        trades.append({
            'date': date, 'action': 'EXIT_BEAR', 'asset': 'SMH',
            'entry_price': position['long_entry'], 'exit_price': smh_close.iloc[i],
            'shares': position['long_shares'], 'pnl': pnl,
            'ema_fast': ema_fast.iloc[i], 'ema_slow': ema_slow.iloc[i],
            'equity_before': day_start_equity
        })
        
        equity = day_start_equity + pnl
        
        if not bear_exit_logged:
            print("=" * 70)
            print("EXAMPLE BEAR EXIT (EMA crossover)")
            print("=" * 70)
            print(f"Date: {date.date()}")
            print(f"EMA Fast: {ema_fast.iloc[i]:.2f} < EMA Slow: {ema_slow.iloc[i]:.2f}")
            print(f"P&L: ${pnl:,.2f}")
            print("=" * 70 + "\n")
            bear_exit_logged = True
        
        position['long_shares'] = 0
        position['long_entry'] = 0
    
    # 4. ENTER LONG (only in bull market)
    if position['long_shares'] == 0 and bull.iloc[i]:
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
            'date': date, 'action': 'ENTER_LONG', 'asset': 'SMH',
            'entry_price': smh_close.iloc[i], 'exit_price': None,
            'shares': shares, 'notional': notional, 'leverage': lev,
            'vix': vix.iloc[i], 'pnl': None, 'equity_before': equity
        })
    
    # 5. SHORT HEDGE
    if not pd.isna(vix_chg.iloc[i]) and not pd.isna(smh_ret.iloc[i]):
        if vix_chg.iloc[i] >= 0.02 and smh_ret.iloc[i] <= -0.005 and position['short_shares'] == 0:
            short_lev = 1.5 if vix.iloc[i] >= 22 else 1.0
            short_notional = equity * short_lev
            short_shares = short_notional / soxl.iloc[i]
            
            position['short_shares'] = short_shares
            position['short_entry'] = soxl.iloc[i]
            
            trades.append({
                'date': date, 'action': 'ENTER_SHORT', 'asset': 'SOXL',
                'entry_price': soxl.iloc[i], 'exit_price': None,
                'shares': short_shares, 'notional': short_notional,
                'leverage': short_lev, 'vix': vix.iloc[i],
                'pnl': None, 'equity_before': equity
            })
    
    # 6. EXIT SHORT
    if position['short_shares'] > 0:
        pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
        
        trades.append({
            'date': date, 'action': 'EXIT_SHORT', 'asset': 'SOXL',
            'entry_price': position['short_entry'], 'exit_price': soxl.iloc[i],
            'shares': position['short_shares'], 'pnl': pnl,
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
                'date': date, 'action': 'REENTER_LONG', 'asset': 'SMH',
                'entry_price': smh_close.iloc[i], 'exit_price': None,
                'shares': shares, 'notional': notional, 'leverage': lev,
                'vix': vix.iloc[i], 'pnl': None, 'equity_before': equity
            })
    
    # 7. EOD EQUITY
    if position['long_shares'] > 0:
        unrealized_pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        eod_equity = equity + unrealized_pnl
    else:
        eod_equity = equity
    
    # 8. DRAWDOWN
    if eod_equity > peak_equity:
        peak_equity = eod_equity
    
    current_drawdown = peak_equity - eod_equity
    drawdown_pct = (current_drawdown / peak_equity) * 100
    
    if current_drawdown > max_drawdown:
        max_drawdown = current_drawdown
    
    daily_log.append({
        'date': date, 'eod_equity': eod_equity, 'peak_equity': peak_equity,
        'drawdown_$': current_drawdown, 'drawdown_%': drawdown_pct,
        'in_position': position['long_shares'] > 0, 'bull': bull.iloc[i],
        'smh_close': smh_close.iloc[i], 'vix': vix.iloc[i]
    })

# FINAL EQUITY
if position['long_shares'] > 0:
    final_unrealized_pnl = position['long_shares'] * (smh_close.iloc[-1] - position['long_entry'])
    final_equity = equity + final_unrealized_pnl
else:
    final_equity = equity

# Save
trades_df = pd.DataFrame(trades)
trades_df['pnl'] = trades_df['pnl'].fillna(0)
daily_df = pd.DataFrame(daily_log)

trades_df.to_csv('backtest_STRATEGY_B_trades.csv', index=False)
daily_df.to_csv('backtest_STRATEGY_B_daily.csv', index=False)

# Metrics
trades_with_pnl = trades_df[trades_df['pnl'] != 0]
winning_trades = trades_with_pnl[trades_with_pnl['pnl'] > 0]
losing_trades = trades_with_pnl[trades_with_pnl['pnl'] < 0]
total_return = (final_equity / initial_capital - 1) * 100

long_entries = len(trades_df[trades_df['action'].isin(['ENTER_LONG', 'REENTER_LONG'])])
short_entries = len(trades_df[trades_df['action'] == 'ENTER_SHORT'])
gap_stops = len(trades_df[trades_df['action'] == 'STOP_LOSS_GAP'])
intraday_stops = len(trades_df[trades_df['action'] == 'STOP_LOSS_INTRADAY'])
bear_exits = len(trades_df[trades_df['action'] == 'EXIT_BEAR'])

bull_days = bull.iloc[125:].sum()
bear_days = len(bull.iloc[125:]) - bull_days

# Summary
print("\n" + "=" * 70)
print("FINAL BACKTEST - Strategy B (EMA Crossover)")
print("=" * 70)
print(f"Period: {df.index[125].date()} to {df.index[-1].date()}")
print(f"Days: {len(df) - 125}")
print(f"Bull Days: {bull_days} ({bull_days/(len(df)-125)*100:.1f}%)")
print(f"Bear Days: {bear_days} ({bear_days/(len(df)-125)*100:.1f}%)")

print(f"\n🛡️  STOP LOSS:")
print(f"  Gap: {gap_stops}")
print(f"  Intraday: {intraday_stops}")
print(f"  Bear Exit: {bear_exits}")
print(f"  Total: {gap_stops + intraday_stops + bear_exits}")

print(f"\n📈 TRADES:")
print(f"  Long Entries: {long_entries}")
print(f"  Short Hedges: {short_entries}")

print(f"\n💰 PERFORMANCE:")
print(f"  Start: ${initial_capital:,.2f}")
print(f"  Final: ${final_equity:,.2f}")
print(f"  Return: {total_return:.2f}%")
print(f"  Peak: ${peak_equity:,.2f}")
print(f"  Max DD: ${max_drawdown:,.2f} ({max_drawdown/peak_equity*100:.1f}%)")

if len(winning_trades) > 0 and len(losing_trades) > 0:
    print(f"\n📊 WIN/LOSS:")
    print(f"  Win Rate: {len(winning_trades)/len(trades_with_pnl)*100:.1f}%")
    print(f"  Avg Win: ${winning_trades['pnl'].mean():,.2f}")
    print(f"  Avg Loss: ${losing_trades['pnl'].mean():,.2f}")
    profit_factor = abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum())
    print(f"  Profit Factor: {profit_factor:.2f}")

print("=" * 70)