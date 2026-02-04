from ib_insync import *
import pandas as pd
import numpy as np
import pytz
from datetime import datetime
import time

# ================== CONFIG ==================
BAR_SIZE = "5 mins"
USE_RTH = True
TIMEZONE = pytz.timezone("America/New_York")

ENTRY_1 = 0.0012
ENTRY_2 = 0.0020
ENTRY_3 = 0.0030
INVALID_ZERO = 0.0
HARD_EXIT = 0.002
DAILY_KILL = -0.025

# ============================================

def fetch_ibkr(symbol, start, end, is_vix=False):
    ib = IB()
    
    try:
        print(f"Connecting to IBKR for {symbol}...")
        ib.connect("127.0.0.1", 7497, clientId=11)
        print("Connected successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Make sure TWS or IB Gateway is running on port 7497")
        return None
    
    try:
        if is_vix:
            contract = Index("VIX", "CBOE", "USD")
        else:
            contract = Stock(symbol, "SMART", "USD")
        
        print(f"Qualifying contract for {symbol}...")
        ib.qualifyContracts(contract)
        print(f"Qualified: {contract}")
        
        # Request with proper timeout handling
        print(f"Requesting historical data for {symbol}...")
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="20241231 16:00:00 US/Eastern",
            durationStr="1 Y",
            barSizeSetting=BAR_SIZE,
            whatToShow="TRADES",
            useRTH=USE_RTH,
            formatDate=1,
            timeout=60  # 60 second timeout
        )
        
        if not bars:
            print(f"No data returned for {symbol}")
            return None
        
        print(f"Retrieved {len(bars)} bars for {symbol}")
        
        df = util.df(bars)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.tz_localize(TIMEZONE)
        
        return df[["date", "open", "close"]]
        
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None
    finally:
        ib.disconnect()
        print(f"Disconnected from IBKR")
        time.sleep(1)  # Small delay between requests


def compute_intraday_ret(df):
    df = df.copy()
    df["day"] = df["date"].dt.date
    df["day_open"] = df.groupby("day")["open"].transform("first")
    df["RET"] = (df["close"] - df["day_open"]) / df["day_open"]
    return df


def run_backtest(data):
    state = {
        "mode": "NEUTRAL",
        "pf": 0.0,
        "trading": True,
        "daily_pnl": 0.0,
        "current_day": None
    }
    
    rows = []
    
    for _, r in data.iterrows():
        day = r["date"].date()
        
        # Daily reset
        if state["current_day"] != day:
            state["current_day"] = day
            state["daily_pnl"] = 0.0
            state["trading"] = True
            state["pf"] = 0.0
            state["mode"] = "NEUTRAL"
        
        SMH_RET = r["SMH_RET"]
        SOXX_RET = r["SOXX_RET"]
        QQQ_RET = r["QQQ_RET"]
        VIX = r["VIX_close"]
        
        # Kill switch
        if state["daily_pnl"] <= DAILY_KILL:
            state["trading"] = False
            state["pf"] = 0.0
        
        # Detect mode
        if state["trading"]:
            if SMH_RET > 0 and SOXX_RET > 0:
                state["mode"] = "LONG"
            elif SMH_RET < 0 and SOXX_RET < 0:
                state["mode"] = "SHORT"
            else:
                state["mode"] = "NEUTRAL"
            
            if state["mode"] == "NEUTRAL":
                state["pf"] = 0.0
        
        asset_ret = (
            max(SMH_RET, SOXX_RET) if state["mode"] == "LONG"
            else min(SMH_RET, SOXX_RET) if state["mode"] == "SHORT"
            else 0.0
        )
        
        pf = state["pf"]
        
        # Progressive entry
        if state["mode"] == "LONG":
            if asset_ret >= ENTRY_3:
                pf = 1.0
            elif asset_ret >= ENTRY_2:
                pf = max(pf, 0.7)
            elif asset_ret >= ENTRY_1:
                pf = max(pf, 0.5)
        
        if state["mode"] == "SHORT":
            if asset_ret <= -ENTRY_3:
                pf = 1.0
            elif asset_ret <= -ENTRY_2:
                pf = max(pf, 0.7)
            elif asset_ret <= -ENTRY_1:
                pf = max(pf, 0.5)
        
        # Invalidation / hard exit
        if state["mode"] == "LONG" and asset_ret <= INVALID_ZERO:
            pf *= 0.5
        if state["mode"] == "SHORT" and asset_ret >= INVALID_ZERO:
            pf *= 0.5
        
        if state["mode"] == "LONG" and asset_ret <= -HARD_EXIT:
            pf = 0.0
        if state["mode"] == "SHORT" and asset_ret >= HARD_EXIT:
            pf = 0.0
        
        # Leverage based on VIX
        leverage = 0.0
        if state["mode"] == "LONG":
            if VIX < 12:
                base = 4.0
            elif VIX < 15:
                base = 3.0
            else:
                base = 2.0
            leverage = base * pf
        
        if state["mode"] == "SHORT":
            if VIX < 20:
                base = 2.0
            elif VIX < 25:
                base = 4.0
            else:
                base = 5.0
            leverage = base * pf
        
        state["pf"] = pf
        
        rows.append({
            "timestamp": r["date"],
            "mode": state["mode"],
            "position_fraction": pf,
            "leverage": leverage,
            "asset_ret": asset_ret,
            "vix": VIX
        })
    
    return pd.DataFrame(rows)


