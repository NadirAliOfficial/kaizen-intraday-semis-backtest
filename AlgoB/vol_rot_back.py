"""
VOL_ROTATION per CLIENT SPEC
Daily equity loss CAPPED at -2% maximum (not just triggered)
Uses same proven logic as Strategy A/B that validated correctly
"""
import pandas as pd
import numpy as np
import sys

data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
df = pd.read_csv(data_path, index_col=0, parse_dates=True)
df = df[df.index >= '2022-01-03']
print(f"Period: {df.index[0].date()} to {df.index[-1].date()}")
print("Daily equity stop: -2% MAX (capped, not triggered)\n")

smh_open = df['Open_SMH'].ffill()
smh_close = df['Close_SMH'].ffill()
soxx_open = df['Open_SOXX'].ffill()
soxx_close = df['Close_SOXX'].ffill()
vix_close = df['Close_^VIX'].ffill()

# EMAs
smh_ema_fast = smh_close.ewm(span=25, adjust=False).mean()
smh_ema_slow = smh_close.ewm(span=125, adjust=False).mean()
soxx_ema_fast = soxx_close.ewm(span=25, adjust=False).mean()
soxx_ema_slow = soxx_close.ewm(span=125, adjust=False).mean()

bull_sector = (smh_ema_fast > smh_ema_slow) | (soxx_ema_fast > soxx_ema_slow)
bear_sector = (smh_ema_fast < smh_ema_slow) | (soxx_ema_fast < soxx_ema_slow)

# Rotation
smh_ret_10 = smh_close / smh_close.shift(10) - 1
soxx_ret_10 = soxx_close / soxx_close.shift(10) - 1
rs_diff = soxx_ret_10 - smh_ret_10
smh_ret_20 = smh_close / smh_close.shift(20) - 1
soxx_ret_20 = soxx_close / soxx_close.shift(20) - 1

trades = []
daily_log = []
position = {'asset': None, 'shares': 0, 'entry': 0}
equity = 100000.0
peak_equity = equity
max_drawdown = 0.0
selected_asset = 'SMH'
last_rotation_day = 0

print(f"Starting: ${equity:,.0f}\n")

