"""
CORRECTED PRODUCTION BACKTEST
Properly tracking equity and position value
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

STOP_LOSS_PCT = 0.018
STOP_BUFFER = 0.001
REBALANCE_THRESHOLD = 50

def get_leverage(vix):
    if vix < 12:
        return 3.75
    elif vix < 13:
        return 3.5
    elif vix < 14:
        return 3.25
    else:
        return 3.0

# Backtest - SIMPLIFIED, NO REBALANCING
equity_series = []
dates_list = []
trades = []

cash = 100000.0  # Cash equity
position = {'shares': 0, 'entry': 0}

stop_count = 0
bear_exit_count = 0

for i in range(125, len(df)):
    date = df.index[i]
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
        continue
    
    day_start_cash = cash
    
    # STOP CHECK
    if position['shares'] > 0:
        worst_price = smh_low.iloc[i]
        position_value = position['shares'] * worst_price
        entry_value = position['shares'] * position['entry']
        dd = (position_value - entry_value) / entry_value
        
        if dd <= -(STOP_LOSS_PCT + STOP_BUFFER):
            # Exit at stop
            exit_value = position['shares'] * worst_price
            pnl = exit_value - (position['shares'] * position['entry'])
            # Cap loss
            if pnl < -(day_start_cash * STOP_LOSS_PCT):
                pnl = -(day_start_cash * STOP_LOSS_PCT)
            
            cash = day_start_cash + pnl
            
            trades.append({
                'date': date,
                'action': 'STOP',
                'shares': position['shares'],
                'entry': position['entry'],
                'exit': worst_price,
                'pnl': pnl,
                'cash': cash
            })
            
            position = {'shares': 0, 'entry': 0}
            stop_count += 1
    
    # BEAR EXIT
    if position['shares'] > 0 and not bull.iloc[i]:
        exit_price = smh_close.iloc[i]
        pnl = position['shares'] * (exit_price - position['entry'])
        cash = day_start_cash + pnl
        
        trades.append({
            'date': date,
            'action': 'BEAR_EXIT',
            'shares': position['shares'],
            'entry': position['entry'],
            'exit': exit_price,
            'pnl': pnl,
            'cash': cash
        })
        
        position = {'shares': 0, 'entry': 0}
        bear_exit_count += 1
    
    # ENTRY
    if position['shares'] == 0 and bull.iloc[i]:
        vix = vix_close.iloc[i]
        lev = get_leverage(vix)
        entry_price = smh_close.iloc[i]
        shares = int((cash * lev) / entry_price)
        
        position = {'shares': shares, 'entry': entry_price}
        
        trades.append({
            'date': date,
            'action': 'ENTER',
            'shares': shares,
            'price': entry_price,
            'leverage': lev,
            'vix': vix,
            'cash': cash
        })
    
    # EOD EQUITY
    if position['shares'] > 0:
        position_value = position['shares'] * smh_close.iloc[i]
        total_equity = cash + (position_value - position['shares'] * position['entry'])
    else:
        total_equity = cash
    
    equity_series.append(total_equity)
    dates_list.append(date)

# METRICS
equity_array = np.array(equity_series)
dates_array = pd.to_datetime(dates_list)

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

print("=" * 80)
print("CORRECTED BACKTEST - NO DAILY REBALANCING")
print("=" * 80)
print(f"\nCAGR: {cagr:.2f}%")
print(f"Max DD: {max_dd:.2f}%")
print(f"MAR: {mar:.2f}")
print(f"Final: ${final:,.2f}")
print(f"\nStops: {stop_count}")
print(f"Bear Exits: {bear_exit_count}")

trades_df = pd.DataFrame(trades)
entries = trades_df[trades_df['action'] == 'ENTER']
if len(entries) > 0:
    print(f"\nLeverage usage:")
    print(entries['leverage'].value_counts().sort_index())

print("=" * 80)