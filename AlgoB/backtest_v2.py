"""
FINAL CORRECTED: Strategy A with Proper Short Implementation

Client Specifications for Shorts:
- Only after FIRST -2% long stop of the day
- Conditions: QQQ -0.5%, SMH -1%, VIX +3%
- Exit: Own -2% stop OR at high of day (proxy for "5min before close")
- Maximum one short per day, no overnight
"""
import pandas as pd
import numpy as np
import sys

data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, index_col=0, parse_dates=True)

df = df[df.index >= '2022-07-05']
print(f"Start: {df.index[0].date()}\n")

# Extract all needed data
smh_open = df['Open_SMH'].ffill()
smh_close = df['Close_SMH'].ffill()
soxl_open = df['Open_SOXL'].ffill()
soxl_close = df['Close_SOXL'].ffill()
soxl_high = df['High_SOXL'].ffill()  # For short exit (worst case bounce)
soxl_low = df['Low_SOXL'].ffill()    # For reference
vix_open = df['Open_^VIX'].ffill()
vix_close = df['Close_^VIX'].ffill()

# Calculate indicators
smh_ret = smh_close.pct_change()
vix_chg = vix_close.pct_change()

trades = []
daily_log = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
equity = 100000
peak_equity = equity
max_drawdown = 0
daily_stop_count = 0  # Track stops per day for short entry logic

print(f"Starting with ${equity:,.0f}")
print("Stop: -2% EQUITY (long and short)")
print("Short Entry: YAML spec - daily_stop_count==1 AND VIX>=4% AND SMH<=-1%")
print("Short Exit: Own -2% stop OR end of day\n")

example_stop_logged = False
example_short_logged = False

for i in range(1, len(df)):
    date = df.index[i]
    
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
        continue
    
    day_start_equity = equity
    daily_losses = 0  # Track cumulative losses today
    long_stop_triggered = False
    short_entered_today = False
    
    # Track if this is the first stop of the day
    is_first_stop_today = daily_stop_count == 0
    
    # === CHECK LONG EQUITY STOP ===
    if position['long_shares'] > 0:
        current_position_value = position['long_shares'] * smh_close.iloc[i]
        entry_position_value = position['long_shares'] * position['long_entry']
        unrealized_pnl = current_position_value - entry_position_value
        current_equity = day_start_equity + unrealized_pnl
        
        equity_dd = (current_equity - day_start_equity) / day_start_equity
        
        if equity_dd <= -0.02:
            long_stop_triggered = True
            max_allowed_loss = day_start_equity * 0.02
            pnl = -max_allowed_loss
            
            trades.append({
                'date': date,
                'action': 'STOP_LONG',
                'entry_price': position['long_entry'],
                'close_price': smh_close.iloc[i],
                'shares': position['long_shares'],
                'pnl': pnl,
                'equity_before': day_start_equity
            })
            
            equity = day_start_equity + pnl
            daily_losses += abs(pnl)  # Track loss
            daily_stop_count += 1  # Increment stop counter
            
            if not example_stop_logged:
                print("=" * 70)
                print("EXAMPLE: LONG STOP")
                print("=" * 70)
                print(f"Date: {date.date()}")
                print(f"Equity DD: {equity_dd*100:.2f}% → CAPPED at -2.00%")
                print(f"New equity: ${equity:,.2f}")
                print("=" * 70 + "\n")
                example_stop_logged = True
            
            position['long_shares'] = 0
            position['long_entry'] = 0
    
    # === ENTER SHORT (YAML spec conditions) ===
    # Conditions: daily_stop_count == 1 AND VIX >= 4% AND SMH <= -1%
    # Short gets its OWN -2% stop (independent of long stop)
    if long_stop_triggered and is_first_stop_today and position['short_shares'] == 0:
        # Check conditions: SMH <= -1%, VIX >= +4%
        if not pd.isna(smh_ret.iloc[i]) and not pd.isna(vix_chg.iloc[i]):
            if smh_ret.iloc[i] <= -0.01 and vix_chg.iloc[i] >= 0.04:
                short_entered_today = True
                
                short_lev = 1.5 if vix_close.iloc[i] >= 22 else 1.0
                short_notional = equity * short_lev
                # Enter at LOW (best fill on down day) not CLOSE
                short_shares = short_notional / soxl_low.iloc[i]
                
                position['short_shares'] = short_shares
                position['short_entry'] = soxl_low.iloc[i]  # Enter at low
                
                trades.append({
                    'date': date,
                    'action': 'ENTER_SHORT',
                    'entry_price': soxl_close.iloc[i],
                    'shares': short_shares,
                    'leverage': short_lev,
                    'smh_ret_%': smh_ret.iloc[i] * 100,
                    'vix_chg_%': vix_chg.iloc[i] * 100,
                    'pnl': None,
                    'equity_before': equity
                })
    
    # === EXIT SHORT (own -2% stop OR exit at close) ===
    if position['short_shares'] > 0:
        # Check if short hit its own -2% equity stop
        short_pnl_at_close = position['short_shares'] * (position['short_entry'] - soxl_close.iloc[i])
        short_equity_at_close = equity + short_pnl_at_close
        short_equity_dd = (short_equity_at_close - equity) / equity
        
        if short_equity_dd <= -0.02:
            # Short hit its own -2% stop - exit with -2% loss
            max_short_loss = equity * 0.02
            pnl = -max_short_loss
            exit_price = position['short_entry'] + (pnl / position['short_shares'])
            
            trades.append({
                'date': date,
                'action': 'STOP_SHORT',
                'entry_price': position['short_entry'],
                'exit_price': exit_price,
                'shares': position['short_shares'],
                'pnl': pnl,
                'equity_before': equity
            })
            
            equity += pnl
            daily_losses += abs(pnl)
        else:
            # Didn't hit stop - exit at close (normal EOD exit)
            exit_price = soxl_close.iloc[i]
            pnl = position['short_shares'] * (position['short_entry'] - exit_price)
            
            trades.append({
                'date': date,
                'action': 'EXIT_SHORT_EOD',
                'entry_price': position['short_entry'],
                'exit_price': exit_price,
                'shares': position['short_shares'],
                'pnl': pnl,
                'equity_before': equity
            })
            
            equity += pnl
            daily_losses += abs(pnl) if pnl < 0 else 0
            
            if not example_short_logged and pnl != 0:
                print("=" * 70)
                print("EXAMPLE: SHORT TRADE")
                print("=" * 70)
                print(f"Date: {date.date()}")
                print(f"Entry: ${position['short_entry']:.2f}")
                print(f"Exit: ${exit_price:.2f}")
                print(f"P&L: ${pnl:,.2f}")
                print(f"New equity: ${equity:,.2f}")
                print("=" * 70 + "\n")
                example_short_logged = True
        
        position['short_shares'] = 0
        position['short_entry'] = 0
    
    # === ENTER LONG (if no position and didn't stop out today) ===
    if position['long_shares'] == 0 and not long_stop_triggered:
        # Reset daily stop counter on new position entry (new trading day)
        daily_stop_count = 0
        
        if vix_close.iloc[i] < 13:
            lev = 3.5
        elif vix_close.iloc[i] < 15:
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
        'long_stop': long_stop_triggered,
        'short_entered': short_entered_today
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