# ================== RUN ==================

def load_symbol(symbol, start, end, is_vix=False):
    df = fetch_ibkr(symbol, start, end, is_vix=is_vix)
    if df is None or df.empty:
        raise RuntimeError(f"IBKR returned no data for {symbol}")
    
    if is_vix:
        return df[["date", "close"]]
    else:
        return compute_intraday_ret(df)


if __name__ == "__main__":
    start = "2024-01-01 09:30:00"
    end = "2024-12-31 16:00:00"
    
    print("="*60)
    print("IBKR Historical Data Backtest")
    print("="*60)
    print("\nMake sure TWS or IB Gateway is:")
    print("  1. Running and logged in")
    print("  2. Listening on port 7497")
    print("  3. Has API connections enabled")
    print("  4. Has active market data subscriptions for US stocks")
    print("="*60)
    print()
    
    try:
        print("Loading SMH...")
        smh = load_symbol("SMH", start, end)
        print(f"✓ SMH loaded: {len(smh)} rows\n")
        
        print("Loading SOXX...")
        soxx = load_symbol("SOXX", start, end)
        print(f"✓ SOXX loaded: {len(soxx)} rows\n")
        
        print("Loading QQQ...")
        qqq = load_symbol("QQQ", start, end)
        print(f"✓ QQQ loaded: {len(qqq)} rows\n")
        
        print("Loading VIX...")
        vix = load_symbol("VIX", start, end, is_vix=True)
        print(f"✓ VIX loaded: {len(vix)} rows\n")
        
        print("Merging data...")
        data = smh.merge(soxx, on="date", suffixes=("_SMH", "_SOXX"))
        data = data.merge(qqq, on="date")
        data = data.merge(vix, on="date", suffixes=("_QQQ", "_VIX"))
        
        data = data.rename(columns={
            "RET_SMH": "SMH_RET",
            "RET_SOXX": "SOXX_RET",
            "RET": "QQQ_RET",
            "close": "VIX_close"
        })
        
        print(f"✓ Merged dataset: {len(data)} rows\n")
        
        print("Running backtest...")
        results = run_backtest(data)
        
        print("\n" + "="*60)
        print("BACKTEST RESULTS")
        print("="*60)
        print("\n=== First 10 rows ===")
        print(results.head(10))
        print("\n=== Last 10 rows ===")
        print(results.tail(10))
        
        print(f"\n=== Summary ===")
        print(f"Total rows: {len(results)}")
        print(f"\nMode distribution:")
        print(results['mode'].value_counts())
        print(f"\nAverage leverage when positioned: {results[results['leverage'] > 0]['leverage'].mean():.2f}")
        print(f"Max leverage: {results['leverage'].max():.2f}")
        print(f"\nPosition fraction distribution:")
        print(results['position_fraction'].value_counts().sort_index())
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting steps:")
        print("1. Check TWS/IB Gateway is running")
        print("2. Verify port 7497 is correct (check API settings)")
        print("3. Enable 'Socket Clients' in API settings")
        print("4. Confirm market data subscriptions are active")
        print("5. Try a different clientId if there are conflicts")