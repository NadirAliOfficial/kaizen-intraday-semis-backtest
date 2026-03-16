"""
IBKR PRODUCTION SYSTEM - FINAL
Exact logic matching clean backtest
Author: Nadir Ali
Version: 2.0 FINAL
"""
import sys
import io
import os
import re
import time
import logging
import requests
from datetime import datetime, time as dt_time
from dotenv import load_dotenv
from ib_insync import IB, Stock, Order, util, Index
import pandas as pd
import pytz

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# ============================================================================
# CONFIGURATION
# ============================================================================
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 4002  # 4002 = Gateway PAPER, 4001 = Gateway LIVE
CLIENT_ID = 10

SYMBOL = "SMH"
EXCHANGE = "SMART"

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
ENTRY_TIME     = dt_time(15, 55)   # PRODUCTION
ENTRY_TIME_END = dt_time(15, 58)   # PRODUCTION
MARKET_CLOSE   = dt_time(16, 0)

# Telegram Alerts
TG_TOKEN = os.getenv("TG_TOKEN", "")

def _strip_html(text):
    """Remove HTML tags from IBKR error messages"""
    return re.sub(r'<[^>]+>', ' ', text).strip()

def tg(msg):
    """Send Telegram alert — auto-fetches chat_id from latest bot update"""
    if not TG_TOKEN:
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", timeout=5)
        data = r.json()
        if not data.get("result"):
            return
        chat_id = data["result"][-1]["message"]["chat"]["id"]
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": _strip_html(msg), "parse_mode": ""},
            timeout=5
        )
    except:
        pass

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('trading.log', encoding='utf-8'),
        logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True))
    ]
)
log = logging.getLogger(__name__)

