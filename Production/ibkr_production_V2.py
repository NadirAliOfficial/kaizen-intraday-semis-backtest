"""
IBKR PRODUCTION SYSTEM - FINAL
Exact logic matching clean backtest
Author: Nadir Ali
Version: 2.0 FINAL
"""
import time
import logging
from datetime import datetime, time as dt_time
from ib_insync import IB, Stock, Order, util, Index
import pandas as pd
import pytz

# ============================================================================
# CONFIGURATION
# ============================================================================
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 4002  # 4002 = PAPER, 4001 = LIVE (Gateway)
CLIENT_ID = 1

SYMBOL = "SMH"
EXCHANGE = "ARCA"

# Strategy Parameters
EMA_FAST = 25
EMA_SLOW = 125
STOP_PCT = 0.019  # 1.9% stop on underlying

# Leverage by VIX
LEV_BASE = 3.0
LEV_VIX_14 = 3.25
LEV_VIX_13 = 3.5
LEV_VIX_12 = 3.75

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
# PRODUCTION SYSTEM
# ============================================================================
class ProductionSystem:
    def __init__(self):
        self.ib = None
        self.smh = Stock(SYMBOL, EXCHANGE, "USD")
        self.vix = Index('VIX', 'CBOE')
        
        self.position_qty = 0
        self.position_entry = 0
        self.stop_order_id = None
        self.stopped_today = False
        
        self.connect()
    
    def connect(self):
        """Connect to IBKR"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.ib = IB()
                self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=20)
                self.ib.reqMarketDataType(1)
                
                log.info(f"✅ Connected (Port {IBKR_PORT})")
                
                self.initialize_emas()
                self.sync_position()
                
                return True
                
            except Exception as e:
                log.error(f"Connect failed: {e}")
                time.sleep(5)
        
        raise ConnectionError("Cannot connect")
    
    def initialize_emas(self):
        """Load 250 bars"""
        log.info("Loading 250 bars...")
        
        bars = self.ib.reqHistoricalData(
            self.smh,
            endDateTime='',
            durationStr='250 D',
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
        
        log.info(f"✅ EMAs: {self.ema_25:.2f} / {self.ema_125:.2f} | {'BULL' if self.bull_signal else 'BEAR'}")
    
    def sync_position(self):
        """Detect existing position and synchronize stops"""
        positions = self.ib.positions()
        has_position = False
        
        for pos in positions:
            if pos.contract.symbol == SYMBOL:
                self.position_qty = pos.position
                has_position = True
                
                portfolio = self.ib.portfolio()
                for item in portfolio:
                    if item.contract.symbol == SYMBOL:
                        self.position_entry = item.averageCost
                        break
                
                log.info(f"📍 Position: {self.position_qty} @ ${self.position_entry:.2f}")
                break
        
        # Synchronize stops with IBKR
        self.sync_stops(has_position)
        
        if not has_position:
            log.info("📍 No position")
    
    def sync_stops(self, has_position):
        """Synchronize stop orders with IBKR state"""
        try:
            # Get all open orders
            open_orders = self.ib.openOrders()
            smh_stops = [o for o in open_orders 
                        if o.contract.symbol == SYMBOL 
                        and o.order.orderType == 'STP']
            
            if has_position and len(smh_stops) == 0:
                # Position exists but no stop - CREATE
                log.warning("⚠️  Position without stop - creating")
                stop_price = self.position_entry * (1 - STOP_PCT)
                self.place_stop(self.position_qty, stop_price)
                
            elif has_position and len(smh_stops) > 0:
                # Position exists with stop - VERIFY
                stop = smh_stops[0]
                self.stop_order_id = stop.order.orderId
                log.info(f"✅ Stop verified: {stop.order.auxPrice:.2f}")
                
                # Cancel extra stops
                for extra in smh_stops[1:]:
                    self.ib.cancelOrder(extra.order.orderId)
                    log.warning(f"⚠️  Cancelled duplicate stop")
                    
            elif not has_position and len(smh_stops) > 0:
                # No position but stops exist - CANCEL orphans
                for stop in smh_stops:
                    self.ib.cancelOrder(stop.order.orderId)
                    log.warning(f"⚠️  Cancelled orphan stop")
                    
        except Exception as e:
            log.error(f"Stop sync error: {e}")
    
    def get_account_value(self):
        """Get NetLiquidation"""
        try:
            for v in self.ib.accountValues():
                if v.tag == 'NetLiquidation' and v.currency == 'USD':
                    return float(v.value)
        except:
            pass
        return 0
    
    def get_vix(self):
        """Get VIX"""
        try:
            ticker = self.ib.reqMktData(self.vix)
            self.ib.sleep(2)
            vix = ticker.last if ticker.last == ticker.last else ticker.close
            return vix if vix > 0 else 15.0
        except:
            return 15.0
    
    def get_leverage(self):
        """VIX-based leverage"""
        vix = self.get_vix()
        
        if vix < 12:
            lev = LEV_VIX_12
        elif vix < 13:
            lev = LEV_VIX_13
        elif vix < 14:
            lev = LEV_VIX_14
        else:
            lev = LEV_BASE
        
        log.info(f"   VIX: {vix:.2f} → {lev}x")
        return lev
    
    def update_emas(self, price):
        """Update EMAs"""
        k_fast = 2 / (EMA_FAST + 1)
        k_slow = 2 / (EMA_SLOW + 1)
        
        self.ema_25 = price * k_fast + self.ema_25 * (1 - k_fast)
        self.ema_125 = price * k_slow + self.ema_125 * (1 - k_slow)
        
        prev = self.bull_signal
        self.bull_signal = self.ema_25 > self.ema_125
        
        if prev != self.bull_signal:
            log.info(f"📊 SIGNAL: {'BULL' if self.bull_signal else 'BEAR'}")
    
    def place_moc(self, action, qty):
        """Market-On-Close order"""
        try:
            order = Order()
            order.action = action
            order.totalQuantity = abs(qty)
            order.orderType = "MOC"
            order.tif = "DAY"
            
            trade = self.ib.placeOrder(self.smh, order)
            self.ib.sleep(2)
            
            for _ in range(30):
                if trade.orderStatus.status in ['Filled', 'Cancelled']:
                    break
                self.ib.sleep(1)
            
            if trade.orderStatus.status == 'Filled':
                fill = trade.orderStatus.avgFillPrice
                log.info(f"✅ {action} {qty} @ ${fill:.2f}")
                return fill
            else:
                log.error(f"❌ Order failed")
                return None
                
        except Exception as e:
            log.error(f"Order error: {e}")
            return None
    
    def place_stop(self, qty, stop_price):
        """IBKR stop order"""
        try:
            order = Order()
            order.action = "SELL"
            order.totalQuantity = abs(qty)
            order.orderType = "STP"
            order.auxPrice = stop_price
            order.tif = "GTC"
            
            trade = self.ib.placeOrder(self.smh, order)
            self.stop_order_id = trade.order.orderId
            
            log.info(f"🛡️  Stop @ ${stop_price:.2f}")
            
        except Exception as e:
            log.error(f"Stop error: {e}")
    
    def cancel_stop(self):
        """Cancel stop"""
        if self.stop_order_id:
            try:
                self.ib.cancelOrder(self.stop_order_id)
                self.stop_order_id = None
                log.info("🛡️  Stop cancelled")
            except:
                pass
    
    def check_stop_triggered(self):
        """Check if IBKR stop hit"""
        if not self.stop_order_id:
            return False
        
        try:
            positions = self.ib.positions()
            has_pos = any(p.contract.symbol == SYMBOL for p in positions)
            
            if not has_pos and self.position_qty > 0:
                log.warning("🛑 Stop triggered")
                self.position_qty = 0
                self.position_entry = 0
                self.stop_order_id = None
                self.stopped_today = True
                return True
        except:
            pass
        
        return False
    
    def enter(self):
        """Entry at 3:55 PM"""
        try:
            equity = self.get_account_value()
            leverage = self.get_leverage()
            
            ticker = self.ib.reqMktData(self.smh)
            self.ib.sleep(2)
            price = ticker.last if ticker.last == ticker.last else ticker.close
            
            if not price or price <= 0:
                log.error("❌ Invalid price")
                return
            
            qty = int((equity * leverage) / price)
            
            if qty <= 0:
                log.error("❌ Invalid qty")
                return
            
            log.info(f"📊 Entry: ${equity:,.0f} × {leverage}x = {qty} shares")
            
            fill = self.place_moc("BUY", qty)
            
            if fill:
                self.position_qty = qty
                self.position_entry = fill
                
                # Stop at 1.9% below entry
                stop_price = fill * (1 - STOP_PCT)
                self.place_stop(qty, stop_price)
                
                log.info(f"✅ OPENED: {qty} @ ${fill:.2f}")
            
        except Exception as e:
            log.error(f"Entry error: {e}")
    
    def exit(self, reason):
        """Exit position"""
        if self.position_qty == 0:
            return
        
        try:
            log.info(f"🚪 Exit: {reason}")
            
            self.cancel_stop()
            
            fill = self.place_moc("SELL", self.position_qty)
            
            if fill:
                pnl = self.position_qty * (fill - self.position_entry)
                pct = (fill / self.position_entry - 1) * 100
                
                log.info(f"✅ CLOSED: {self.position_qty} @ ${fill:.2f} | ${pnl:,.0f} ({pct:+.2f}%)")
                
                self.position_qty = 0
                self.position_entry = 0
            
        except Exception as e:
            log.error(f"Exit error: {e}")
    
    def daily_cycle(self):
        """Main loop"""
        try:
            now = datetime.now(pytz.timezone('US/Eastern')).time()
            
            # Morning reset
            if now < dt_time(9, 35):
                self.stopped_today = False
            
            # Check stop
            if self.position_qty > 0:
                self.check_stop_triggered()
            
            # 3:55 PM Entry (or re-entry)
            if now >= ENTRY_TIME and now < dt_time(15, 58):
                if self.position_qty == 0 and self.bull_signal:
                    if self.stopped_today:
                        log.info("🔄 Re-entering after stop")
                    self.enter()
            
            # 4:00 PM Update & Exit
            if now >= MARKET_CLOSE and now < dt_time(16, 5):
                ticker = self.ib.reqMktData(self.smh)
                self.ib.sleep(2)
                close = ticker.close
                
                if close and close > 0:
                    self.update_emas(close)
                    
                    # Bear exit
                    if self.position_qty > 0 and not self.bull_signal:
                        self.exit("BEAR")
                    
                    # Rebalancing (if still BULL)
                    elif self.position_qty > 0 and self.bull_signal:
                        equity = self.get_account_value()
                        leverage = self.get_leverage()
                        target_notional = equity * leverage
                        target_qty = int(target_notional / close)
                        
                        # Current position value at entry cost
                        current_notional = self.position_qty * self.position_entry
                        notional_diff = abs(target_notional - current_notional)
                        
                        # Rebalance if difference > $50
                        if notional_diff > 50:
                            qty_diff = target_qty - self.position_qty
                            
                            if qty_diff > 0:
                                log.info(f"📊 Rebalance UP: +{qty_diff} shares (${notional_diff:,.0f})")
                                self.place_moc("BUY", qty_diff)
                            elif qty_diff < 0:
                                log.info(f"📊 Rebalance DOWN: {qty_diff} shares (${notional_diff:,.0f})")
                                self.place_moc("SELL", abs(qty_diff))
                            
                            self.position_qty = target_qty
                            
                            # Update stop
                            self.cancel_stop()
                            stop_price = close * (1 - STOP_PCT)
                            self.place_stop(self.position_qty, stop_price)
            
        except Exception as e:
            log.error(f"Cycle error: {e}")
    
    def run(self):
        """Main loop"""
        log.info("🚀 PRODUCTION STARTED")
        log.info(f"   EMA {EMA_FAST}/{EMA_SLOW} | Stop {STOP_PCT*100}%")
        
        try:
            while True:
                if not self.ib.isConnected():
                    log.warning("⚠️  Reconnecting...")
                    self.connect()
                
                self.daily_cycle()
                time.sleep(10)
                
        except KeyboardInterrupt:
            log.info("⏹️  Shutdown")
            self.ib.disconnect()
        except Exception as e:
            log.critical(f"Fatal: {e}")
            self.ib.disconnect()

# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    log.info("=" * 80)
    log.info("PRODUCTION SYSTEM - FINAL")
    log.info(f"Port: {IBKR_PORT} ({'LIVE' if IBKR_PORT == 4001 else 'PAPER'})")
    log.info("=" * 80)
    
    system = ProductionSystem()
    system.run()