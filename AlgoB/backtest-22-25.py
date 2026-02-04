"""
Minimal Backtest for PIÑON_FIJO_DYNAMIC Algorithm (2022-2025)
"""
import pandas as pd
import numpy as np
import sys

# Load data - FLAT structure
data_path = sys.argv[1] if len(sys.argv) > 1 else 'AlgoB/market_data.csv'
print(f"Loading data from {data_path}...")
df = pd.read_csv(data_path, index_col=0, parse_dates=True)

# Extract series directly (flat columns)
smh = df['Close_SMH'].ffill()
soxl = df['Close_SOXL'].ffill()
vix = df['Close_^VIX'].ffill()

# Calculate indicators
smh_ret = smh.pct_change()
vix_chg = vix.pct_change()
prev_close = smh.shift(1)

# Initialize
trades = []
equity_curve = []
position = {'long_shares': 0, 'long_entry': 0, 'short_shares': 0, 'short_entry': 0}
initial_capital = 100000
equity = initial_capital

print(f"Starting backtest with ${initial_capital:,.0f}...\n")

# Main loop
for i in range(1, len(df)):
    date = df.index[i]
    
    if pd.isna(smh.iloc[i]) or pd.isna(vix.iloc[i]):
        continue
    
    # Update equity
    if position['long_shares'] > 0:
        long_pnl = position['long_shares'] * (smh.iloc[i] - position['long_entry'])
        equity = initial_capital + long_pnl
        
        if position['short_shares'] > 0:
            short_pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
            equity += short_pnl
    else:
        equity = initial_capital
    
    equity_curve.append({
        'date': date, 'equity': equity, 'smh': smh.iloc[i], 'vix': vix.iloc[i],
        'long_shares': position['long_shares'], 'short_shares': position['short_shares']
    })
    
    # 1. Check stop loss
    if position['long_shares'] > 0 and not pd.isna(prev_close.iloc[i]):
        dd = (smh.iloc[i] - prev_close.iloc[i]) / prev_close.iloc[i]
        if dd <= -0.02:
            pnl = position['long_shares'] * (smh.iloc[i] - position['long_entry'])
            trades.append({
                'date': date, 'action': 'STOP_LOSS_LONG', 'asset': 'SMH',
                'entry_price': position['long_entry'], 'exit_price': smh.iloc[i], 
                'shares': position['long_shares'], 'pnl': pnl, 'dd_pct': dd * 100, 
                'equity_before': equity
            })
            initial_capital += pnl
            equity = initial_capital
            position['long_shares'] = 0
            position['long_entry'] = 0
    
    # 2. Enter long
    if position['long_shares'] == 0:
        lev = 3.5 if vix.iloc[i] < 13 else (3.25 if vix.iloc[i] < 15 else 3.0)
        notional = equity * lev
        shares = notional / smh.iloc[i]
        position['long_shares'] = shares
        position['long_entry'] = smh.iloc[i]
        
        trades.append({
            'date': date, 'action': 'ENTER_LONG', 'asset': 'SMH',
            'entry_price': smh.iloc[i], 'exit_price': None, 'shares': shares, 
            'notional': notional, 'leverage': lev, 'vix': vix.iloc[i], 'pnl': None, 
            'equity_before': equity
        })
    
    # 3. Enter short
    if not pd.isna(vix_chg.iloc[i]) and not pd.isna(smh_ret.iloc[i]):
        if vix_chg.iloc[i] >= 0.02 and smh_ret.iloc[i] <= -0.005 and position['short_shares'] == 0:
            short_lev = 1.5 if vix.iloc[i] >= 22 else 1.0
            short_notional = equity * short_lev
            short_shares = short_notional / soxl.iloc[i]
            
            position['short_shares'] = short_shares
            position['short_entry'] = soxl.iloc[i]
            
            trades.append({
                'date': date, 'action': 'ENTER_SHORT', 'asset': 'SOXL',
                'entry_price': soxl.iloc[i], 'exit_price': None, 'shares': short_shares, 
                'notional': short_notional, 'leverage': short_lev, 'vix': vix.iloc[i], 
                'vix_chg_pct': vix_chg.iloc[i] * 100, 'smh_ret_pct': smh_ret.iloc[i] * 100, 
                'pnl': None, 'equity_before': equity
            })
    
    # 4. Exit short
    if position['short_shares'] > 0:
        pnl = position['short_shares'] * (position['short_entry'] - soxl.iloc[i])
        trades.append({
            'date': date, 'action': 'EXIT_SHORT', 'asset': 'SOXL',
            'entry_price': position['short_entry'], 'exit_price': soxl.iloc[i], 
            'shares': position['short_shares'], 'pnl': pnl, 'equity_before': equity
        })
        initial_capital += pnl
        equity = initial_capital + (position['long_shares'] * (smh.iloc[i] - position['long_entry']) if position['long_shares'] > 0 else 0)
        position['short_shares'] = 0
        position['short_entry'] = 0

