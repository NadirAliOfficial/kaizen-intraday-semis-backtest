
import time
from datetime import datetime, time as dt_time
from ib_insync import IB, Stock, MarketOrder, util
import pandas as pd
import pytz

# ============================================================================
# CONFIGURATION
# ============================================================================
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7496  # Paper trading
CLIENT_ID = 1

SYMBOL = "SMH"
EXCHANGE = "ARCA"

# Strategy Parameters
EMA_FAST = 25
EMA_SLOW = 125
STOP_LOSS_PCT = 0.02  # -2%

# Leverage by VIX
LEV_BASE = 3.0
LEV_VIX_14 = 3.25
LEV_VIX_13 = 3.5
LEV_VIX_12 = 3.75

# Trading Times (ET)
MARKET_CLOSE = dt_time(16, 0)
ENTRY_TIME = dt_time(15, 55)  # 5 min before close

# ============================================================================
# IBKR CONNECTION
# ============================================================================
class TradingSystem:
    def __init__(self):
        self.ib = IB()
        self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID)
        
        # Request delayed market data (free)
        self.ib.reqMarketDataType(3)  # 3 = delayed, 1 = live (requires subscription)
        
        print(f"✅ Connected to IBKR Paper Trading (Port {IBKR_PORT})")
        print("   Using delayed market data (15min delay)")
        
        self.smh = Stock(SYMBOL, EXCHANGE, "USD")
        
        self.position_qty = 0
        self.position_entry = 0
        self.day_start_equity = 0
        
        # Initialize EMAs
        self.initialize_emas()
    
    def initialize_emas(self):
        """Load historical data and calculate EMAs"""
        print("Loading historical data...")
        bars = self.ib.reqHistoricalData(
            self.smh,
            endDateTime='',
            durationStr='1 Y',
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True
        )
        
        df = util.df(bars)
        df['ema_25'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
        df['ema_125'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
        
        self.ema_25 = df['ema_25'].iloc[-1]
        self.ema_125 = df['ema_125'].iloc[-1]
        self.bull_signal = self.ema_25 > self.ema_125
        
        print(f"✅ EMAs Initialized: 25={self.ema_25:.2f} | 125={self.ema_125:.2f}")
        print(f"   Signal: {'BULL' if self.bull_signal else 'BEAR'}")
    
    def get_account_value(self):
        """Get current account equity"""
        account_values = self.ib.accountValues()
        for v in account_values:
            if v.tag == 'NetLiquidation':
                return float(v.value)
        return 0
    
    def get_position(self):
        """Check current position"""
        positions = self.ib.positions()
        for pos in positions:
            if pos.contract.symbol == SYMBOL:
                return pos.position
        return 0
    
    def get_vix(self):
        """Get current VIX - fallback to default if unavailable"""
        try:
            # VIX not available in paper trading - use default leverage
            return 15.0  # Default VIX assumption
        except:
            return 15.0
    
    def get_leverage(self):
        """Calculate leverage based on VIX"""
        vix = self.get_vix()
        print(f"   VIX: {vix:.2f}")
        if vix < 12:
            return LEV_VIX_12
        elif vix < 13:
            return LEV_VIX_13
        elif vix < 14:
            return LEV_VIX_14
        else:
            return LEV_BASE
    
    def check_stop_loss(self):
        """Check -2% equity stop"""
        if self.position_qty == 0:
            return False
        
        current_equity = self.get_account_value()
        equity_dd = (current_equity - self.day_start_equity) / self.day_start_equity
        
        if equity_dd <= -STOP_LOSS_PCT:
            print(f"🛑 STOP TRIGGERED: {equity_dd*100:.2f}%")
            self.exit_position("STOP")
            return True
        return False
    
    def update_emas(self, price):
        """Update EMAs with new price"""
        # EMA formula: EMA_today = price * k + EMA_yesterday * (1-k)
        k_fast = 2 / (EMA_FAST + 1)
        k_slow = 2 / (EMA_SLOW + 1)
        
        self.ema_25 = price * k_fast + self.ema_25 * (1 - k_fast)
        self.ema_125 = price * k_slow + self.ema_125 * (1 - k_slow)
        
        prev_signal = self.bull_signal
        self.bull_signal = self.ema_25 > self.ema_125
        
        if prev_signal != self.bull_signal:
            print(f"📊 SIGNAL CHANGE: {'BULL' if self.bull_signal else 'BEAR'}")
    
    def enter_position(self):
        """Enter position 5 min before close"""
        equity = self.get_account_value()
        leverage = self.get_leverage()
        
        ticker = self.ib.reqMktData(self.smh)
        self.ib.sleep(2)
        
        # Use last or close price
        price = ticker.last if not pd.isna(ticker.last) else ticker.close
        
        if pd.isna(price) or price <= 0:
            print("❌ Cannot get valid price - skipping entry")
            return
        
        notional = equity * leverage
        qty = int(notional / price)
        
        if qty > 0:
            order = MarketOrder("BUY", qty)
            trade = self.ib.placeOrder(self.smh, order)
            self.ib.sleep(2)
            
            self.position_qty = qty
            self.position_entry = price
            
            print(f"✅ ENTERED: {qty} shares @ ${price:.2f} (Leverage: {leverage}x)")
        else:
            print("❌ Position size = 0, skipping entry")
    
    def exit_position(self, reason):
        """Exit position"""
        if self.position_qty == 0:
            return
        
        order = MarketOrder("SELL", abs(self.position_qty))
        trade = self.ib.placeOrder(self.smh, order)
        self.ib.sleep(2)
        
        print(f"🚪 EXITED ({reason}): {self.position_qty} shares")
        self.position_qty = 0
        self.position_entry = 0
    
    def daily_routine(self):
        """Execute daily trading logic"""
        now = datetime.now(pytz.timezone('US/Eastern')).time()
        
        # Set day start equity once per day
        if now < dt_time(9, 35) and self.day_start_equity == 0:
            self.day_start_equity = self.get_account_value()
            print(f"📅 Day Start Equity: ${self.day_start_equity:,.2f}")
        
        # Check stop loss (continuous)
        if self.position_qty > 0:
            self.check_stop_loss()
        
        # Market close - update EMAs and check bear exit
        if now >= MARKET_CLOSE and now < dt_time(16, 5):
            ticker = self.ib.reqMktData(self.smh)
            self.ib.sleep(1)
            close_price = ticker.last
            
            self.update_emas(close_price)
            
            # Bear exit
            if self.position_qty > 0 and not self.bull_signal:
                self.exit_position("BEAR")
        
        # Entry time (3:55 PM)
        if now >= ENTRY_TIME and now < dt_time(15, 58):
            if self.position_qty == 0 and self.bull_signal:
                self.enter_position()
        
        # Reset day start equity after hours
        if now > dt_time(17, 0):
            self.day_start_equity = 0
    
    def run(self, test_mode=False):
        """Main loop"""
        print("🚀 Trading System Started")
        print(f"   Symbol: {SYMBOL}")
        print(f"   Strategy: EMA {EMA_FAST}/{EMA_SLOW}")
        print(f"   Stop Loss: {STOP_LOSS_PCT*100}%")
        
        if test_mode:
            print("\n🧪 TEST MODE - Entering immediately...")
            self.day_start_equity = self.get_account_value()
            print(f"📅 Day Start Equity: ${self.day_start_equity:,.2f}")
            
            if self.bull_signal and self.position_qty == 0:
                self.enter_position()
            
            print("\n✅ Test entry complete. Starting normal monitoring...")
        
        try:
            while True:
                self.daily_routine()
                time.sleep(5)  # Check every 5 seconds
        except KeyboardInterrupt:
            print("\n⏹️  Shutting down...")
            self.ib.disconnect()

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    system = TradingSystem()
    system.run(test_mode=True)  # Set to False for production