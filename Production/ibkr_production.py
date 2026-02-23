"""
IBKR PRODUCTION TRADING SYSTEM - HARDENED
EMA 25/125 Strategy with Full Safeguards
Author: Nadir Ali
Version: 1.0 Production
"""
import time
import logging
from datetime import datetime, time as dt_time
from ib_insync import IB, Stock, Order, util
import pandas as pd
import pytz

# ============================================================================
# CONFIGURATION
# ============================================================================
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497  # 7497 = LIVE, 7496 = PAPER
CLIENT_ID = 1

SYMBOL = "SMH"
EXCHANGE = "ARCA"

# Strategy Parameters
EMA_FAST = 25
EMA_SLOW = 125
STOP_LOSS_PCT = 0.018  # -1.8%

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
# PRODUCTION TRADING SYSTEM
# ============================================================================
class ProductionTradingSystem:
    def __init__(self):
        self.ib = None
        self.smh = Stock(SYMBOL, EXCHANGE, "USD")
        
        self.position_qty = 0
        self.position_entry = 0
        self.day_start_equity = 0
        self.stop_order_id = None
        
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
                
                log.info(f"📍 Existing position detected: {self.position_qty} shares @ ${self.position_entry:.2f}")
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
    
    def get_leverage(self):
        """VIX-based leverage (defaults to 3.0)"""
        try:
            # In production, fetch real VIX if available
            # For now, use base leverage
            return LEV_BASE
        except:
            return LEV_BASE
    
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
                log.info(f"✅ {action} filled: {quantity} @ ${fill_price:.2f}")
                return fill_price
            else:
                log.error(f"❌ Order failed: {trade.orderStatus.status}")
                return None
                
        except Exception as e:
            log.error(f"Order placement error: {e}")
            return None
    
    def place_stop_order(self, quantity, stop_price):
        """Place protective stop order at IBKR"""
        try:
            order = Order()
            order.action = "SELL"
            order.totalQuantity = abs(quantity)
            order.orderType = "STP"
            order.auxPrice = stop_price
            order.tif = "GTC"
            
            trade = self.ib.placeOrder(self.smh, order)
            self.stop_order_id = trade.order.orderId
            
            log.info(f"🛡️  Stop order placed: {quantity} @ ${stop_price:.2f}")
            
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
    
    def check_virtual_stop(self):
        """Backup virtual stop check"""
        if self.position_qty == 0 or self.day_start_equity == 0:
            return False
        
        try:
            current_equity = self.get_account_value()
            dd = (current_equity - self.day_start_equity) / self.day_start_equity
            
            if dd <= -STOP_LOSS_PCT:
                log.warning(f"🛑 Virtual stop triggered: {dd*100:.2f}%")
                self.exit_position("VIRTUAL_STOP")
                return True
                
        except Exception as e:
            log.error(f"Virtual stop check error: {e}")
        
        return False
    
    def enter_position(self):
        """Enter position with MOC order"""
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
            
            log.info(f"📊 Entry signal: Equity=${equity:,.0f} Lev={leverage}x Price=${price:.2f} Qty={qty}")
            
            # Place MOC order
            fill_price = self.place_moc_order("BUY", qty)
            
            if fill_price:
                self.position_qty = qty
                self.position_entry = fill_price
                
                # Place protective stop
                # stop_price = fill_price * (1 - STOP_LOSS_PCT - 0.005)  # -2.5% buffer
                stop_price = fill_price * (1 - STOP_LOSS_PCT - 0.001)  # -1.9% effective
                self.place_stop_order(qty, stop_price)
                
                log.info(f"✅ POSITION OPENED: {qty} @ ${fill_price:.2f}")
            
        except Exception as e:
            log.error(f"Entry error: {e}")
    
    def exit_position(self, reason):
        """Exit position with MOC order"""
        if self.position_qty == 0:
            return
        
        try:
            log.info(f"🚪 Exit signal: {reason}")
            
            # Cancel stop order
            self.cancel_stop_order()
            
            # Place MOC sell
            fill_price = self.place_moc_order("SELL", self.position_qty)
            
            if fill_price:
                pnl = self.position_qty * (fill_price - self.position_entry)
                pnl_pct = (fill_price / self.position_entry - 1) * 100
                
                log.info(f"✅ POSITION CLOSED: {self.position_qty} @ ${fill_price:.2f} | P&L: ${pnl:,.0f} ({pnl_pct:+.2f}%)")
                
                self.position_qty = 0
                self.position_entry = 0
            
        except Exception as e:
            log.error(f"Exit error: {e}")
    
    def daily_cycle(self):
        """Main trading logic"""
        try:
            now = datetime.now(pytz.timezone('US/Eastern')).time()
            
            # Morning: Set day start equity
            if now < dt_time(9, 35) and self.day_start_equity == 0:
                self.day_start_equity = self.get_account_value()
                log.info(f"📅 Day start: ${self.day_start_equity:,.2f}")
            
            # Continuous: Virtual stop check (backup)
            if self.position_qty > 0:
                self.check_virtual_stop()
            
            # 3:55 PM: Entry
            if now >= ENTRY_TIME and now < dt_time(15, 58):
                if self.position_qty == 0 and self.bull_signal:
                    self.enter_position()
            
            # 4:00 PM: Update EMAs and rebalance/exit
            if now >= MARKET_CLOSE and now < dt_time(16, 5):
                ticker = self.ib.reqMktData(self.smh)
                self.ib.sleep(2)
                close = ticker.close
                
                if close and close > 0:
                    self.update_emas(close)
                    
                    # Bear exit
                    if self.position_qty > 0 and not self.bull_signal:
                        self.exit_position("BEAR_SIGNAL")
                    
                    # Rebalancing logic (if BULL and in position)
                    elif self.position_qty > 0 and self.bull_signal:
                        equity = self.get_account_value()
                        leverage = self.get_leverage()
                        target_notional = equity * leverage
                        target_qty = int(target_notional / close)
                        
                        current_notional = self.position_qty * close
                        notional_diff = abs(target_notional - current_notional)
                        
                        # Rebalance if difference > $50
                        if notional_diff > 50:
                            qty_diff = target_qty - self.position_qty
                            
                            if qty_diff > 0:
                                log.info(f"📊 Rebalancing UP: +{qty_diff} shares (${notional_diff:,.0f} new capital)")
                                self.place_moc_order("BUY", qty_diff)
                                self.position_qty = target_qty
                            elif qty_diff < 0:
                                log.info(f"📊 Rebalancing DOWN: {qty_diff} shares (${notional_diff:,.0f} reduction)")
                                self.place_moc_order("SELL", abs(qty_diff))
                                self.position_qty = target_qty
                            
                            # Update stop order
                            self.cancel_stop_order()
                            stop_price = close * (1 - STOP_LOSS_PCT - 0.005)
                            self.place_stop_order(self.position_qty, stop_price)
                        else:
                            log.info(f"✅ No rebalancing needed (${notional_diff:.0f} difference)")
            
            # After hours: Reset
            if now > dt_time(17, 0):
                self.day_start_equity = 0
            
        except Exception as e:
            log.error(f"Daily cycle error: {e}")
    
    def run(self):
        """Main event loop with reconnection"""
        log.info("🚀 Production system started")
        
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
    log.info("IBKR PRODUCTION TRADING SYSTEM")
    log.info(f"Strategy: EMA {EMA_FAST}/{EMA_SLOW}")
    log.info(f"Port: {IBKR_PORT} ({'LIVE' if IBKR_PORT == 7497 else 'PAPER'})")
    log.info("=" * 80)
    
    system = ProductionTradingSystem()
    system.run()