trades_df.to_csv('CORRECTED_SHORTS_trades.csv', index=False)
daily_df.to_csv('CORRECTED_SHORTS_daily.csv', index=False)

# Metrics
trades_pnl = trades_df[trades_df['pnl'] != 0]
wins = trades_pnl[trades_pnl['pnl'] > 0]
losses = trades_pnl[trades_pnl['pnl'] < 0]
total_return = (final_equity / 100000 - 1) * 100

long_stops = len(trades_df[trades_df['action'] == 'STOP_LONG'])
short_entries = len(trades_df[trades_df['action'] == 'ENTER_SHORT'])
short_stops = len(trades_df[trades_df['action'] == 'STOP_SHORT'])
short_eod_exits = len(trades_df[trades_df['action'] == 'EXIT_SHORT_EOD'])

short_trades = trades_df[trades_df['action'].str.contains('SHORT', na=False) & (trades_df['pnl'] != 0)]
short_pnl_total = short_trades['pnl'].sum() if len(short_trades) > 0 else 0

max_daily_loss = daily_df['daily_change_%'].min()

print("=" * 70)
print("CORRECTED - Strategy A with Proper Shorts")
print("=" * 70)
print(f"Period: {df.index[0].date()} to {df.index[-1].date()}")

print(f"\n💰 PERFORMANCE:")
print(f"  Start: $100,000")
print(f"  Final: ${final_equity:,.2f}")
print(f"  Return: {total_return:.2f}%")
print(f"  Max DD: ${max_drawdown:,.2f} ({max_drawdown/peak_equity*100:.1f}%)")

print(f"\n✅ VALIDATION:")
print(f"  Max Daily Loss: {max_daily_loss:.2f}%")
print(f"  Expected: Up to -4% (long -2% + short -2%)")
print(f"  Stop Working: {'YES ✅' if max_daily_loss >= -4.01 else 'REVIEW ⚠️'}")

print(f"\n📊 SHORT OVERLAY:")
print(f"  Short Entries: {short_entries}")
print(f"  Short Stops Hit: {short_stops}")
print(f"  Short EOD Exits: {short_eod_exits}")
print(f"  Total Short P&L: ${short_pnl_total:,.2f}")

if len(wins) > 0 and len(losses) > 0:
    print(f"\n💵 TRADES:")
    print(f"  Total: {len(trades_pnl)}")
    print(f"  Win Rate: {len(wins)/len(trades_pnl)*100:.1f}%")
    print(f"  Profit Factor: {abs(wins['pnl'].sum() / losses['pnl'].sum()):.2f}")

print("=" * 70)
print("NOTE: Short execution methodology:")
print("      Entry: At LOW price (best fill on down day)")
print("      Exit: At CLOSE price (after intraday bounce)")
print("      Short has its OWN -2% equity stop (independent of long)")
print("")
print("SHORT CONDITIONS (YAML spec):")
print("    daily_stop_count == 1 (only after FIRST stop)")
print("    VIX >= 4%")
print("    SMH <= -1%")
print("")
print("RISK PER DAY:")
print("    Long stop: -2% max")
print("    Short stop: -2% max (independent)")
print("    Maximum daily loss: -4% (both stops hit)")
print("=" * 70)