# IBKR Production Trading System
**EMA 25/125 Strategy with Dynamic Leverage**

---

## 📋 Overview

Automated trading system for SMH (semiconductor ETF) using EMA crossover strategy with:
- **Signal:** EMA 25 > EMA 125 = BULL (enter long)
- **Leverage:** 3.0x - 3.75x based on VIX
- **Stop Loss:** -2% daily equity
- **Entry:** 5 minutes before market close (3:55 PM ET)
- **Exit:** Bear signal or stop loss

---

## ⚙️ Setup

### 1. Install Dependencies
```bash
pip install ib_insync pandas pytz
```

### 2. Configure IBKR TWS
1. Open **TWS Paper Trading**
2. Go to: **Edit → Global Configuration → API → Settings**
3. Enable: **"Enable ActiveX and Socket Clients"**
4. Set Port: **7496** (paper) or **7497** (live)
5. Add Trusted IP: **127.0.0.1**
6. Click **OK** and restart TWS

### 3. Login to TWS
- Start TWS and login with paper trading credentials

---

## 🚀 Running the System

### Test Mode (Immediate Entry)
```bash
python ibkr_production.py
```
- Enters position immediately
- Good for testing

### Production Mode (3:55 PM Entry)
Edit line 241:
```python
system.run(test_mode=False)  # Change True to False
```

---

## 📊 How It Works

### Daily Cycle

| Time | Action |
|------|--------|
| **9:30 AM** | Records day start equity |
| **Continuous** | Monitors -2% stop loss |
| **3:55 PM** | Enters if BULL signal + no position |
| **4:00 PM** | Updates EMAs, checks bear exit |

### When You Add Money

1. System recalculates at **4:00 PM** (market close)
2. Updates EMAs with today's close price
3. Checks signal: BULL or BEAR
4. If **BULL** → enters position at **3:55 PM next day**
5. Position sized on **new total equity**

### Stop Loss

- Monitors equity every 5 seconds
- If daily loss ≥ **-2%** → exits immediately
- Can **re-enter same day** at 3:55 PM if BULL signal remains

### Leverage Scaling

| VIX Level | Leverage |
|-----------|----------|
| VIX < 12 | 3.75x |
| VIX < 13 | 3.5x |
| VIX < 14 | 3.25x |
| VIX ≥ 14 | 3.0x |

*Note: Paper trading uses default 3.0x (VIX not available)*

---

## 📈 Console Output

```
✅ Connected to IBKR Paper Trading (Port 7496)
✅ EMAs Initialized: 25=399.87 | 125=356.11
   Signal: BULL
📅 Day Start Equity: $1,001,295.25
✅ ENTERED: 7355 shares @ $408.39 (Leverage: 3.0x)
```

### Status Messages

| Symbol | Meaning |
|--------|---------|
| ✅ | Success |
| 🛑 | Stop loss triggered |
| 🚪 | Position exited |
| 📊 | Signal changed |
| ⏹️ | System shutdown |

---

## 🔧 Configuration

Edit these variables in `ibkr_production.py`:

```python
# Connection
IBKR_PORT = 7496  # 7496 = paper, 7497 = live

# Strategy
EMA_FAST = 25
EMA_SLOW = 125
STOP_LOSS_PCT = 0.02  # 2%

# Leverage
LEV_BASE = 3.0
LEV_VIX_14 = 3.25
LEV_VIX_13 = 3.5
LEV_VIX_12 = 3.75

# Timing
ENTRY_TIME = dt_time(15, 55)  # 3:55 PM ET
```

---

## 🛡️ Safety Features

1. **-2% Hard Stop** - Cannot lose >2% per day (except gaps)
2. **Bear Exit** - Exits when EMA turns bearish
3. **Auto-reconnect** - Handles disconnections
4. **Position verification** - Checks actual IBKR position
5. **Paper trading default** - Safe testing environment

---

## 🔄 Position Management

### Entry Conditions
- ✅ No current position
- ✅ EMA 25 > EMA 125 (BULL)
- ✅ Time = 3:55 PM ET
- ✅ Valid price available

### Exit Conditions
- ❌ Daily loss ≥ -2% (stop loss)
- ❌ EMA 25 < EMA 125 (bear signal)

### Re-entry
- Can re-enter **same day** at 3:55 PM if:
  - Stop triggered earlier
  - BULL signal still valid

---

## 📝 Logs & Monitoring

### Real-time Monitoring
Watch the console for:
- Entry/exit confirmations
- Stop loss triggers
- Signal changes
- Errors

### Position Check
```python
# In TWS: Portfolio → Positions
# Should show: SMH shares = script output
```

---

## 🚨 Troubleshooting

### "No security definition found"
- **Fix:** Check symbol and exchange (SMH on ARCA)

### "Market data requires subscription"
- **Fix:** System uses delayed data (automatic)
- 15-minute delay is acceptable for end-of-day strategy

### "Cannot convert NaN to integer"
- **Fix:** Updated script handles this automatically
- Waits for valid price before entering

### Position not entering
- Check time (must be 3:55 PM ET in production mode)
- Check signal (EMA 25 must be > EMA 125)
- Check TWS is connected and logged in

---

## 📊 Expected Performance

Based on backtest (July 2022 - Jan 2026):
- **CAGR:** 99.30%
- **Max DD:** 20.84%
- **Sharpe:** 1.64
- **Trades/Year:** 2.8
- **Win Rate:** 40%

---

## 🎯 Going Live (Real Money)

### Checklist

1. ✅ Test in paper trading for 1 week
2. ✅ Verify all entries/exits working
3. ✅ Confirm stop loss triggers correctly
4. ✅ Check position sizing is correct

### Switch to Live

1. Change port to **7497**
```python
IBKR_PORT = 7497
```

2. Login to **TWS Live** (not paper)

3. **Start with small capital** (test $10k first)

4. Monitor daily for first week

5. Gradually increase to full capital

---

## ⚠️ Risk Warnings

1. **Gap Risk:** Overnight gaps can exceed -2% stop
2. **Leverage:** 3x amplifies gains AND losses
3. **Bear Markets:** Strategy exits during downtrends (misses upside)
4. **Slippage:** Real executions may differ from backtest
5. **Technical:** System failures, disconnections possible

---

## 🛑 Emergency Shutdown

**To stop the system:**
1. Press `Ctrl+C` in terminal
2. System exits gracefully
3. **Does NOT close position** (manual close in TWS if needed)

**Manual position close:**
1. Open TWS
2. Go to Portfolio → Positions
3. Right-click SMH → Close Position

---

## 📞 Support

**Issues?**
- Check TWS connection
- Verify API settings
- Check console for error messages
- Ensure market hours (9:30 AM - 4:00 PM ET)

---

## 📄 Files

- `ibkr_production.py` - Main trading script
- `DEPLOYMENT_GUIDE.md` - Setup instructions
- `README.md` - This file

---

**Strategy validated. System ready. Trade safe.** 🎯