"""
BACKTEST WITH TRAILING STOP
Matching final production logic
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

STOP_PCT = 0.019

def get_leverage(vix):
    if vix < 12:
        return 3.75
    elif vix < 13:
        return 3.5
    elif vix < 14:
        return 3.25
    else:
        return 3.0

equity_series = []
dates_list = []
trades = []

equity = 100000.0
position = {'shares': 0, 'entry': 0, 'stop_price': 0}

stop_count = 0
bear_exit_count = 0

for i in range(125, len(df)):
    date = df.index[i]
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix_close.iloc[i]):
        continue
    
    # STOP CHECK (trailing)
    if position['shares'] > 0:
        worst_price = smh_low.iloc[i]
        
        if worst_price <= position['stop_price']:
            pnl = position['shares'] * (position['stop_price'] - position['entry'])
            equity += pnl
            
            trades.append({
                'date': date,
                'action': 'STOP',
                'entry': position['entry'],
                'stop': position['stop_price'],
                'pnl': pnl
            })
            
            position = {'shares': 0, 'entry': 0, 'stop_price': 0}
            stop_count += 1
    
    # BEAR EXIT
    if position['shares'] > 0 and not bull.iloc[i]:
        exit_price = smh_close.iloc[i]
        pnl = position['shares'] * (exit_price - position['entry'])
        equity += pnl
        
        trades.append({
            'date': date,
            'action': 'BEAR_EXIT',
            'entry': position['entry'],
            'exit': exit_price,
            'pnl': pnl
        })
        
        position = {'shares': 0, 'entry': 0, 'stop_price': 0}
        bear_exit_count += 1
    
    # ENTRY
    if position['shares'] == 0 and bull.iloc[i]:
        vix = vix_close.iloc[i]
        lev = get_leverage(vix)
        entry_price = smh_close.iloc[i]
        shares = int((equity * lev) / entry_price)
        
        initial_stop = entry_price * (1 - STOP_PCT)
        
        position = {
            'shares': shares,
            'entry': entry_price,
            'stop_price': initial_stop
        }
        
        trades.append({
            'date': date,
            'action': 'ENTER',
            'price': entry_price,
            'leverage': lev,
            'stop': initial_stop
        })
    
    # TRAILING STOP (move UP only at close)
    if position['shares'] > 0:
        close = smh_close.iloc[i]
        new_stop = close * (1 - STOP_PCT)
        
        if new_stop > position['stop_price']:
            position['stop_price'] = new_stop
    
    # EOD EQUITY
    if position['shares'] > 0:
        unrealized = position['shares'] * (smh_close.iloc[i] - position['entry'])
        total_equity = equity + unrealized
    else:
        total_equity = equity
    
    equity_series.append(total_equity)
    dates_list.append(date)

# METRICS
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

print("=" * 80)
print("BACKTEST WITH TRAILING STOP")
print("=" * 80)
print(f"CAGR: {cagr:.2f}%")
print(f"Max DD: {max_dd:.2f}%")
print(f"MAR: {mar:.2f}")
print(f"Final: ${final:,.2f}")
print(f"Stops: {stop_count}")
print(f"Bear Exits: {bear_exit_count}")

trades_df = pd.DataFrame(trades)
trades_df.to_csv('TRAILING_STOP_trades.csv', index=False)

pd.DataFrame({
    'date': dates_list,
    'equity': equity_array
}).to_csv('TRAILING_STOP_equity.csv', index=False)

print("\n✅ Files saved")
print("=" * 80)