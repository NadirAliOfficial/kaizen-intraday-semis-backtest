"""
Backtest for EMA 25/125 Crossover Strategy v2.3.2
Run: python backtest_ema_crossover.py [path/to/data.csv]
"""
import pandas as pd
import numpy as np
import sys

# Load data
data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, header=[0, 1], index_col=0, parse_dates=True)
df.columns = ['_'.join(col).strip() for col in df.columns.values]

# Extract series and forward fill NaN
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
equity_curve = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
initial_capital = 100000
equity = initial_capital

print(f"Starting backtest with ${initial_capital:,.0f}...")
print(f"Strategy: EMA 25/125 Crossover\n")

# Main loop
for i in range(125, len(df)):  # Start after EMA_SLOW warmup
    date = df.index[i]
    
    # Skip if we have NaN values
    if pd.isna(smh_close.iloc[i]) or pd.isna(vix.iloc[i]) or pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]):
        continue
    
    # Update equity from existing positions
    if position['long_shares'] > 0:
        long_pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        equity = initial_capital + long_pnl
        
        if position['short_shares'] > 0:
            short_pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
            equity += short_pnl
    else:
        equity = initial_capital
    
    equity_curve.append({
        'date': date, 
        'equity': equity, 
        'smh': smh_close.iloc[i], 
        'vix': vix.iloc[i],
        'ema_fast': ema_fast.iloc[i],
        'ema_slow': ema_slow.iloc[i],
        'bull': bull.iloc[i],
        'long_shares': position['long_shares'],
        'short_shares': position['short_shares']
    })
    
    # 1. Check daily stop loss on long position
    if position['long_shares'] > 0 and not pd.isna(prev_close.iloc[i]):
        dd = (smh_close.iloc[i] - prev_close.iloc[i]) / prev_close.iloc[i]
        if dd <= -0.02:
            pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
            trades.append({
                'date': date, 
                'action': 'STOP_LOSS_LONG', 
                'asset': 'SMH',
                'entry_price': position['long_entry'],
                'exit_price': smh_close.iloc[i], 
                'shares': position['long_shares'],
                'pnl': pnl, 
                'dd_pct': dd * 100, 
                'bull': bull.iloc[i],
                'equity_before': equity
            })
            initial_capital += pnl
            equity = initial_capital
            position['long_shares'] = 0
            position['long_entry'] = 0
    
    # 2. Enter long if bull market and no position
    if position['long_shares'] == 0 and bull.iloc[i]:
        # Determine leverage
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
            'asset': 'SMH',
            'entry_price': smh_close.iloc[i],
            'exit_price': None,
            'shares': shares, 
            'notional': notional,
            'leverage': lev,
            'vix': vix.iloc[i],
            'gap_up': gap_up.iloc[i],
            'ema_fast': ema_fast.iloc[i],
            'ema_slow': ema_slow.iloc[i],
            'pnl': None, 
            'equity_before': equity
        })
    
    # 3. Exit long if bear market (EMA crossover down)
    if position['long_shares'] > 0 and not bull.iloc[i]:
        pnl = position['long_shares'] * (smh_close.iloc[i] - position['long_entry'])
        trades.append({
            'date': date, 
            'action': 'EXIT_LONG_BEAR', 
            'asset': 'SMH',
            'entry_price': position['long_entry'],
            'exit_price': smh_close.iloc[i], 
            'shares': position['long_shares'],
            'pnl': pnl,
            'ema_fast': ema_fast.iloc[i],
            'ema_slow': ema_slow.iloc[i],
            'equity_before': equity
        })
        initial_capital += pnl
        equity = initial_capital
        position['long_shares'] = 0
        position['long_entry'] = 0
    
    # 4. Check short entry conditions (only if bull market for re-entry)
    if vix_chg.iloc[i] >= 0.02 and smh_ret.iloc[i] <= -0.005 and position['short_shares'] == 0:
        short_lev = 1.5 if vix.iloc[i] >= 22 else 1.0
        short_notional = equity * short_lev
        short_shares = short_notional / soxl.iloc[i]
        
        position['short_shares'] = short_shares
        position['short_entry'] = soxl.iloc[i]
        
        trades.append({
            'date': date, 
            'action': 'ENTER_SHORT', 
            'asset': 'SOXL',
            'entry_price': soxl.iloc[i],
            'exit_price': None,
            'shares': short_shares, 
            'notional': short_notional,
            'leverage': short_lev,
            'vix': vix.iloc[i], 
            'vix_chg_pct': vix_chg.iloc[i] * 100, 
            'smh_ret_pct': smh_ret.iloc[i] * 100,
            'bull': bull.iloc[i],
            'pnl': None, 
            'equity_before': equity
        })
    
    # 5. Exit short at close, then re-enter long if bull
    if position['short_shares'] > 0:
        pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
        trades.append({
            'date': date, 
            'action': 'EXIT_SHORT', 
            'asset': 'SOXL',
            'entry_price': position['short_entry'],
            'exit_price': soxl.iloc[i], 
            'shares': position['short_shares'],
            'pnl': pnl,
            'bull': bull.iloc[i],
            'equity_before': equity
        })
        initial_capital += pnl
        equity = initial_capital
        position['short_shares'] = 0
        position['short_entry'] = 0
        
        # Re-enter long if still bull market
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
                'asset': 'SMH',
                'entry_price': smh_close.iloc[i],
                'exit_price': None,
                'shares': shares, 
                'notional': notional,
                'leverage': lev,
                'vix': vix.iloc[i],
                'pnl': None, 
                'equity_before': equity
            })