# Final equity
final_equity = initial_capital
if position['long_shares'] > 0:
    last_smh = smh.dropna().iloc[-1]
    final_long_pnl = position['long_shares'] * (last_smh - position['long_entry'])
    final_equity += final_long_pnl
    print(f"\nOpen Position: {position['long_shares']:.2f} shares SMH @ ${position['long_entry']:.2f}")
    print(f"Current Price: ${last_smh:.2f}, Unrealized P&L: ${final_long_pnl:,.2f}")

if position['short_shares'] > 0:
    last_soxl = soxl.dropna().iloc[-1]
    final_short_pnl = position['short_shares'] * (position['short_entry'] - last_soxl)
    final_equity += final_short_pnl

# Save
trades_df = pd.DataFrame(trades)
trades_df['pnl'] = trades_df['pnl'].fillna(0)
equity_df = pd.DataFrame(equity_curve)

trades_df.to_csv('backtest_trades.csv', index=False)
equity_df.to_csv('backtest_equity.csv', index=False)

# Metrics
trades_with_pnl = trades_df[trades_df['pnl'] != 0]
winning_trades = trades_with_pnl[trades_with_pnl['pnl'] > 0]
losing_trades = trades_with_pnl[trades_with_pnl['pnl'] < 0]
total_pnl = final_equity - 100000
total_return = (final_equity / 100000 - 1) * 100

long_entries = len(trades_df[trades_df['action'] == 'ENTER_LONG'])
short_entries = len(trades_df[trades_df['action'] == 'ENTER_SHORT'])
short_exits = len(trades_df[trades_df['action'] == 'EXIT_SHORT'])
stop_losses = len(trades_df[trades_df['action'] == 'STOP_LOSS_LONG'])

# Summary
print("\n" + "=" * 70)
print("BACKTEST RESULTS - PIÑON_FIJO (Always Long)")
print("=" * 70)
print(f"Period: {df.index[0].date()} to {df.index[-1].date()}")
print(f"Total Trading Days: {len(df)}")

print(f"\nTRADE STATISTICS:")
print(f"  Total Trade Events: {len(trades_df)}")
print(f"  Long Entries: {long_entries}")
print(f"  Short Entries: {short_entries}")
print(f"  Short Exits: {short_exits}")
print(f"  Stop Losses Hit: {stop_losses}")

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

if len(equity_df) > 1:
    daily_returns = equity_df['equity'].pct_change().dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe_approx = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        print(f"  Sharpe Ratio (approx): {sharpe_approx:.2f}")

print(f"\nOUTPUTS:")
print(f"  Trades: backtest_trades.csv ({len(trades_df)} rows)")
print(f"  Equity Curve: backtest_equity.csv ({len(equity_df)} rows)")

print(f"\nKEY INSIGHTS:")
print(f"  Stop Loss Rate: {stop_losses}/{long_entries} ({stop_losses/long_entries*100:.1f}% of longs)")
print(f"  Short Hedge Rate: {short_entries}/{len(df)} days ({short_entries/len(df)*100:.1f}%)")
if len(trades_with_pnl) > 0:
    avg_pnl = trades_with_pnl['pnl'].mean()
    print(f"  Avg P&L per Trade: ${avg_pnl:,.2f}")
print("=" * 70)