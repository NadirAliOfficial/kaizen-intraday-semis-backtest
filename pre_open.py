import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta

# ================== CONFIG ==================
BAR_SIZE = "5m"
TIMEZONE = pytz.timezone("America/New_York")

# Gap thresholds (from previous close to today's open)
GAP_LONG = 0.002   # 0.2% gap up
GAP_SHORT = -0.002 # 0.2% gap down

# Exit rules
STOP_LOSS = -0.015  # -1.5% stop loss
PROFIT_TARGET = 0.02  # 2% profit target

# Leverage by VIX
VIX_LOW = 15
VIX_MID = 20

# ============================================

def fetch_yfinance_intraday(symbol, lookback_days=60):
    """Fetch 5-minute intraday data"""
    print(f"Fetching {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        df = ticker.history(start=start_date, end=end_date, interval=BAR_SIZE, prepost=False)
        
        if df.empty:
            print(f"  ❌ No data for {symbol}")
            return None
        
        df = df.reset_index()
        df = df.rename(columns={'Datetime': 'date', 'Open': 'open', 'Close': 'close', 'High': 'high', 'Low': 'low'})
        
        if df['date'].dt.tz is None:
            df['date'] = df['date'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
        else:
            df['date'] = df['date'].dt.tz_convert(TIMEZONE)
        
        print(f"  ✓ {len(df)} bars ({df['date'].dt.date.nunique()} days)")
        return df[['date', 'open', 'close', 'high', 'low']]
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def fetch_daily_close(symbol, lookback_days=60):
    """Fetch daily data for previous close"""
    print(f"Fetching daily data for {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days + 10)  # Extra buffer
        
        df = ticker.history(start=start_date, end=end_date, interval="1d")
        df = df.reset_index()
        df = df.rename(columns={'Date': 'date', 'Close': 'prev_close'})
        
        if df['date'].dt.tz is None:
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(TIMEZONE)
        else:
            df['date'] = pd.to_datetime(df['date']).dt.tz_convert(TIMEZONE)
        
        df['date'] = df['date'].dt.date
        
        print(f"  ✓ {len(df)} days")
        return df[['date', 'prev_close']]
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def run_premarket_gap_backtest(intraday_data, daily_data, vix_data, initial_capital=100000):
    """
    PRE-MARKET GAP STRATEGY
    
    1. Calculate gap: (today_open - yesterday_close) / yesterday_close
    2. If gap meets threshold, enter at market open (9:30 AM)
    3. Hold during day with stops
    4. Exit at market close (3:55 PM)
    """
    
    capital = initial_capital
    daily_results = []
    bar_results = []
    
    # Prepare data
    intraday_data = intraday_data.sort_values('date').reset_index(drop=True)
    intraday_data['day'] = intraday_data['date'].dt.date
    
    # Merge previous day's close
    daily_data_shifted = daily_data.copy()
    daily_data_shifted['next_day'] = pd.to_datetime(daily_data_shifted['date']) + timedelta(days=1)
    daily_data_shifted['next_day'] = daily_data_shifted['next_day'].dt.date
    
    intraday_data = intraday_data.merge(
        daily_data_shifted[['next_day', 'prev_close']], 
        left_on='day', 
        right_on='next_day', 
        how='left'
    )
    
    # Merge VIX
    intraday_data = intraday_data.merge(vix_data, left_on='day', right_on='date', how='left', suffixes=('', '_vix'))
    intraday_data['VIX_close'] = intraday_data['VIX_close'].ffill()
    
    # Drop days without previous close
    intraday_data = intraday_data.dropna(subset=['prev_close'])
    
    print(f"✓ Data prepared: {len(intraday_data)} bars across {intraday_data['day'].nunique()} days")
    
    # Group by day
    for day, day_data in intraday_data.groupby('day'):
        day_start_capital = capital
        day_pnl = 0.0
        
        # Get first bar (9:30 AM - market open)
        first_bar = day_data.iloc[0]
        prev_close = first_bar['prev_close']
        market_open = first_bar['open']
        vix = first_bar['VIX_close']
        
        # Calculate PRE-MARKET GAP
        gap = (market_open - prev_close) / prev_close
        
        # Determine leverage based on VIX
        if vix < VIX_LOW:
            leverage = 2.0
        elif vix < VIX_MID:
            leverage = 1.5
        else:
            leverage = 1.0
        
        # Initialize state
        state = {
            "position_open": False,
            "entry_price": 0.0,
            "entry_mode": None,
            "position_size": 0.0,
            "highest_price": 0.0,
            "lowest_price": 999999.0
        }
        
        # Determine signal based on gap
        if gap >= GAP_LONG:
            # GAP UP - Enter LONG at open
            state["position_open"] = True
            state["entry_price"] = market_open
            state["entry_mode"] = "LONG"
            state["position_size"] = day_start_capital * leverage
            state["highest_price"] = market_open
            signal = "LONG"
            
        elif gap <= GAP_SHORT:
            # GAP DOWN - Enter SHORT at open
            state["position_open"] = True
            state["entry_price"] = market_open
            state["entry_mode"] = "SHORT"
            state["position_size"] = day_start_capital * leverage
            state["lowest_price"] = market_open
            signal = "SHORT"
        else:
            # No signal - stay flat
            signal = "NONE"
        
        # Process each bar during the day
        for idx, bar in day_data.iterrows():
            bar_pnl = 0.0
            action = "HOLD" if state["position_open"] else "FLAT"
            
            if state["position_open"]:
                current_price = bar['close']
                
                # Update highest/lowest for trailing stops
                if state["entry_mode"] == "LONG":
                    state["highest_price"] = max(state["highest_price"], bar['high'])
                    
                    # Calculate current P&L
                    profit_pct = (current_price - state["entry_price"]) / state["entry_price"]
                    
                    # Check stop loss
                    if profit_pct <= STOP_LOSS:
                        bar_pnl = state["position_size"] * profit_pct
                        day_pnl += bar_pnl
                        state["position_open"] = False
                        action = "STOP_LOSS"
                    
                    # Check profit target
                    elif profit_pct >= PROFIT_TARGET:
                        bar_pnl = state["position_size"] * profit_pct
                        day_pnl += bar_pnl
                        state["position_open"] = False
                        action = "PROFIT_TARGET"
                
                else:  # SHORT
                    state["lowest_price"] = min(state["lowest_price"], bar['low'])
                    
                    # Calculate current P&L
                    profit_pct = (state["entry_price"] - current_price) / state["entry_price"]
                    
                    # Check stop loss
                    if profit_pct <= STOP_LOSS:
                        bar_pnl = state["position_size"] * profit_pct
                        day_pnl += bar_pnl
                        state["position_open"] = False
                        action = "STOP_LOSS"
                    
                    # Check profit target
                    elif profit_pct >= PROFIT_TARGET:
                        bar_pnl = state["position_size"] * profit_pct
                        day_pnl += bar_pnl
                        state["position_open"] = False
                        action = "PROFIT_TARGET"
            
            # Calculate unrealized P&L
            unrealized = 0.0
            if state["position_open"]:
                current_price = bar['close']
                if state["entry_mode"] == "LONG":
                    unrealized = state["position_size"] * (current_price - state["entry_price"]) / state["entry_price"]
                else:
                    unrealized = state["position_size"] * (state["entry_price"] - current_price) / state["entry_price"]
            
            bar_results.append({
                'timestamp': bar['date'],
                'day': day,
                'action': action,
                'signal': signal,
                'gap': gap,
                'mode': state['entry_mode'] if state['position_open'] else 'FLAT',
                'leverage': leverage if state['position_open'] else 0,
                'position_open': state['position_open'],
                'entry_price': state['entry_price'] if state['position_open'] else 0,
                'current_price': bar['close'],
                'bar_pnl': bar_pnl,
                'unrealized_pnl': unrealized,
                'day_pnl': day_pnl,
                'day_total': day_pnl + unrealized,
                'capital': day_start_capital + day_pnl,
                'vix': vix
            })
        
        # End of day - close any open position
        if state["position_open"]:
            last_bar = day_data.iloc[-1]
            final_price = last_bar['close']
            
            if state["entry_mode"] == "LONG":
                final_pnl = state["position_size"] * (final_price - state["entry_price"]) / state["entry_price"]
            else:
                final_pnl = state["position_size"] * (state["entry_price"] - final_price) / state["entry_price"]
            
            day_pnl += final_pnl
        
        # Update capital
        capital = day_start_capital + day_pnl
        
        daily_results.append({
            'date': day,
            'gap': gap,
            'signal': signal,
            'start_capital': day_start_capital,
            'day_pnl_dollars': day_pnl,
            'day_pnl_pct': day_pnl / day_start_capital,
            'end_capital': capital,
            'vix': vix
        })
    
    return pd.DataFrame(bar_results), pd.DataFrame(daily_results), capital


def analyze_backtest(bar_df, daily_df, final_capital, initial_capital=100000):
    """Analyze results"""
    
    print("\n" + "="*70)
    print("PRE-MARKET GAP STRATEGY RESULTS")
    print("="*70)
    
    print(f"\nInitial Capital: ${initial_capital:,.2f}")
    print(f"Final Capital: ${final_capital:,.2f}")
    total_return = (final_capital / initial_capital - 1) * 100
    print(f"Total Return: {total_return:+.2f}%")
    
    print(f"\nPeriod: {daily_df['date'].min()} to {daily_df['date'].max()}")
    print(f"Trading Days: {len(daily_df)}")
    
    print(f"\n{'='*70}")
    print("SIGNAL DISTRIBUTION")
    print(f"{'='*70}")
    signal_counts = daily_df['signal'].value_counts()
    for signal, count in signal_counts.items():
        pct = count / len(daily_df) * 100
        print(f"  {signal:5s}: {count:3d} days ({pct:5.1f}%)")
    
    print(f"\n{'='*70}")
    print("DAILY PERFORMANCE")
    print(f"{'='*70}")
    
    winning_days = daily_df[daily_df['day_pnl_pct'] > 0]
    losing_days = daily_df[daily_df['day_pnl_pct'] < 0]
    flat_days = daily_df[daily_df['day_pnl_pct'] == 0]
    
    print(f"Winning Days: {len(winning_days)} ({len(winning_days)/len(daily_df)*100:.1f}%)")
    print(f"Losing Days: {len(losing_days)} ({len(losing_days)/len(daily_df)*100:.1f}%)")
    print(f"Flat Days: {len(flat_days)} ({len(flat_days)/len(daily_df)*100:.1f}%)")
    
    if len(winning_days) > 0:
        print(f"\nAvg Win: {winning_days['day_pnl_pct'].mean()*100:+.3f}%")
    if len(losing_days) > 0:
        print(f"Avg Loss: {losing_days['day_pnl_pct'].mean()*100:+.3f}%")
    
    if len(winning_days) > 0 and len(losing_days) > 0:
        win_loss_ratio = abs(winning_days['day_pnl_pct'].mean() / losing_days['day_pnl_pct'].mean())
        print(f"Win/Loss Ratio: {win_loss_ratio:.2f}")
    
    print(f"\nAvg Daily Return: {daily_df['day_pnl_pct'].mean()*100:+.3f}%")
    print(f"Daily Std Dev: {daily_df['day_pnl_pct'].std()*100:.3f}%")
    print(f"Best Day: {daily_df['day_pnl_pct'].max()*100:+.2f}%")
    print(f"Worst Day: {daily_df['day_pnl_pct'].min()*100:+.2f}%")
    
    if daily_df['day_pnl_pct'].std() > 0:
        sharpe = (daily_df['day_pnl_pct'].mean() / daily_df['day_pnl_pct'].std()) * np.sqrt(252)
        print(f"\nSharpe Ratio: {sharpe:.2f}")
    
    # Drawdown
    daily_df['cumulative'] = (1 + daily_df['day_pnl_pct']).cumprod()
    daily_df['peak'] = daily_df['cumulative'].cummax()
    daily_df['drawdown'] = (daily_df['cumulative'] - daily_df['peak']) / daily_df['peak']
    max_dd = daily_df['drawdown'].min()
    print(f"Max Drawdown: {max_dd*100:.2f}%")
    
    # CAGR
    days = len(daily_df)
    years = days / 252
    if years > 0:
        cagr = (pow(final_capital / initial_capital, 1/years) - 1) * 100
        print(f"CAGR (annualized): {cagr:+.2f}%")
    
    # Performance by signal
    print(f"\n{'='*70}")
    print("PERFORMANCE BY SIGNAL")
    print(f"{'='*70}")
    
    for signal in ['LONG', 'SHORT', 'NONE']:
        signal_days = daily_df[daily_df['signal'] == signal]
        if len(signal_days) > 0:
            wins = len(signal_days[signal_days['day_pnl_pct'] > 0])
            total = len(signal_days)
            avg_ret = signal_days['day_pnl_pct'].mean() * 100
            print(f"\n{signal}:")
            print(f"  Days: {total}")
            print(f"  Win Rate: {wins/total*100:.1f}%")
            print(f"  Avg Return: {avg_ret:+.3f}%")
    
    # Gap distribution
    print(f"\n{'='*70}")
    print("GAP DISTRIBUTION")
    print(f"{'='*70}")
    print(f"Avg Gap: {daily_df['gap'].mean()*100:+.3f}%")
    print(f"Max Gap Up: {daily_df['gap'].max()*100:+.2f}%")
    print(f"Max Gap Down: {daily_df['gap'].min()*100:+.2f}%")
    
    print(f"\n{'='*70}")
    print("SAMPLE TRADES")
    print(f"{'='*70}")
    
    # Show first 10 trading days
    trade_days = daily_df[daily_df['signal'] != 'NONE'].head(10)
    if len(trade_days) > 0:
        print(trade_days[['date', 'signal', 'gap', 'day_pnl_pct', 'vix']].to_string(index=False))
    
    return daily_df


if __name__ == "__main__":
    print("="*70)
    print("PRE-MARKET GAP STRATEGY")
    print("="*70)
    print("\nStrategy:")
    print("• Calculate gap: (today_open - yesterday_close) / yesterday_close")
    print("• Enter LONG if gap > +0.2%, SHORT if gap < -0.2%")
    print("• Enter at market open (9:30 AM)")
    print("• Exit at profit target (+2%) or stop loss (-1.5%)")
    print("• Flatten at market close (3:55 PM)")
    print("• Leverage: 2x (VIX<15), 1.5x (VIX 15-20), 1x (VIX>20)")
    print("="*70)
    
    try:
        # Fetch intraday data
        print("\nFetching intraday data...")
        smh_intraday = fetch_yfinance_intraday("SMH", lookback_days=60)
        
        # Fetch daily data for previous close
        smh_daily = fetch_daily_close("SMH", lookback_days=60)
        
        # Fetch VIX
        vix_ticker = yf.Ticker("^VIX")
        vix_df = vix_ticker.history(period="60d", interval="1d")
        vix_df = vix_df.reset_index()
        vix_df['date'] = pd.to_datetime(vix_df['Date']).dt.date
        vix_df = vix_df[['date', 'Close']].rename(columns={'Close': 'VIX_close'})
        
        if smh_intraday is None or smh_daily is None:
            print("\n❌ Failed to fetch data")
            exit(1)
        
        # Run pre-market gap backtest
        print("\nRunning PRE-MARKET GAP backtest...")
        bar_results, daily_results, final_capital = run_premarket_gap_backtest(
            smh_intraday, smh_daily, vix_df, initial_capital=100000
        )
        
        # Analyze
        daily_results = analyze_backtest(bar_results, daily_results, final_capital)
        
        # Save
        bar_results.to_csv("backtest_premarket_gap_bars.csv", index=False)
        daily_results.to_csv("backtest_premarket_gap_daily.csv", index=False)
        
        print(f"\n{'='*70}")
        print("✓ Files saved: backtest_premarket_gap_*.csv")
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()