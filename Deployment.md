# IBKR PRODUCTION DEPLOYMENT

## Prerequisites

1. **Install ib_insync:**
```bash
pip install ib_insync pandas pytz --break-system-packages
```

2. **IBKR TWS Setup:**
   - Open TWS (Paper Trading)
   - Go to: Edit → Global Configuration → API → Settings
   - Enable: "Enable ActiveX and Socket Clients"
   - Port: 7496
   - Trusted IPs: 127.0.0.1
   - Click OK and restart TWS

## Deployment

1. **Start TWS Paper Trading** and login

2. **Run the script:**
```bash
python ibkr_production.py
```

## How It Works

**Daily Cycle:**
- **9:30 AM:** Records day start equity
- **Continuous:** Monitors -2% stop loss
- **3:55 PM:** Enters position if BULL signal
- **4:00 PM:** Updates EMAs, checks bear exit

**On Deposit:**
When you add money, system recalculates at 4:00 PM:
- Updates EMAs with today's close
- Checks signal (BULL/BEAR)
- If BULL → enters at 3:55 PM next day
- Position sized on new equity

**Stop Loss:**
- Monitors real-time equity
- Exits if daily loss ≥ 2%
- Re-enters at 3:55 PM if BULL signal remains

## Monitoring

Watch console output:
```
✅ Connected to IBKR Paper Trading
✅ EMAs Initialized: 25=285.32 | 125=265.18
   Signal: BULL
📅 Day Start Equity: $100,000.00
✅ ENTERED: 1069 shares @ $281.50 (Leverage: 3.0x)
```

## Safety

- Runs in paper trading (Port 7496)
- Auto-reconnects on disconnect
- Logs all trades
- -2% hard stop enforced

## Going Live

**When ready for real money:**
1. Change PORT to 7497
2. Test with small amount first
3. Monitor for 1 week before full capital

Ready to deploy!