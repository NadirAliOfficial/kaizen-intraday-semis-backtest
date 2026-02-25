"""
IBKR PRODUCTION TRADING SYSTEM - FINAL
Exact specification per client requirements
Author: Nadir Ali
Version: 2.0 FINAL
Date: Feb 25, 2026
"""
import time
import logging
from datetime import datetime, time as dt_time
from ib_insync import IB, Stock, Order, util
import pandas as pd
import pytz

# ============================================================================
# CONFIGURATION - LOCKED SPECIFICATION
# ============================================================================
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 4002  # Gateway: 4001 = LIVE, 4002 = PAPER
CLIENT_ID = 1

SYMBOL = "SMH"
EXCHANGE = "ARCA"

# Strategy Parameters
EMA_FAST = 25
EMA_SLOW = 125
STOP_LOSS_PCT = 0.018  # 1.8% underlying
STOP_BUFFER = 0.001    # 0.1% buffer = 1.9% effective

# Leverage by VIX (Dynamic)
LEV_BASE = 3.0
LEV_VIX_14 = 3.25
LEV_VIX_13 = 3.5
LEV_VIX_12 = 3.75

# Rebalancing
REBALANCE_THRESHOLD = 50  # $50 notional difference

# Trading Times (ET)
ENTRY_TIME = dt_time(15, 55)
MARKET_CLOSE = dt_time(16, 0)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================================
# PRODUCTION TRADING SYSTEM
# ============================================================================
class ProductionTradingSystem:
    def __init__(self):
        self.ib = None
        self.smh = Stock(SYMBOL, EXCHANGE, "USD")
        self.vix = None  # Will be set if available
        
        self.position_qty = 0
        self.position_entry = 0
        self.stop_order_id = None
        self.stopped_today = False  # Track if stopped intraday
        
        self.connect()
    
    def connect(self):
        """Connect to IBKR with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.ib = IB()
                self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=20)
                self.ib.reqMarketDataType(1)  # Live data
                
                log.info(f"✅ Connected to IBKR (Port {IBKR_PORT})")
                
                # Initialize EMAs
                self.initialize_emas()
                
                # Detect existing position
                self.sync_position()
                
                return True
                
            except Exception as e:
                log.error(f"Connection attempt {attempt+1} failed: {e}")
                time.sleep(5)
        
        log.critical("❌ Failed to connect after 3 attempts")
        raise ConnectionError("Cannot connect to IBKR")
    
    def initialize_emas(self):
        """Load 250 bars and calculate EMAs"""
        log.info("Loading historical data (250 bars)...")
        
        bars = self.ib.reqHistoricalData(
            self.smh,
            endDateTime='',
            durationStr='250 D',
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True
        )
        
        if len(bars) < EMA_SLOW:
            log.error(f"Insufficient data: {len(bars)} bars (need {EMA_SLOW})")
            raise ValueError("Not enough historical data")
        
        df = util.df(bars)
        df['ema_25'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
        df['ema_125'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
        
        self.ema_25 = df['ema_25'].iloc[-1]
        self.ema_125 = df['ema_125'].iloc[-1]
        self.bull_signal = self.ema_25 > self.ema_125
        
        log.info(f"✅ EMAs: 25={self.ema_25:.2f} | 125={self.ema_125:.2f} | Signal={'BULL' if self.bull_signal else 'BEAR'}")
    
    def sync_position(self):
        """Detect existing IBKR position on startup"""
        positions = self.ib.positions()
        
        for pos in positions:
            if pos.contract.symbol == SYMBOL:
                self.position_qty = pos.position
                
                # Get avg cost from IBKR
                portfolio = self.ib.portfolio()
                for item in portfolio:
                    if item.contract.symbol == SYMBOL:
                        self.position_entry = item.averageCost
                        break
                
                log.info(f"📍 Existing position: {self.position_qty} shares @ ${self.position_entry:.2f}")
                return
        
        log.info("📍 No existing position")
    
    def get_account_value(self):
        """Get NetLiquidation"""
        try:
            account_values = self.ib.accountValues()
            for v in account_values:
                if v.tag == 'NetLiquidation' and v.currency == 'USD':
                    return float(v.value)
            return 0
        except Exception as e:
            log.error(f"Error getting account value: {e}")
            return 0
    
    def get_vix(self):
        """Get current VIX value"""
        try:
            if not self.vix:
                from ib_insync import Index
                self.vix = Index('VIX', 'CBOE')
            
            ticker = self.ib.reqMktData(self.vix)
            self.ib.sleep(2)
            
            vix_value = ticker.last if ticker.last == ticker.last else ticker.close
            return vix_value if vix_value > 0 else 15.0
            
        except Exception as e:
            log.warning(f"VIX unavailable, using base leverage: {e}")
            return 15.0  # Default to base leverage
    
    def get_leverage(self):
        """Calculate leverage based on VIX"""
        vix = self.get_vix()
        
        if vix < 12:
            lev = LEV_VIX_12
        elif vix < 13:
            lev = LEV_VIX_13
        elif vix < 14:
            lev = LEV_VIX_14
        else:
            lev = LEV_BASE
        
        log.info(f"   VIX: {vix:.2f} → Leverage: {lev}x")
        return lev
    
    def update_emas(self, price):
        """Update EMAs with new close price"""
        k_fast = 2 / (EMA_FAST + 1)
        k_slow = 2 / (EMA_SLOW + 1)
        
        self.ema_25 = price * k_fast + self.ema_25 * (1 - k_fast)
        self.ema_125 = price * k_slow + self.ema_125 * (1 - k_slow)
        
        prev_signal = self.bull_signal
        self.bull_signal = self.ema_25 > self.ema_125
        
        if prev_signal != self.bull_signal:
            log.info(f"📊 SIGNAL CHANGE: {'BULL' if self.bull_signal else 'BEAR'}")
    
    def place_moc_order(self, action, quantity):
        """Place Market-On-Close order"""
        try:
            order = Order()
            order.action = action
            order.totalQuantity = abs(quantity)
            order.orderType = "MOC"
            order.tif = "DAY"
            
            trade = self.ib.placeOrder(self.smh, order)
            self.ib.sleep(2)
            
            # Wait for fill
            max_wait = 30
            for _ in range(max_wait):
                if trade.orderStatus.status in ['Filled', 'Cancelled']:
                    break
                self.ib.sleep(1)
            
            if trade.orderStatus.status == 'Filled':
                fill_price = trade.orderStatus.avgFillPrice
                log.info(f"✅ {action} MOC filled: {quantity} @ ${fill_price:.2f}")
                return fill_price
            else:
                log.error(f"❌ MOC order failed: {trade.orderStatus.status}")
                return None
                
        except Exception as e:
            log.error(f"MOC order error: {e}")
            return None
    
    def place_stop_order(self, quantity, stop_price):
        """Place IBKR stop order (broker-level protection)"""
        try:
            order = Order()
            order.action = "SELL"
            order.totalQuantity = abs(quantity)
            order.orderType = "STP"
            order.auxPrice = stop_price
            order.tif = "GTC"
            
            trade = self.ib.placeOrder(self.smh, order)
            self.stop_order_id = trade.order.orderId
            
            log.info(f"🛡️  IBKR stop placed: {quantity} @ ${stop_price:.2f}")
            
        except Exception as e:
            log.error(f"Stop order error: {e}")
    
    def cancel_stop_order(self):
        """Cancel existing stop order"""
        if self.stop_order_id:
            try:
                self.ib.cancelOrder(self.stop_order_id)
                log.info("🛡️  Stop order cancelled")
                self.stop_order_id = None
            except Exception as e:
                log.error(f"Cancel stop error: {e}")
    
    def check_stop_triggered(self):
        """Check if IBKR stop was triggered"""
        if not self.stop_order_id:
            return False
        
        try:
            positions = self.ib.positions()
            has_position = any(p.contract.symbol == SYMBOL for p in positions)
            
            # If we had a stop order but no longer have position, stop was triggered
            if not has_position and self.position_qty > 0:
                log.warning("🛑 IBKR stop triggered - position closed")
                self.position_qty = 0
                self.position_entry = 0
                self.stop_order_id = None
                self.stopped_today = True
                return True
                
        except Exception as e:
            log.error(f"Stop check error: {e}")
        
        return False
    
    def enter_position(self):
        """Enter position with MOC order at 3:55 PM"""
        try:
            equity = self.get_account_value()
            leverage = self.get_leverage()
            
            # Get current price
            ticker = self.ib.reqMktData(self.smh)
            self.ib.sleep(2)
            price = ticker.last if ticker.last == ticker.last else ticker.close
            
            if not price or price <= 0:
                log.error("❌ Invalid price, skipping entry")
                return
            
            # Calculate position
            notional = equity * leverage
            qty = int(notional / price)
            
            if qty <= 0:
                log.error("❌ Invalid quantity")
                return
            
            log.info(f"📊 Entry: Equity=${equity:,.0f} Lev={leverage}x Price=${price:.2f} Qty={qty}")
            
            # Place MOC order
            fill_price = self.place_moc_order("BUY", qty)
            
            if fill_price:
                self.position_qty = qty
                self.position_entry = fill_price
                
                # Place IBKR stop (1.9% below entry)
                stop_price = fill_price * (1 - STOP_LOSS_PCT - STOP_BUFFER)
                self.place_stop_order(qty, stop_price)
                
                log.info(f"✅ POSITION OPENED: {qty} @ ${fill_price:.2f}")
            
        except Exception as e:
            log.error(f"Entry error: {e}")
    
    def exit_position(self, reason):
        """Exit position with MOC order"""
        if self.position_qty == 0:
            return
        
        try:
            log.info(f"🚪 Exit: {reason}")
            
            # Cancel stop order
            self.cancel_stop_order()
            
            # Place MOC sell
            fill_price = self.place_moc_order("SELL", self.position_qty)
            
            if fill_price:
                pnl = self.position_qty * (fill_price - self.position_entry)
                pnl_pct = (fill_price / self.position_entry - 1) * 100
                
                log.info(f"✅ CLOSED: {self.position_qty} @ ${fill_price:.2f} | P&L: ${pnl:,.0f} ({pnl_pct:+.2f}%)")
                
                self.position_qty = 0
                self.position_entry = 0
            
        except Exception as e:
            log.error(f"Exit error: {e}")
    
    def rebalance_position(self, close_price):
        """Rebalance position if notional difference > $50"""
        if self.position_qty == 0:
            return
        
        try:
            equity = self.get_account_value()
            leverage = self.get_leverage()
            target_notional = equity * leverage
            target_qty = int(target_notional / close_price)
            
            current_notional = self.position_qty * close_price
            notional_diff = abs(target_notional - current_notional)
            
            # Rebalance if difference > $50
            if notional_diff > REBALANCE_THRESHOLD:
                qty_diff = target_qty - self.position_qty
                
                if qty_diff > 0:
                    log.info(f"📊 Rebalancing UP: +{qty_diff} shares (${notional_diff:,.0f})")
                    self.place_moc_order("BUY", qty_diff)
                elif qty_diff < 0:
                    log.info(f"📊 Rebalancing DOWN: {qty_diff} shares (${notional_diff:,.0f})")
                    self.place_moc_order("SELL", abs(qty_diff))
                
                self.position_qty = target_qty
                
                # Update stop to new reference
                self.cancel_stop_order()
                stop_price = close_price * (1 - STOP_LOSS_PCT - STOP_BUFFER)
                self.place_stop_order(self.position_qty, stop_price)
            else:
                log.info(f"✅ No rebalancing (${notional_diff:.0f} diff)")
                
        except Exception as e:
            log.error(f"Rebalancing error: {e}")
    
    def daily_cycle(self):
        """Main trading logic"""
        try:
            now = datetime.now(pytz.timezone('US/Eastern')).time()
            
            # Morning: Reset stopped flag
            if now < dt_time(9, 35):
                self.stopped_today = False
            
            # Continuous: Check if IBKR stop triggered
            if self.position_qty > 0:
                self.check_stop_triggered()
            
            # 3:55 PM: Entry (or re-entry if stopped intraday)
            if now >= ENTRY_TIME and now < dt_time(15, 58):
                # Enter if: no position AND bull signal
                # This handles both fresh entries AND re-entries after intraday stop
                if self.position_qty == 0 and self.bull_signal:
                    if self.stopped_today:
                        log.info("🔄 Re-entering after intraday stop")
                    self.enter_position()
            
            # 4:00 PM: Update EMAs, check bear exit, rebalance
            if now >= MARKET_CLOSE and now < dt_time(16, 5):
                ticker = self.ib.reqMktData(self.smh)
                self.ib.sleep(2)
                close = ticker.close
                
                if close and close > 0:
                    self.update_emas(close)
                    
                    # Bear exit (EMA 25 < EMA 125)
                    if self.position_qty > 0 and not self.bull_signal:
                        self.exit_position("BEAR_SIGNAL")
                    
                    # Rebalance if still in bull
                    elif self.position_qty > 0 and self.bull_signal:
                        self.rebalance_position(close)
            
        except Exception as e:
            log.error(f"Daily cycle error: {e}")
    
    def run(self):
        """Main event loop with reconnection"""
        log.info("🚀 PRODUCTION SYSTEM STARTED")
        log.info(f"   Strategy: EMA {EMA_FAST}/{EMA_SLOW}")
        log.info(f"   Stop: {STOP_LOSS_PCT*100}% + {STOP_BUFFER*100}% = {(STOP_LOSS_PCT+STOP_BUFFER)*100}% effective")
        log.info(f"   Port: {IBKR_PORT} ({'LIVE' if IBKR_PORT == 7497 else 'PAPER'})")
        
        try:
            while True:
                # Check connection
                if not self.ib.isConnected():
                    log.warning("⚠️  Disconnected, reconnecting...")
                    self.connect()
                
                self.daily_cycle()
                time.sleep(10)  # Check every 10 seconds
                
        except KeyboardInterrupt:
            log.info("⏹️  Manual shutdown")
            self.ib.disconnect()
        except Exception as e:
            log.critical(f"Fatal error: {e}")
            self.ib.disconnect()

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    log.info("=" * 80)
    log.info("IBKR PRODUCTION TRADING SYSTEM - FINAL VERSION")
    log.info("Specification: SMH | EMA 25/125 | Dynamic VIX Leverage | 1.9% Stop")
    log.info("=" * 80)
    
    system = ProductionTradingSystem()
    system.run()