# Calculate final equity
final_equity = initial_capital
if position['long_shares'] > 0:
    last_smh = smh_close.dropna().iloc[-1]
    final_long_pnl = position['long_shares'] * (last_smh - position['long_entry'])
    final_equity += final_long_pnl
    print(f"\nOpen Position: {position['long_shares']:.2f} shares SMH @ ${position['long_entry']:.2f}")
    print(f"Current Price: ${last_smh:.2f}, Unrealized P&L: ${final_long_pnl:,.2f}")

if position['short_shares'] > 0:
    last_soxl = soxl.dropna().iloc[-1]
    final_short_pnl = position['short_shares'] * (position['short_entry'] - last_soxl)
    final_equity += final_short_pnl

# Create DataFrames
trades_df = pd.DataFrame(trades)
trades_df['pnl'] = trades_df['pnl'].fillna(0)
equity_df = pd.DataFrame(equity_curve)

# Save outputs
trades_df.to_csv('backtest_ema_trades.csv', index=False)
equity_df.to_csv('backtest_ema_equity.csv', index=False)

# Calculate metrics
trades_with_pnl = trades_df[trades_df['pnl'] != 0]
winning_trades = trades_with_pnl[trades_with_pnl['pnl'] > 0]
losing_trades = trades_with_pnl[trades_with_pnl['pnl'] < 0]
total_pnl = final_equity - 100000
total_return = (final_equity / 100000 - 1) * 100

# Get trade counts
long_entries = len(trades_df[trades_df['action'].isin(['ENTER_LONG', 'REENTER_LONG'])])
short_entries = len(trades_df[trades_df['action'] == 'ENTER_SHORT'])
short_exits = len(trades_df[trades_df['action'] == 'EXIT_SHORT'])
stop_losses = len(trades_df[trades_df['action'] == 'STOP_LOSS_LONG'])
bear_exits = len(trades_df[trades_df['action'] == 'EXIT_LONG_BEAR'])

# Calculate bull/bear periods
bull_days = bull.iloc[125:].sum()
bear_days = len(bull.iloc[125:]) - bull_days