# Suppress noisy ib_insync internal logs
for _noisy in ('ib_insync.wrapper', 'ib_insync.client', 'ib_insync.ib'):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

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
        self.last_known_price = 0
        self.order_pending = False
        self._last_heartbeat_minute = -1
        self._entered_today = False
        self._close_done_today = False
        self._pending_trade = None  # track MOC trade for fill checking
        
        self.connect()
    
    def connect(self):
        """Connect to IBKR — retries indefinitely every 10-15s"""
        attempt = 0
        while True:
            attempt += 1
            try:
                self.ib = IB()
                log.info(f"⏳ Connecting to {IBKR_HOST}:{IBKR_PORT} clientId={CLIENT_ID}...")
                self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=20)
                self.ib.reqMarketDataType(4)  # 4 = delayed frozen (works after-hours on TWS)

                accounts = self.ib.managedAccounts()
                self._account = accounts[0] if accounts else ''
                log.info(f"✅ Connected (Port {IBKR_PORT}) | Account: {self._account}")
                tg(f"✅ <b>Connected</b> to IBKR (Port {IBKR_PORT})\nAccount: {self._account}")

                self.initialize_emas()
                self.sync_position()

                return True

            except Exception as e:
                delay = 10 if attempt % 2 == 0 else 15
                log.error(f"Connect failed (attempt {attempt}): {e} — retrying in {delay}s...")
                if attempt == 1:
                    tg(f"🔴 <b>Disconnected</b>\nCannot connect to IBKR. Retrying every {delay}s...\nError: {e}")
                time.sleep(delay)
    
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
        self.last_known_price = df['close'].iloc[-1]
        
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
            # Get all open trades (Trade objects have .contract and .order)
            open_trades = self.ib.openTrades()
            smh_stops = [t for t in open_trades
                        if t.contract.symbol == SYMBOL
                        and t.order.orderType == 'STP']

            if has_position and len(smh_stops) == 0:
                log.warning("⚠️  Position without stop - creating")
                stop_price = self.position_entry * (1 - STOP_PCT)
                self.place_stop(self.position_qty, stop_price)

            elif has_position and len(smh_stops) > 0:
                stop = smh_stops[0]
                self.stop_order_id = stop.order.orderId
                log.info(f"✅ Stop verified: {stop.order.auxPrice:.2f}")

                for extra in smh_stops[1:]:
                    self.ib.cancelOrder(extra.order)
                    log.warning(f"⚠️  Cancelled duplicate stop")

            elif not has_position and len(smh_stops) > 0:
                for stop in smh_stops:
                    self.ib.cancelOrder(stop.order)
                    log.warning(f"⚠️  Cancelled orphan stop")
                    
        except Exception as e:
            log.error(f"Stop sync error: {e}")
    
    def get_account_value(self):
        """Get NetLiquidation (any currency — account is EUR-denominated)"""
        account = getattr(self, '_account', '')

        for attempt in range(3):
            try:
                for v in self.ib.accountValues():
                    if v.tag == 'NetLiquidation' and v.account == account and v.currency != 'BASE':
                        val = float(v.value)
                        if val > 0:
                            log.info(f"   Equity: {v.currency} {val:,.2f}")
                            return val
            except:
                pass

            log.warning(f"⚠️  Account value attempt {attempt+1} returned 0, retrying...")
            self.ib.sleep(3)

        log.error("❌ Could not fetch account value after 3 attempts")
        return 0
    
    def get_vix(self):
        """Get VIX"""
        try:
            ticker = self.ib.reqMktData(self.vix)
            self.ib.sleep(2)
            vix = ticker.last if ticker.last == ticker.last else ticker.close
            self.ib.cancelMktData(self.vix)
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
    
    def place_order(self, action, qty):
        """Place MOC order (falls back to MKT if past 15:45 ET)"""
        try:
            now_et = datetime.now(pytz.timezone('US/Eastern')).time()
            order = Order()
            order.action = action
            order.totalQuantity = abs(qty)
            order.tif = "DAY"

            if now_et >= dt_time(15, 45):
                order.orderType = "MKT"
                log.info(f"📨 Using MKT order (past 15:45 ET)")
            else:
                order.orderType = "MOC"

            trade = self.ib.placeOrder(self.smh, order)
            self._pending_trade = trade
            self.ib.sleep(2)

            for i in range(30, 0, -1):
                if trade.orderStatus.status in ['Filled', 'Cancelled', 'Inactive']:
                    break
                sys.stdout.write(f"\r   ⏳ Waiting for fill... {i}s | {trade.orderStatus.status}    ")
                sys.stdout.flush()
                self.ib.sleep(1)
            print()  # new line after countdown

            status = trade.orderStatus.status
            if status == 'Filled':
                fill = trade.orderStatus.avgFillPrice
                log.info(f"✅ {action} {qty} @ ${fill:.2f}")
                tg(f"✅ <b>Order Filled</b>\n{action} {qty} SMH @ ${fill:.2f}")
                self._pending_trade = None
                return fill
            elif status in ('PreSubmitted', 'Submitted'):
                log.info(f"📨 Order submitted — {action} {qty} {order.orderType} | awaiting fill")
                tg(f"📨 <b>Order Submitted</b>\n{action} {qty} SMH ({order.orderType})\nAwaiting fill at market close")
                return -1  # signals order is live, not yet filled
            else:
                log.error(f"❌ Order rejected — status: {status}")
                err_msgs = [f"{e.errorCode}: {e.message}" for e in trade.log if e.errorCode]
                err_str = "\n".join(err_msgs) if err_msgs else status
                tg(f"🚫 <b>Order Rejected</b>\n{action} {qty} SMH\n{err_str}")
                for entry in trade.log:
                    if entry.errorCode:
                        log.error(f"   IBKR error {entry.errorCode}: {entry.message}")
                self._pending_trade = None
                return None

        except Exception as e:
            log.error(f"Order error: {e}")
            self._pending_trade = None
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
    
    def check_pending_fill(self):
        """Check if a pending MOC/MKT order has filled"""
        if not self._pending_trade:
            return
        trade = self._pending_trade
        status = trade.orderStatus.status
        if status == 'Filled':
            fill = trade.orderStatus.avgFillPrice
            qty = int(trade.order.totalQuantity)
            action = trade.order.action
            log.info(f"✅ Pending fill: {action} {qty} @ ${fill:.2f}")
            self._pending_trade = None
            self.order_pending = False

            if action == 'BUY':
                self.position_qty = qty
                self.position_entry = fill
                stop_price = fill * (1 - STOP_PCT)
                self.place_stop(qty, stop_price)
                log.info(f"✅ OPENED: {qty} @ ${fill:.2f}")
            elif action == 'SELL':
                if self.position_qty > 0:
                    pnl = self.position_qty * (fill - self.position_entry)
                    pct = (fill / self.position_entry - 1) * 100 if self.position_entry > 0 else 0
                    log.info(f"✅ CLOSED: {self.position_qty} @ ${fill:.2f} | ${pnl:,.0f} ({pct:+.2f}%)")
                self.position_qty = 0
                self.position_entry = 0
        elif status in ('Cancelled', 'Inactive'):
            log.error(f"❌ Pending order {status}")
            self._pending_trade = None
            self.order_pending = False

    def enter(self):
        """Entry"""
        if self.order_pending or self._entered_today:
            return
        try:
            equity = self.get_account_value()
            leverage = self.get_leverage()

            ticker = self.ib.reqMktData(self.smh)
            self.ib.sleep(2)
            price = ticker.last if ticker.last == ticker.last else ticker.close
            price = price if price == price else None  # NaN guard
            if not price or price <= 0:
                price = self.last_known_price
                log.warning(f"⚠️  Live price unavailable, using last close: ${price:.2f}")

            if not price or price <= 0:
                log.error("❌ No price available, skipping entry")
                return

            qty = int((equity * leverage) / price)

            if qty <= 0:
                log.error("❌ Invalid qty (equity=${equity:.0f})")
                return

            log.info(f"📊 Entry: ${equity:,.0f} × {leverage}x = {qty} shares @ ~${price:.2f}")

            fill = self.place_order("BUY", qty)
            self._entered_today = True  # prevent repeated entries

            if fill == -1:
                self.order_pending = True
            elif fill and fill > 0:
                self.order_pending = False
                self.position_qty = qty
                self.position_entry = fill

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

            fill = self.place_order("SELL", self.position_qty)

            if fill and fill > 0:
                pnl = self.position_qty * (fill - self.position_entry)
                pct = (fill / self.position_entry - 1) * 100

                log.info(f"✅ CLOSED: {self.position_qty} @ ${fill:.2f} | ${pnl:,.0f} ({pct:+.2f}%)")

                self.position_qty = 0
                self.position_entry = 0
            elif fill == -1:
                self.order_pending = True

        except Exception as e:
            log.error(f"Exit error: {e}")
    
    def daily_cycle(self):
        """Main loop"""
        try:
            now_et = datetime.now(pytz.timezone('US/Eastern'))
            now = now_et.time()

            # Check pending order fills
            self.check_pending_fill()

            # HEARTBEAT LOGGING (every 5 minutes, 24/7)
            current_minute = now_et.minute
            if current_minute % 5 == 0 and current_minute != self._last_heartbeat_minute:
                self._last_heartbeat_minute = current_minute
                try:
                    ticker = self.ib.reqMktData(self.smh)
                    self.ib.sleep(2)
                    raw = ticker.last if ticker.last == ticker.last else ticker.close
                    price = raw if (raw == raw and raw > 0) else None
                except:
                    price = None

                price_str = f"${price:.2f}" if price is not None else "No data"
                log.info("=" * 60)
                log.info(f"💓 HEARTBEAT | {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
                log.info(f"   SMH Price: {price_str}")
                log.info(f"   EMA 25: {self.ema_25:.2f}")
                log.info(f"   EMA 125: {self.ema_125:.2f}")
                log.info(f"   Signal: {'BULL ✅' if self.bull_signal else 'BEAR ❌'}")
                log.info(f"   Position: {self.position_qty} shares")
                if self.position_qty > 0:
                    log.info(f"   Entry: ${self.position_entry:.2f}")
                if self.order_pending:
                    log.info(f"   Pending order: YES")
                log.info("=" * 60)

                # Telegram 5-min heartbeat
                now_et_str = now_et.strftime('%H:%M ET')
                entry_dt = datetime.combine(now_et.date(), ENTRY_TIME, tzinfo=now_et.tzinfo)
                diff = (entry_dt - now_et).total_seconds()
                if diff > 0:
                    h, rem = divmod(int(diff), 3600)
                    m, s = divmod(rem, 60)
                    next_trade = f"{h}h {m:02d}m" if h > 0 else f"{m}m {s:02d}s"
                else:
                    next_trade = "In window / passed"
                signal_icon = "🐂 BULL" if self.bull_signal else "🐻 BEAR"
                pos_str = f"{self.position_qty} shares @ ${self.position_entry:.2f}" if self.position_qty > 0 else "No position"
                tg(
                    f"💓 <b>Heartbeat</b> | {now_et_str}\n"
                    f"SMH: {price_str} | {signal_icon}\n"
                    f"Position: {pos_str}\n"
                    f"Next entry: {next_trade}"
                )

            # Morning reset (narrow window so it runs once, not all pre-market)
            if dt_time(9, 30) <= now < dt_time(9, 35):
                self.stopped_today = False
                self.order_pending = False
                self._entered_today = False
                self._close_done_today = False

            # Check stop
            if self.position_qty > 0:
                self.check_stop_triggered()

            # Entry window (runs ONCE per day)
            if now >= ENTRY_TIME and now < ENTRY_TIME_END:
                if self.position_qty == 0 and not self.order_pending and not self._entered_today and self.bull_signal:
                    if self.stopped_today:
                        log.info("🔄 Re-entering after stop")
                    self.enter()

            # 4:00 PM Update & Exit (runs ONCE per day)
            if now >= MARKET_CLOSE and now < dt_time(16, 5) and not self._close_done_today:
                self._close_done_today = True
                ticker = self.ib.reqMktData(self.smh)
                self.ib.sleep(2)
                close = ticker.close

                if close and close > 0:
                    self.update_emas(close)

                    # Bear exit
                    if self.position_qty > 0 and not self.bull_signal:
                        self.exit("BEAR")

                    # If still in position
                    elif self.position_qty > 0 and self.bull_signal:
                        # 1. TRAILING STOP
                        new_stop = close * (1 - STOP_PCT)

                        current_stop = self.position_entry * (1 - STOP_PCT)
                        if self.stop_order_id:
                            try:
                                for t in self.ib.openTrades():
                                    if t.order.orderId == self.stop_order_id:
                                        current_stop = t.order.auxPrice
                                        break
                            except:
                                pass

                        if new_stop > current_stop:
                            log.info(f"📈 Trailing stop: ${current_stop:.2f} → ${new_stop:.2f}")
                            self.cancel_stop()
                            self.place_stop(self.position_qty, new_stop)

                        # 2. REBALANCING (only if >2% drift)
                        equity = self.get_account_value()
                        leverage = self.get_leverage()
                        target_notional = equity * leverage
                        target_qty = int(target_notional / close)

                        current_notional = self.position_qty * close
                        notional_diff = abs(target_notional - current_notional)

                        if notional_diff > 50:  # rebalance if >$50 difference
                            qty_diff = target_qty - self.position_qty

                            if qty_diff > 0:
                                log.info(f"📊 Rebalance UP: +{qty_diff} shares (${notional_diff:,.0f} drift)")
                                self.place_order("BUY", qty_diff)
                            elif qty_diff < 0:
                                log.info(f"📊 Rebalance DOWN: {qty_diff} shares (${notional_diff:,.0f} drift)")
                                self.place_order("SELL", abs(qty_diff))

                            self.position_qty = target_qty

        except Exception as e:
            log.error(f"Cycle error: {e}")
    
    def _show_countdown(self):
        """Show live countdown to next entry on a single line"""
        from datetime import timedelta
        now_et = datetime.now(pytz.timezone('US/Eastern'))

        entry_dt = datetime.combine(now_et.date(), ENTRY_TIME, tzinfo=now_et.tzinfo)
        if entry_dt <= now_et:
            # Today's window passed — show countdown to next weekday
            days_ahead = 1
            next_day = now_et.date() + timedelta(days=days_ahead)
            while next_day.weekday() >= 5:  # skip Saturday(5) and Sunday(6)
                days_ahead += 1
                next_day = now_et.date() + timedelta(days=days_ahead)
            entry_dt = datetime.combine(next_day, ENTRY_TIME, tzinfo=now_et.tzinfo)

        diff = (entry_dt - now_et).total_seconds()

        if self._entered_today or self.position_qty > 0 or self.order_pending:
            return

        h = int(diff // 3600)
        m = int((diff % 3600) // 60)
        s = int(diff % 60)

        if h > 0:
            countdown = f"{h}h {m:02d}m {s:02d}s"
        elif m > 0:
            countdown = f"{m}m {s:02d}s"
        else:
            countdown = f"{s}s"

        signal = "BULL" if self.bull_signal else "BEAR"
        line = f"\r   ⏳ Entry in {countdown} | {signal} | Pos: {self.position_qty}    "
        sys.stdout.buffer.write(line.encode('utf-8'))
        sys.stdout.buffer.flush()

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
                self._show_countdown()
                time.sleep(1)

        except KeyboardInterrupt:
            print()  # clean line after \r
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

    if TG_TOKEN:
        log.info("✅ Telegram alerts active")
        tg("🟢 <b>Bot Started</b>\nSMH production system is live.\nEntry: 15:55 ET | Stop: 1.9%")
    else:
        log.warning("⚠️  Telegram: TG_TOKEN not set in .env")

    system = ProductionSystem()
    system.run()