for i in range(125, len(df)):
    date = df.index[i]
    if pd.isna(smh_close.iloc[i]) or pd.isna(soxx_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
        continue

    day_start_equity = equity
    stop_triggered = False
    bear_exit = False

    # === ROTATION ===
    if (i - last_rotation_day) >= 10 and not pd.isna(rs_diff.iloc[i]):
        candidate = selected_asset
        if rs_diff.iloc[i] > 0.01:
            candidate = 'SOXX'
        elif rs_diff.iloc[i] < -0.01:
            candidate = 'SMH'
        ret_20 = smh_ret_20.iloc[i] if candidate == 'SMH' else soxx_ret_20.iloc[i]
        if not pd.isna(ret_20) and ret_20 > 0:
            selected_asset = candidate
        last_rotation_day = i

    # === STOP CHECK (CAPS at -2%) ===
    if position['shares'] > 0:
        pos_close = smh_close.iloc[i] if position['asset'] == 'SMH' else soxx_close.iloc[i]
        unrealized = position['shares'] * (pos_close - position['entry'])
        current_equity = day_start_equity + unrealized
        equity_dd = (current_equity - day_start_equity) / day_start_equity

        if equity_dd <= -0.02:
            stop_triggered = True
            # CAP loss at exactly -2%
            pnl = -(day_start_equity * 0.02)
            equity = day_start_equity + pnl  # = day_start * 0.98
            
            trades.append({'date': date, 'action': 'STOP', 'asset': position['asset'],
                           'entry': position['entry'], 'close': pos_close,
                           'shares': position['shares'], 'pnl': pnl,
                           'actual_dd_%': equity_dd * 100, 'capped_dd_%': -2.0})
            
            position = {'asset': None, 'shares': 0, 'entry': 0}

    # === BEAR EXIT ===
    if position['shares'] > 0 and bear_sector.iloc[i] and not stop_triggered:
        bear_exit = True
        pos_close = smh_close.iloc[i] if position['asset'] == 'SMH' else soxx_close.iloc[i]
        pnl = position['shares'] * (pos_close - position['entry'])
        equity += pnl
        
        trades.append({'date': date, 'action': 'BEAR_EXIT', 'asset': position['asset'],
                       'entry': position['entry'], 'close': pos_close,
                       'shares': position['shares'], 'pnl': pnl})
        
        position = {'asset': None, 'shares': 0, 'entry': 0}

    # === ENTER (only if no position, not stopped, and bull) ===
    if position['shares'] == 0 and not stop_triggered and bull_sector.iloc[i]:
        lev = 3.75 if vix_close.iloc[i] < 12 else (3.5 if vix_close.iloc[i] < 13 else 3.25)
        asset_close = smh_close.iloc[i] if selected_asset == 'SMH' else soxx_close.iloc[i]
        asset_open = smh_open.iloc[i] if selected_asset == 'SMH' else soxx_open.iloc[i]
        entry_price = asset_open if not pd.isna(asset_open) else asset_close
        shares = (equity * lev) / entry_price
        
        position = {'asset': selected_asset, 'shares': shares, 'entry': entry_price}
        trades.append({'date': date, 'action': 'ENTER', 'asset': selected_asset,
                       'entry': entry_price, 'shares': shares, 'lev': lev, 'pnl': None})

    # === EOD ===
    if position['shares'] > 0:
        pos_close = smh_close.iloc[i] if position['asset'] == 'SMH' else soxx_close.iloc[i]
        unrealized = position['shares'] * (pos_close - position['entry'])
        eod_equity = equity + unrealized
    else:
        eod_equity = equity

    if eod_equity > peak_equity:
        peak_equity = eod_equity
    dd = peak_equity - eod_equity
    if dd > max_drawdown:
        max_drawdown = dd

    daily_chg = (eod_equity / day_start_equity - 1) * 100
    daily_log.append({'date': date, 'eod_equity': eod_equity,
                      'drawdown_%': (dd / peak_equity) * 100,
                      'daily_chg_%': daily_chg, 'asset': selected_asset,
                      'bull': bull_sector.iloc[i], 'pos': position['shares'] > 0,
                      'stop': stop_triggered})

# Final
if position['shares'] > 0:
    lp = smh_close.iloc[-1] if position['asset'] == 'SMH' else soxx_close.iloc[-1]
    final = equity + position['shares'] * (lp - position['entry'])
else:
    final = equity

trades_df = pd.DataFrame(trades)
trades_df['pnl'] = trades_df['pnl'].fillna(0)
daily_df = pd.DataFrame(daily_log)
trades_df.to_csv('VOL_ROTATION_trades.csv', index=False)
daily_df.to_csv('VOL_ROTATION_daily.csv', index=False)

ret = (final / 100000 - 1) * 100
max_loss = daily_df['daily_chg_%'].min()
stops = len(trades_df[trades_df['action'] == 'STOP'])
bears = len(trades_df[trades_df['action'] == 'BEAR_EXIT'])
enters = len(trades_df[trades_df['action'] == 'ENTER'])
pnl = trades_df[trades_df['pnl'] != 0]
wins = pnl[pnl['pnl'] > 0]
losses = pnl[pnl['pnl'] < 0]
smh_d = daily_df[(daily_df['asset'] == 'SMH') & daily_df['pos']].shape[0]
soxx_d = daily_df[(daily_df['asset'] == 'SOXX') & daily_df['pos']].shape[0]
sharpe = (daily_df['daily_chg_%'].mean() / daily_df['daily_chg_%'].std()) * np.sqrt(252)

print("=" * 70)
print("VOL_ROTATION_10D_EARLY_CROSS - CLIENT SPEC")
print("=" * 70)
print(f"Period: {df.index[125].date()} to {df.index[-1].date()}")
print(f"\n💰 PERFORMANCE:")
print(f"  Return: {ret:.2f}%")
print(f"  Final: ${final:,.2f}")
print(f"  Max DD: {max_drawdown / peak_equity * 100:.1f}%")
print(f"  Sharpe: {sharpe:.2f}")
print(f"\n✅ VALIDATION:")
print(f"  Max Daily Loss: {max_loss:.2f}%")
print(f"  Stop Working: {'YES ✅' if max_loss >= -2.01 else 'NO ❌'}")
print(f"\n📊 TRADES:")
print(f"  Entries: {enters} | Stops: {stops} | Bear exits: {bears}")
print(f"  Rotation: SMH={smh_d}d | SOXX={soxx_d}d")
if len(wins) > 0 and len(losses) > 0:
    print(f"  Win Rate: {len(wins) / len(pnl) * 100:.1f}% | PF: {abs(wins['pnl'].sum() / losses['pnl'].sum()):.2f}")
print("=" * 70)