# Summary
print("\n" + "=" * 70)
print("BACKTEST RESULTS - EMA 25/125 Crossover Strategy")
print("=" * 70)
print(f"Period: {df.index[125].date()} to {df.index[-1].date()}")
print(f"Total Trading Days: {len(df) - 125}")
print(f"Bull Market Days: {bull_days} ({bull_days/(len(df)-125)*100:.1f}%)")
print(f"Bear Market Days: {bear_days} ({bear_days/(len(df)-125)*100:.1f}%)")

print(f"\nTRADE STATISTICS:")
print(f"  Total Trade Events: {len(trades_df)}")
print(f"  Long Entries: {long_entries}")
print(f"  Short Entries: {short_entries}")
print(f"  Short Exits: {short_exits}")
print(f"  Stop Losses Hit: {stop_losses}")
print(f"  Bear Market Exits: {bear_exits}")

print(f"\nWIN/LOSS ANALYSIS:")
if len(trades_with_pnl) > 0:
    print(f"  Trades with P&L: {len(trades_with_pnl)}")
    print(f"  Winning Trades: {len(winning_trades)} ({len(winning_trades)/len(trades_with_pnl)*100:.1f}%)")
    print(f"  Losing Trades: {len(losing_trades)} ({len(losing_trades)/len(trades_with_pnl)*100:.1f}%)")
    if len(winning_trades) > 0:
        print(f"  Avg Win: ${winning_trades['pnl'].mean():,.2f}")
        print(f"  Total Wins: ${winning_trades['pnl'].sum():,.2f}")
    if len(losing_trades) > 0:
        print(f"  Avg Loss: ${losing_trades['pnl'].mean():,.2f}")
        print(f"  Total Losses: ${losing_trades['pnl'].sum():,.2f}")
    print(f"  Largest Win: ${trades_with_pnl['pnl'].max():,.2f}")
    print(f"  Largest Loss: ${trades_with_pnl['pnl'].min():,.2f}")
    
    if len(winning_trades) > 0 and len(losing_trades) > 0:
        profit_factor = abs(winning_trades['pnl'].sum() / losing_trades['pnl'].sum())
        print(f"  Profit Factor: {profit_factor:.2f}")

print(f"\nPERFORMANCE:")
print(f"  Starting Capital: ${100000:,.2f}")
print(f"  Realized P&L: ${initial_capital - 100000:,.2f}")
print(f"  Final Equity: ${final_equity:,.2f}")
print(f"  Total P&L: ${total_pnl:,.2f}")
print(f"  Total Return: {total_return:.2f}%")
print(f"  Max Equity: ${equity_df['equity'].max():,.2f}")
print(f"  Min Equity: ${equity_df['equity'].min():,.2f}")
print(f"  Max Drawdown $: ${100000 - equity_df['equity'].min():,.2f}")

# Calculate Sharpe ratio
if len(equity_df) > 1:
    daily_returns = equity_df['equity'].pct_change().dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe_approx = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        print(f"  Sharpe Ratio (approx): {sharpe_approx:.2f}")

print(f"\nOUTPUTS:")
print(f"  Trades: backtest_ema_trades.csv ({len(trades_df)} rows)")
print(f"  Equity Curve: backtest_ema_equity.csv ({len(equity_df)} rows)")

# Additional insights
print(f"\nKEY INSIGHTS:")
print(f"  Stop Loss Rate: {stop_losses}/{long_entries} ({stop_losses/long_entries*100:.1f}% of longs)")
print(f"  Bear Exit Rate: {bear_exits}/{long_entries} ({bear_exits/long_entries*100:.1f}% of longs)")
print(f"  Short Hedge Rate: {short_entries}/{len(df)-125} days ({short_entries/(len(df)-125)*100:.1f}%)")
if len(trades_with_pnl) > 0:
    avg_pnl = trades_with_pnl['pnl'].mean()
    print(f"  Avg P&L per Trade: ${avg_pnl:,.2f}")
print("=" * 70)