# Modified by Mephisto-000 on 2026-10-25: Shioaji 1.7 compatibility through lib/sinopac_session,
#   one order chokepoint (_send_order) and a spot layer (TW stocks as spot inventory: board lots
#   + intraday odd lots, price-protected and cash-checked) so lib/venue_wiring auto-wires SinoPac;
#   (2026-10-31) cancel_spot_order passes the order gate, so it takes upstream's turn order lock.
# Original work: Copyright 2025-2026 WuChi Technology Company Limited
# Licensed under the Apache License, Version 2.0
"""
SinoPac (永豐金證券) Taiwan stock order execution library — Shioaji 1.5 / 1.7.

Companion to references/sinopac-broker.md (account setup / CA certificate) and
lib/sinopac_session.py (the one login per process). Credentials in .env:
sinopac_api_key, sinopac_secret_key, sinopac_ca_path, sinopac_ca_passwd,
optional sinopac_person_id. Set SINOPAC_LIVE=true for real orders — without it
Shioaji runs in simulation mode against a FAKE account whose holdings have
nothing to do with the user's real account.

Two layers:

  SPOT LAYER (the reconciler's — lib/venue_wiring auto-wires SinoPac like the
  paper venue's TW stocks): get_spot_price / get_spot_balances /
  format_spot_qty / place_spot_market_order / get_spot_open_orders /
  cancel_spot_order. A TW stock is spot inventory quoted in TWD (cash shares:
  never short, lib.portfolio holds the key while the TWSE session is shut).
  place_spot_market_order splits a share count into board lots (整股, IOC
  limit order; ROD inside the 13:25–13:30 closing auction) and an odd-lot
  remainder (盤中零股, ROD limit order — the odd-lot market takes no market
  orders and matches by call auction), cancels what the auction did not fill,
  and returns only exchange-confirmed fills.

  LEGACY TYPE-B HELPERS (unchanged behaviour): place_odd_lot_order (after-hours
  odd lot, market order — the combination the first live deployment verified)
  and place_order_sinopac (TWD diff → ≤999-share odd-lot orders).

Harvested from the first live Taiwan-stock deployment (fleet uid 18198,
2026-07), which lost three rounds of orders to SILENT rejections. Design rules:

1. FAIL LOUD. Shioaji's place_order does NOT raise on rejection — a rejected
   order just sits with status Failed (or never leaves PendingSubmit). Every
   order here is polled until the exchange settles it; Failed raises
   SinopacError with the broker's message.
2. ENUMS, NEVER STRINGS. Every order field is the Shioaji enum (the bare string
   "MKT" was silently rejected in the field). Statuses are compared through
   .value: Shioaji 1.7's native enums print as "OrderStatus.Filled".
3. ODD LOT FOR <1000 SHARES. A Common-lot (整股) order's quantity is in 張
   (1000-share board lots); a share count sent as a Common lot silently
   vanishes. Odd lots are always their own order.
4. PRICE-PROTECTED. Spot-layer orders are limit orders at the best quote ±
   SINOPAC_MAX_SLIPPAGE (default 1%), snapped to the TWSE tick table and
   clamped to the day's limit-up / limit-down — a thin book never fills a
   "market" order 10% away.
5. CASH-CHECKED. TW cash shares settle at T+2 and the broker does not check
   cash when the order is placed: a buy above the settlement account's balance
   is a settlement default (違約交割). Live buys are capped at the bank balance
   less every pending settlement, fees and a buffer — never above.
6. HALTABLE + AUDITED. Every order passes _send_order: lib/guard's restart
   stop, the HALT freeze and the account hold before any network call; every
   attempt / outcome lands in state/audit.jsonl. An order whose outcome cannot
   be confirmed trips HALT: the bot's book is in doubt until the user looks.
7. IDEMPOTENT-ISH. client_tag (≤6 alphanumeric chars — Shioaji's
   custom_field) unique per intent; a resubmit with the same tag the same day
   is refused locally (DuplicateOrder). Spot-layer tags derive from the
   reconciler's client_order_id ('b' + hash + leg letter).

Field-verified quirks (all cost real debugging on a live account):
- CA must be activated AFTER login (api.activate_ca), and only exists in live
  mode; orders before activation fail with "CA not activated for: <person>".
- Warning-flagged / disposition stocks (警示股, 處置股, e.g. "警示股預收條件")
  may require pre-funded settlement — surfaced, never retried.
- Simulation mode does not take odd-lot orders (Shioaji 模擬模式): the spot
  layer trades whole board lots only while SINOPAC_LIVE is not true.
"""

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from lib import guard, reject_token
from lib import sinopac_session as ss

guard.mark_money_process()  # Stop in the chat never kills this process (lib/guard)

VENUE = ss.VENUE
BOARD_LOT = 1000
# Odd-lot orders carry at most 999 shares (1000 = one board lot).
MAX_ODD_LOT_SHARES = 999

# Terminal-failure statuses (legacy confirm_order). Filled is terminal-success;
# Submitted/PreSubmitted mean the exchange accepted the order (it may rest, e.g.
# placed after hours); PendingSubmit means the broker has NOT acknowledged it yet.
FAILED_STATUSES = {"Failed", "Cancelled", "Inactive"}
_TERMINAL = {"Filled", "Cancelled", "Failed", "Inactive"}

# Spot layer timing (Taipei wall clock). Continuous trading 09:00–13:25, closing
# call auction 13:25–13:30; intraday odd lots by call auction (every 5 s since
# 2024-12-02, from 09:10 at the latest).
_OPEN = (9, 0)
_ODD_FIRST_MATCH = (9, 10)
_CLOSE_AUCTION = (13, 25)
_CLOSE = (13, 30)
IOC_WAIT_S = 20        # an IOC settles within seconds; this is the ack timeout
ODD_WAIT_S = 45        # odd lots: auctions every 5 s — nine chances, then cancel the rest
AUCTION_GRACE_S = 40   # after the 13:30 closing auction prints
CANCEL_WAIT_S = 30     # a cancel not confirmed in this long = outcome unknown → HALT
# after the session's last match (13:30 auction) a regular-session order cannot fill any
# more: a remainder whose cancel the exchange no longer answers is final this long after it
SESSION_FINAL = (13, 32)
POST_CLOSE_WAIT_S = 240
TAG_LOOKUP_TRIES = 3
DAY_BUYS_PATH = "state/sinopac_day_buys.json"
POLL_S = 1.0
DEFAULT_SLIPPAGE = 0.01
FEE_RATE = 0.001425    # 手續費 ceiling (before the broker's discount) — cash check + estimate
MIN_FEE_TWD = 20       # per board-lot order; odd lots are charged less, never more
CASH_BUFFER = 0.005    # on top of fees: a fill one tick above the limit never defaults
PRICE_TTL_S = 10.0
# one spot execution at a time per process: a TWAP slice thread and the
# reconcile loop never interleave their legs on the broker session
_exec_lock = threading.Lock()

SinopacError = ss.SinopacError


class OrderNotConfirmed(Exception):
    """Order was sent but never acknowledged by the exchange within timeout.
    It MAY still go through — query again before resubmitting."""


class DuplicateOrder(Exception):
    """An order with the same client_tag already exists today — refused
    locally so a resubmit cannot double the position."""


class PaperMarketClosed(SinopacError):
    """A TW stock order outside the TWSE session (09:00–13:30 on a trading
    day). The class NAME is the contract manager/flatten._defer_tw_close
    matches (shared with lib/order_paper's TW stocks): a close-all that meets
    it is deferred to the reconciler's first round after the open instead of
    being booked as closed."""


MarketClosed = PaperMarketClosed


class NoFill(SinopacError):
    """The order reached the exchange and nothing filled inside the price
    protection (no liquidity there, or the exchange cancelled it). Nothing
    changed on the account; the next reconcile round tries again."""


# ── connection ───────────────────────────────────────────────────────────────

def _get_api(env):
    """(api, stock account) for ORDERS: logged in, CA activated in live mode —
    raising at connect time so the CA trap surfaces before the first order."""
    api = ss.get_api(env, need_ca=True)
    return api, ss.stock_account(api)


def _read_api(env):
    """(api, stock account) for READS — no CA needed."""
    api = ss.get_api(env)
    return api, ss.stock_account(api)


def reset_connection():
    """Drop the session so the next call re-logs-in (e.g. after changing
    SINOPAC_LIVE in .env)."""
    ss.reset()


def _simulation(env):
    return not ss.is_live(env)


# ── account info ─────────────────────────────────────────────────────────────

def get_account_balance(env):
    """Stock account settlement balance in TWD. Raises on failure — a silent
    0.0 would make the reconciler think the account is empty."""
    _, account = _read_api(env)
    balance = ss.read(env, lambda a: a.account_balance(account), kind="account")
    if balance is None:
        raise SinopacError("account_balance returned None")
    row = balance[0] if isinstance(balance, (list, tuple)) else balance
    err = str(getattr(row, "errmsg", "") or "")
    if err:
        raise SinopacError(f"account_balance: {err}")
    return float(row.acc_balance)


def _norm_code(symbol):
    s = str(symbol or "").strip().upper()
    for suffix in (".TWO", ".TW"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _stock_rows(env):
    """Cash (現股) long rows in SHARES (lib/account_sinopac.stock_rows)."""
    from lib import account_sinopac
    return account_sinopac.stock_rows(env)


def get_sinopac_positions(env):
    """{symbol: {'side': 'long', 'size': value_in_TWD}} — the legacy hand-wired
    reconciler shape (the auto-wired spot layer reads get_spot_balances)."""
    positions = {}
    for r in _stock_rows(env):
        price = r["last_price"] or _last_price(env, r["code"])
        if price > 0:
            positions[r["code"]] = {"side": "long", "size": r["quantity"] * price}
    return positions


_px_cache = {}


def _quote(env, symbol):
    """{'last', 'bid', 'ask', 'reference', 'limit_up', 'limit_down', 'info'}
    from one snapshot + the contract's daily limits."""
    api, _ = _read_api(env)
    contract = ss.stock_contract(api, symbol)
    info = ss.stock_info(api, contract)
    snaps = ss.read(env, lambda a: a.snapshots([contract]), kind="market") or []
    snap = snaps[0] if snaps else None

    def f(obj, name):
        try:
            v = float(getattr(obj, name, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0 and math.isfinite(v) else 0.0

    q = {"last": f(snap, "close"), "bid": f(snap, "buy_price"), "ask": f(snap, "sell_price"),
         "reference": f(info, "reference"), "limit_up": f(info, "limit_up"),
         "limit_down": f(info, "limit_down"), "info": info}
    last = q["last"] or q["reference"]
    if last > 0:
        _px_cache[symbol] = (time.monotonic(), last)
    return q


def _last_price(env, symbol):
    symbol = _norm_code(symbol)
    hit = _px_cache.get(symbol)
    if hit and time.monotonic() - hit[0] < PRICE_TTL_S:
        return hit[1]
    q = _quote(env, symbol)
    return q["last"] or q["reference"]


# ── spot layer: reads ────────────────────────────────────────────────────────

def get_spot_price(env, symbol):
    """Last trade price in TWD (yesterday's reference before the first trade)."""
    px = _last_price(env, symbol)
    if not px > 0:
        raise SinopacError(f"{_norm_code(symbol)}: no price from SinoPac")
    return px


class _ByCode(dict):
    """{code: shares} that answers '0050.TW' / '6488.TWO' as the bare code:
    lib/venue_wiring keeps a suffixed strategy symbol whole as the inventory
    key, and a miss there reads as "the account holds none" — a book
    write-off with the shares still held."""

    def __getitem__(self, k):
        return dict.__getitem__(self, _norm_code(k))

    def get(self, k, default=None):
        return dict.get(self, _norm_code(k), default)

    def __contains__(self, k):
        return dict.__contains__(self, _norm_code(k))


def get_spot_balances(env):
    """{stock code: shares} of cash shares on the stock account — what a sell
    may draw on (the reconciler caps the bot's sells at its own book first).
    Suffixed codes ('0050.TW') read as their bare code."""
    rows = _stock_rows(env)
    out = _ByCode()
    for r in rows:
        out[r["code"]] = out.get(r["code"], 0.0) + r["quantity"]
    try:  # the account page reads the same snapshot: keep it fresh while trading
        from lib import account_sinopac
        account_sinopac.refresh_if_stale(env, positions=rows)
    except Exception as e:
        logging.info(f"[sinopac] account snapshot not refreshed ({type(e).__name__}: {e})")
    return out


def get_spot_rules(env, symbol):
    """Whole shares; a board lot is 1000. Simulation takes board lots only."""
    lot = float(BOARD_LOT) if _simulation(env) else 1.0
    return {"min_qty": lot, "step_size": lot, "min_notional": 0.0}


def format_spot_qty(env, symbol, qty):
    """Shares floored to what can be sent ('' = below one share / one lot)."""
    step = BOARD_LOT if _simulation(env) else 1
    q = int(math.floor(float(qty) / step + 1e-9)) * step
    return str(q) if q > 0 else ""


# ── order status helpers ─────────────────────────────────────────────────────

def _same_trade(a, b):
    for attr in ("id", "seqno"):
        x, y = getattr(a.order, attr, None), getattr(b.order, attr, None)
        if x and y:
            return str(x) == str(y)
    return a is b


def _refresh(env, trade):
    """The trade's latest state. 1.7.6+ updates trades from order events
    itself; update_status makes it deterministic on every version."""
    api, account = _read_api(env)
    ss.throttle("order")
    try:
        if "trade" in ss._params(api.update_status):
            api.update_status(trade=trade)
        else:
            api.update_status(account)
    except Exception as e:
        logging.info(f"[sinopac] update_status: {type(e).__name__}")
    for t in api.list_trades() or []:
        if _same_trade(t, trade):
            return t
    return trade


def _deals(trade):
    try:
        return list(getattr(trade.status, "deals", None) or [])
    except TypeError:
        return []


def _normalize(trade, mult=1):
    """Status dict in ORDER units (lots for a board-lot order) + shares."""
    st = trade.status
    deals = _deals(trade)
    filled = sum(float(d.quantity) for d in deals)
    if deals and filled:
        avg = sum(float(d.price) * float(d.quantity) for d in deals) / filled
    else:
        # a fill count without its deal rows: priced at the order's own limit
        # (a market order has none — 0, the caller's price fallback applies)
        filled = float(getattr(st, "deal_quantity", 0) or 0)
        avg = float(getattr(trade.order, "price", 0) or 0) if filled else 0.0
    order_qty = float(getattr(st, "order_quantity", None) or trade.order.quantity or 0)
    return {
        "seqno": str(getattr(trade.order, "seqno", "") or ""),
        "ordno": str(getattr(trade.order, "ordno", "") or ""),
        "status": ss.enum_value(st.status),
        "filled_qty": filled,
        "order_qty": order_qty,
        "cancel_qty": float(getattr(st, "cancel_quantity", 0) or 0),
        "filled_shares": filled * mult,
        "avg_fill_price": avg,
        "msg": str(getattr(st, "msg", "") or ""),
        "simulation": bool(ss.simulation()),
    }


def confirm_order(env, trade, timeout=90):
    """Poll a trade until the exchange acknowledges it. Returns the normalized
    dict once status is Filled OR accepted-and-resting (Submitted/PreSubmitted/
    PartFilled after the fill wait). Raises SinopacError on Failed/Cancelled/
    Inactive (with the broker's msg — this is the silent-rejection killer),
    OrderNotConfirmed if still PendingSubmit at timeout."""
    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        trade = _refresh(env, trade)
        result = _normalize(trade)
        status = result["status"]
        if status in FAILED_STATUSES:
            raise SinopacError(
                f"order {result['seqno']} {status}: {result['msg'] or '(no msg from broker)'}"
            )
        if status == "Filled":
            return result
        # Accepted but not filled — keep polling for a fill until timeout,
        # then return the resting order honestly (normal outside 09:00-13:30).
        time.sleep(2)
    if result is None or result["status"] == "PendingSubmit":
        raise OrderNotConfirmed(
            f"order still {result['status'] if result else 'UNKNOWN'} after {timeout}s — "
            f"not acknowledged by the exchange; query again before resubmitting"
        )
    return result


def _check_duplicate(env, api, account, symbol, client_tag):
    ss.throttle("order")
    api.update_status(account)
    for t in api.list_trades() or []:
        if (
            str(getattr(t.order, "custom_field", "") or "") == client_tag
            and _norm_code(getattr(t.contract, "code", "")) == symbol
            and ss.enum_value(t.status.status) not in FAILED_STATUSES
        ):
            raise DuplicateOrder(
                f"order with client_tag={client_tag} for {symbol} already exists today "
                f"(seqno {t.order.seqno}, status {ss.enum_value(t.status.status)}) — "
                f"refusing resubmit"
            )


def _find_by_tag(api, account, symbol, client_tag, tries=1):
    """Today's newest trade of `symbol` carrying `client_tag`, or None — asked
    `tries` times a couple of seconds apart (an order that did reach the
    exchange can take a moment to show)."""
    for i in range(max(1, tries)):
        if i:
            time.sleep(2)
        try:
            api.update_status(account)
        except Exception as e:
            logging.info(f"[sinopac] update_status: {type(e).__name__}")
        try:
            trades = list(api.list_trades() or [])
        except Exception as e:
            logging.info(f"[sinopac] list_trades: {type(e).__name__}")
            continue
        for t in reversed(trades):
            if (str(getattr(t.order, "custom_field", "") or "") == client_tag
                    and _norm_code(getattr(t.contract, "code", "")) == symbol):
                return t
    return None


# Raised by the SDK before anything is sent (argument checks, a refused login / CA / terms):
# a definite "not placed". Anything else out of place_order may have reached the exchange.
_PRESEND_ERRORS = frozenset({
    "ValidationError", "BadRequestError", "AccountNotProvideError", "AccountNotSignError",
    "CaError", "CaExpiredError", "CaPasswordError", "ShioajiValueError", "ShioajiTypeError",
    "ShioajiPermissionError", "AuthError", "TokenError", "ValueError", "TypeError",
})


# ── the one way out: every order goes through here ───────────────────────────

def _build_order(api, action, price, quantity, price_type, order_type, lot, tag, account):
    sj = ss.shioaji()
    kw = dict(
        action=getattr(ss.const("Action"), action),
        price=price,
        quantity=int(quantity),
        price_type=getattr(ss.const("StockPriceType"), price_type),  # enum — "MKT" as a string is rejected silently
        order_type=getattr(ss.const("OrderType"), order_type),
        order_lot=getattr(ss.const("StockOrderLot"), lot),           # <1000 shares MUST be an odd lot
        order_cond=ss.const("StockOrderCond").Cash,
        account=account,
    )
    if tag:
        kw["custom_field"] = tag
    cls = getattr(sj, "StockOrder", None)
    return cls(**kw) if cls is not None else api.Order(**kw)


def _send_order(env, symbol, action, quantity, lot, price_type, price, order_type, tag,
                intent, fields):
    """Place ONE stock order and return its Trade — the chokepoint every order
    of this lib passes (tests/check_restart_stop_order_gate.py). The guards
    run before the broker session is even opened: after a machine restart, in
    a HALT (a user's close pass aside) or while the account guard holds the
    venue, nothing reaches SinoPac."""
    guard.check_restart_stop(intent, fields)
    guard.check_account_hold(VENUE, intent, fields)
    if intent == "entry" and guard.entry_blocked():
        guard.audit("order_denied_halt", **fields)
        raise guard.Halted(
            f"state/HALT is set ({guard.halt_info()}) — buy order for {symbol} refused "
            f"before reaching the broker. Trading is paused. Only the user may clear "
            f"the halt (guard.clear_halt).")
    ss.ensure_fresh(env)
    api, account = _get_api(env)
    contract = ss.stock_contract(api, symbol)
    if tag:
        _check_duplicate(env, api, account, symbol, tag)
    else:
        # no caller tag (a legacy call): still one to find the order by when the reply
        # is lost — 'x', never swept as the spot layer's own resting order
        tag = _tag(f"auto{time.time_ns()}", "X", prefix="x")
    order = _build_order(api, action, price, quantity, price_type, order_type, lot, tag, account)
    guard.audit("order_attempt", **{**fields, "tag": tag})
    ss.throttle("order")
    try:
        trade = api.place_order(contract, order)
    except Exception as e:
        presend = type(e).__name__ in _PRESEND_ERRORS
        found = None if presend else _find_by_tag(api, account, symbol, tag, TAG_LOOKUP_TRIES)
        if found is not None:
            logging.warning(f"[sinopac] {symbol}: place_order {type(e).__name__}, but the order "
                            f"is on the book (tag {tag}) — following it")
            trade = found
        else:
            guard.audit("order_error", error=f"{type(e).__name__}: {ss.scrub(e, env)[:200]}", **fields)
            if not presend:
                # the request may have reached the exchange: never read as "not placed"
                raise OrderNotConfirmed(f"{symbol}: place_order outcome unknown "
                                        f"({type(e).__name__}) — query the account before "
                                        f"resubmitting") from e
            raise
    ss.note_ok()
    return trade


# ── spot layer: the order ────────────────────────────────────────────────────

def _tick(price):
    """TWSE / TPEx stock tick size for a price. ETF ticks (0.01 / 0.05) divide
    these, so a price on this grid is valid for an ETF too."""
    p = Decimal(str(price))
    for bound, tick in ((10, "0.01"), (50, "0.05"), (100, "0.1"), (500, "0.5"), (1000, "1")):
        if p < bound:
            return Decimal(tick)
    return Decimal("5")


def protected_price(side, ref, limit_up=0.0, limit_down=0.0, slippage=DEFAULT_SLIPPAGE):
    """The limit price that stands in for a market order: ref ± slippage,
    rounded AWAY from the market onto the tick grid (up for a buy, down for a
    sell) and clamped to the day's limit-up / limit-down."""
    buy = side == "buy"
    rounding = ROUND_CEILING if buy else ROUND_FLOOR
    raw = Decimal(str(ref)) * (Decimal(1) + (Decimal(str(slippage)) if buy else -Decimal(str(slippage))))
    q = raw
    for _ in range(3):  # a value rounded across a band edge is re-snapped on that band's tick
        tick = _tick(q)
        snapped = (raw / tick).to_integral_value(rounding=rounding) * tick
        if _tick(snapped) == tick or snapped == q:
            q = snapped
            break
        q = snapped
    if buy and limit_up > 0:
        q = min(q, Decimal(str(limit_up)))
    if not buy and limit_down > 0:
        q = max(q, Decimal(str(limit_down)))
    return float(q)


def _slippage(env):
    raw = ss.env_get(env, "SINOPAC_MAX_SLIPPAGE") or os.environ.get("SINOPAC_MAX_SLIPPAGE", "")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SLIPPAGE
    return v if 0 < v <= 0.1 else DEFAULT_SLIPPAGE


def _session_open(env, now):
    """TWSE regular session at `now` (Taipei): 09:00–13:30 on a trading day —
    lib.paper_data's rule, the one lib.portfolio holds the keys by."""
    try:
        from lib.paper_data import tw_session_open
    except ImportError:
        mins = now.hour * 60 + now.minute
        return now.weekday() < 5 and 9 * 60 <= mins < 13 * 60 + 30
    return tw_session_open(env, now=now.timestamp())


def _at(now, hm):
    return now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def _tag(client_order_id, part, prefix="b"):
    """6-char custom_field for one leg: `prefix` + 5 base36 of the hash of
    (client_order_id, leg) — the same id and leg always give the same tag (a
    resubmit is refused as a duplicate), 60M values keep two of the day's
    orders apart when one is looked up by its tag, and 'b' marks the spot
    layer's orders (get_spot_open_orders sweeps those)."""
    h = int(hashlib.sha1(f"{client_order_id}|{part}".encode()).hexdigest(), 16)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    for _ in range(5):
        h, r = divmod(h, 36)
        s += digits[r]
    return prefix + s


def _settlement_amounts(rows):
    """|amount| of every pending settlement (T, T+1, T+2) on either Shioaji
    shape — both directions counted as owed: the sign convention is not
    documented, and counting a receivable as owed only buys less."""
    out = []
    for r in rows or []:
        if hasattr(r, "amount"):
            out.append(abs(float(getattr(r, "amount", 0) or 0)))
        else:
            for k in ("t_money", "t1_money", "t2_money"):
                out.append(abs(float(getattr(r, k, 0) or 0)))
    return out


def _day_buys(env):
    """TWD this process family bought today (Taipei date) on SinoPac in this
    mode — kept here because a broker's settlement rows may only show today's
    buys after the close; counted on top of them (twice at worst: safe)."""
    try:
        from lib.winreplace import load_json
        rec = load_json(DAY_BUYS_PATH, encoding="utf-8")
    except (OSError, ValueError):
        return 0.0
    if not isinstance(rec, dict) or rec.get("date") != ss.now_taipei().date().isoformat() \
            or rec.get("simulation") != _simulation(env):
        return 0.0
    return float(rec.get("twd") or 0)


def _add_day_buys(env, twd):
    from lib.winreplace import atomic_replace
    total = _day_buys(env) + float(twd)
    os.makedirs(os.path.dirname(DAY_BUYS_PATH), exist_ok=True)
    tmp = f"{DAY_BUYS_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"date": ss.now_taipei().date().isoformat(), "simulation": _simulation(env),
                   "twd": round(total, 2)}, f)
    atomic_replace(tmp, DAY_BUYS_PATH)


def _cash_cap(env, symbol, shares, price):
    """Shares a live buy may take: bank balance less every pending settlement,
    less what the bot bought today, fees and CASH_BUFFER, at the order's LIMIT
    price (the worst fill). Raises when not one share is affordable — never a
    buy the account cannot settle."""
    _, account = _read_api(env)
    cash = get_account_balance(env)
    pending = sum(_settlement_amounts(
        ss.read(env, lambda a: a.settlements(account), kind="account"))) + _day_buys(env)
    available = cash - pending - 2 * MIN_FEE_TWD
    per_share = price * (1 + FEE_RATE + CASH_BUFFER)
    affordable = int(math.floor(max(available, 0.0) / per_share)) if per_share > 0 else 0
    if affordable < 1:
        raise SinopacError(reject_token.tag(
            reject_token.INSUFFICIENT_MARGIN,
            f"{symbol}: 交割戶可用餘額不足 — 餘額 {cash:,.0f} TWD,未交割款 {pending:,.0f} TWD,"
            f"買 1 股要 {per_share:,.2f} TWD;請先入金或調低下單金額"))
    if shares > affordable:
        logging.warning(f"[sinopac] {symbol}: buy {shares} trimmed to {affordable} shares — "
                        f"settlement cash {available:,.0f} TWD after pending {pending:,.0f}")
        guard.audit("sinopac_cash_trim", symbol=symbol, wanted=shares, sent=affordable,
                    available=round(available, 2))
    return min(shares, affordable)


def _refuse_untradeable(symbol, info):
    if getattr(info, "trading_suspended", False):
        raise SinopacError(f"{symbol}: 暫停交易中 — not sent")
    prepay = getattr(info, "disposition_prepay_ratio", None)
    try:
        prepay = float(prepay or 0)
    except (TypeError, ValueError):
        prepay = 0.0
    if prepay > 0:
        raise SinopacError(f"{symbol}: 處置股,需預收款券({prepay:g}) — the bot does not "
                           f"pre-fund orders; trade it yourself or wait for the disposition to end")


def _settle_leg(env, trade, mult, wait_s):
    """Poll one leg until it is final; cancel the unfilled rest after `wait_s`
    seconds. Returns the normalized dict (+ 'unconfirmed' when the cancel
    itself never confirmed — the order may still fill)."""
    deadline = time.monotonic() + max(0.0, wait_s)
    cancel_at = None
    while True:
        trade = _refresh(env, trade)
        res = _normalize(trade, mult)
        done = res["status"] in _TERMINAL or (
            res["order_qty"] > 0 and res["filled_qty"] + res["cancel_qty"] >= res["order_qty"])
        if done:
            return res
        now = time.monotonic()
        if cancel_at is None and now >= deadline:
            try:
                api, _ = _read_api(env)   # this process's live session, not one a reset dropped
                ss.throttle("order")
                api.cancel_order(trade)
            except Exception as e:  # e.g. filled in between — the next poll tells
                logging.info(f"[sinopac] cancel {res['seqno']}: {type(e).__name__}")
            cancel_at = now
        elif cancel_at is not None and now - cancel_at >= CANCEL_WAIT_S:
            tp = ss.now_taipei()
            final = _at(tp, SESSION_FINAL)
            if tp >= final:
                # the session's last match is over: nothing more can fill, whatever the
                # exchange answers to a cancel after the close
                res["status"] = "Expired"
                return res
            if (final - tp).total_seconds() > POST_CLOSE_WAIT_S:
                res["unconfirmed"] = True
                return res
        time.sleep(POLL_S)


def _unknown_outcome(symbol, legs, why):
    """A leg we cannot see the end of: the bot's book is in doubt — trip HALT
    (only the user resumes). Returns the message; the caller raises it when no
    other leg has a confirmed fill to report."""
    msg = (f"{symbol}: SinoPac order outcome unknown ({why}) — trading paused (HALT) so the "
           f"bot's book is not traded on a guess; check the account's 委託/成交 in SinoPac's app, "
           f"then resume")
    logging.error(f"[sinopac] {msg}")
    try:
        guard.trip_halt(f"sinopac order unconfirmed: {symbol}", "order_sinopac")
    except Exception as e:
        logging.error(f"[sinopac] HALT trip failed: {e}")
    guard.audit("order_unconfirmed", symbol=symbol, venue=VENUE,
                legs=[{k: l.get(k) for k in ("lot", "seqno", "status", "filled_shares")}
                      for l in legs])
    return msg


def _run_leg(env, sym, action, qty, lot, mult, price, order_type, tag, intent, fields,
             wait_s):
    """Send one leg and follow it to its end. An exception AFTER the order left
    is not a failed order — it is one we lost sight of: reported 'unconfirmed'."""
    trade = _send_order(env, sym, action, qty, lot, "LMT", price, order_type, tag, intent,
                        fields)
    try:
        return {"lot": lot, **_settle_leg(env, trade, mult, wait_s)}
    except Exception as e:
        logging.error(f"[sinopac] {sym}: lost sight of order "
                      f"{getattr(trade.order, 'seqno', '?')} ({type(e).__name__}: {e})")
        return {"lot": lot, "seqno": str(getattr(trade.order, "seqno", "") or ""),
                "status": "Unknown", "filled_qty": 0.0, "filled_shares": 0.0,
                "avg_fill_price": 0.0, "msg": type(e).__name__, "unconfirmed": True}


def place_spot_market_order(env, symbol, side, base_qty=None, quote_qty=None,
                            client_order_id=None):
    """The spot layer's order (lib/venue_wiring, manager/flatten): buy sized in
    TWD (quote_qty) or shares (base_qty), sell in shares (base_qty). Sends
    board lots then the odd-lot remainder as price-protected limit orders and
    waits for the exchange; returns exchange-confirmed fills —
      {'executed_qty' (shares), 'avg_price', 'quote_qty' (TWD), 'status',
       'commission' (estimate, TWD), 'commission_asset': 'TWD', 'order_id', ...}
    False = below one share (one board lot in simulation) — nothing sent.
    Raises PaperMarketClosed outside the TWSE session, NoFill when nothing
    filled, SinopacError on a rejection, OrderNotConfirmed (+ HALT) when a
    leg's end cannot be seen."""
    sym = _norm_code(symbol)
    side = str(side).lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if side == "sell" and base_qty is None:
        raise ValueError("sells are sized in shares — pass base_qty")
    if side == "buy" and base_qty is None and quote_qty is None:
        raise ValueError("buys are sized in TWD (quote_qty) or shares (base_qty)")
    cid = str(client_order_id or f"sp{time.time_ns()}")
    sim = _simulation(env)
    intent = "entry" if side == "buy" else "reduce"
    fields = {"symbol": sym, "side": side, "market": "spot", "intent": intent,
              "venue": VENUE, "simulation": sim, "client_order_id": cid,
              **({"base_qty": float(base_qty)} if base_qty is not None else {}),
              **({"quote_qty": float(quote_qty)} if quote_qty is not None else {})}
    # before the broker session is even opened: after a machine restart / in a HALT
    # / under an account hold no order goes out
    guard.check_restart_stop(intent, fields)
    guard.check_account_hold(VENUE, intent, fields)
    if intent == "entry" and guard.entry_blocked():
        guard.audit("order_denied_halt", **fields)
        raise guard.Halted(f"state/HALT is set ({guard.halt_info()}) — {sym} buy refused. "
                           f"Only the user may clear the halt.")
    with _exec_lock:   # the session is judged once the lock is ours (another execution may run long)
        if not _session_open(env, ss.now_taipei()):
            raise PaperMarketClosed(f"{sym}: 台股休市中(交易時段 09:00–13:30)— SinoPac order "
                                    f"not sent outside the TWSE session")
        return _execute_spot(env, sym, side, base_qty, quote_qty, cid, sim, intent, fields)


def _execute_spot(env, sym, side, base_qty, quote_qty, cid, sim, intent, fields):
    """place_spot_market_order's body, under _exec_lock: quote, size, cash
    check, the board-lot leg, the odd-lot leg, the result."""
    now = ss.now_taipei()
    q = _quote(env, sym)
    _refuse_untradeable(sym, q["info"])
    ref = (q["ask"] if side == "buy" else q["bid"]) or q["last"] or q["reference"]
    if not ref > 0:
        raise SinopacError(f"{sym}: no price from SinoPac — not sent")
    price = protected_price(side, ref, q["limit_up"], q["limit_down"], _slippage(env))
    if base_qty is not None:
        shares = int(math.floor(float(base_qty) + 1e-9))
    else:
        shares = int(math.floor(float(quote_qty) / ref + 1e-9))
    if sim:
        shares -= shares % BOARD_LOT   # simulation takes no odd lots
    if shares < 1:
        logging.info(f"[sinopac] {sym} {side}: under one {'lot' if sim else 'share'} — skipped")
        return False
    if side == "buy" and not sim:
        shares = _cash_cap(env, sym, shares, price)
    lots, odd = divmod(shares, BOARD_LOT)
    action = "Buy" if side == "buy" else "Sell"
    legs, errors, lost = [], [], None

    if lots:
        in_auction = _at(now, _CLOSE_AUCTION) <= now < _at(now, _CLOSE)
        order_type = "ROD" if in_auction else "IOC"
        # the closing auction prints at 13:30 — wait for it, then cancel what is left
        wait_s = ((_at(now, _CLOSE) - now).total_seconds() + AUCTION_GRACE_S if in_auction
                  else IOC_WAIT_S)
        leg_fields = {**fields, "lot": "Common", "lots": lots, "price": price,
                      "order_type": order_type}
        try:
            legs.append(_run_leg(env, sym, action, lots, "Common", BOARD_LOT, price, order_type,
                                 _tag(cid, "L"), intent, leg_fields, wait_s))
        except guard.Halted:
            raise
        except OrderNotConfirmed as e:
            lost = e
        except Exception as e:
            errors.append(e)
    now = ss.now_taipei()   # the board-lot leg may have taken its time
    if odd and (lost is not None or any(l.get("unconfirmed") for l in legs)):
        pass  # never a new order while an earlier leg's outcome is unknown (HALT below)
    elif odd and now >= _at(now, _CLOSE):
        errors.append(PaperMarketClosed(f"{sym}: the session closed before the odd-lot leg — "
                                        f"{odd} shares not sent"))
    elif odd:
        # no odd-lot match before 09:10: an order sent earlier waits for it
        first = max(0.0, (_at(now, _ODD_FIRST_MATCH) - now).total_seconds())
        last = (_at(now, _CLOSE) - now).total_seconds() + AUCTION_GRACE_S
        wait_s = min(first + ODD_WAIT_S, last)
        leg_fields = {**fields, "lot": "IntradayOdd", "shares": odd, "price": price,
                      "order_type": "ROD"}
        try:
            legs.append(_run_leg(env, sym, action, odd, "IntradayOdd", 1, price, "ROD",
                                 _tag(cid, "O"), intent, leg_fields, wait_s))
        except guard.Halted:
            if not legs:
                raise
            errors.append(guard.Halted("trading paused before the odd-lot leg was sent"))
        except OrderNotConfirmed as e:
            lost = e
        except Exception as e:
            errors.append(e)

    unconfirmed = [l for l in legs if l.get("unconfirmed")]
    filled = sum(l["filled_shares"] for l in legs)
    if unconfirmed or lost is not None:
        why = (f"cancel of {', '.join(l['seqno'] for l in unconfirmed)} not confirmed"
               if unconfirmed else str(lost))
        msg = _unknown_outcome(sym, legs, why)
        if filled <= 0:
            raise OrderNotConfirmed(msg)
        errors.append(OrderNotConfirmed(msg))
    for l in legs:
        if l["status"] == "Failed" and not l["filled_shares"]:
            errors.append(SinopacError(
                f"order {l['seqno']} Failed: {l['msg'] or '(no msg from broker)'}"))
    notional = sum(l["filled_shares"] * l["avg_fill_price"] for l in legs)
    if filled <= 0:
        guard.audit("order_error", error="; ".join(str(e)[:120] for e in errors) or "no fill",
                    **fields)
        if errors:
            raise errors[0]
        raise NoFill(f"{sym}: {side} {shares} 股未成交(價格保護 {price:g} TWD 內沒有成交)— "
                     f"nothing changed; the next round tries again")
    avg = notional / filled
    status = "filled" if filled >= shares else "partially_filled"
    if side == "buy":
        try:
            _add_day_buys(env, notional * (1 + FEE_RATE))
        except OSError as e:  # never loses the fill; the next cash check may then count less
            logging.error(f"[sinopac] {sym}: today's buy total not recorded ({e})")
    guard.audit("order_ok", status=status, executed_qty=filled, avg_price=round(avg, 4),
                order_id=",".join(l["seqno"] for l in legs), **fields)
    for e in errors:
        logging.error(f"[sinopac] {sym}: a leg failed after a fill — {e}")
    logging.info(f"[sinopac] {side} {sym} {filled:g}/{shares} shares avg {avg:.2f} "
                 f"(limit {price:g}, simulation={sim})")
    return {
        "order_id": ",".join(l["seqno"] for l in legs),
        "status": status,
        "avg_price": avg,
        "orig_qty": float(shares),
        "executed_qty": float(filled),
        "quote_qty": round(notional, 2),
        # the fee is paid in TWD cash, never out of the shares — lib/venue_wiring
        # books the whole executed_qty (spot_book_qty)
        "commission": round(notional * FEE_RATE, 2),
        "commission_asset": "TWD",
        "commission_estimated": True,
        "client_order_id": cid,
        "exchange": VENUE,
        "simulation": sim,
        "price_limit": price,
        "legs": legs,
        **({"errors": [str(e)[:200] for e in errors]} if errors else {}),
    }


def get_spot_open_orders(env):
    """The bot's own resting orders (custom_field 'b…'), in the shape
    lib/venue_wiring.sweep_orphan_orders cancels at reconciler start: a crash
    between an odd-lot order and its cancel leaves one on the book."""
    api, account = _read_api(env)
    ss.throttle("order")
    api.update_status(account)
    rows = []
    for t in api.list_trades() or []:
        tag = str(getattr(t.order, "custom_field", "") or "")
        status = ss.enum_value(t.status.status)
        if not tag.startswith("b") or status in _TERMINAL:
            continue
        oid = str(getattr(t.order, "id", "") or getattr(t.order, "seqno", ""))
        digits = str(int(hashlib.sha1(oid.encode()).hexdigest(), 16))[:14]
        rows.append({"symbol": _norm_code(getattr(t.contract, "code", "")), "order_id": oid,
                     "client_order_id": f"rc{digits}", "status": status, "tag": tag})
    return rows


def cancel_spot_order(env, symbol, order_id):
    """Cancel one of today's orders by its id / seqno; already gone → no-op.
    Through the same gate as every order, before the broker session: a cancel
    still goes out under HALT and the restart stop, but from an agent turn it
    takes the turn order lock (lib/guard TURN_MONEY_LOCK) — another conversation
    placing orders → TurnMoneyBusy, nothing cancelled."""
    guard.check_restart_stop("cancel", {"symbol": symbol, "order_id": str(order_id), "intent": "cancel"})
    api, account = _read_api(env)
    ss.throttle("order")
    api.update_status(account)
    for t in api.list_trades() or []:
        if str(order_id) in (str(getattr(t.order, "id", "")), str(getattr(t.order, "seqno", ""))):
            if ss.enum_value(t.status.status) in _TERMINAL:
                return False
            ss.throttle("order")
            api.cancel_order(t)
            guard.audit("order_cancel", symbol=_norm_code(symbol), order_id=str(order_id),
                        venue=VENUE)
            return True
    return False


def simulation_api_test(env, code="2890"):
    """SinoPac's API-permission test (條款簽署與測試): in the SIMULATION
    environment — SINOPAC_LIVE is ignored here — one board-lot limit buy at
    the day's limit-down (far from the market), acknowledged, then cancelled.
    Returns the normalized status + 'cancelled'. Weekdays 08:00–20:00 only."""
    env = {k: v for k, v in (env or {}).items() if str(k).upper() != "SINOPAC_LIVE"}
    code = _norm_code(code)
    q = _quote(env, code)
    ref = q["reference"] or q["last"]
    if not ref > 0:
        raise SinopacError(f"{code}: no reference price — try again in the test window")
    price = q["limit_down"] or protected_price("sell", ref, slippage=0.05)
    fields = {"symbol": code, "side": "buy", "intent": "entry", "venue": VENUE,
              "simulation": True, "purpose": "sinopac_api_test", "price": price}
    trade = _send_order(env, code, "Buy", 1, "Common", "LMT", price, "ROD", None, "entry",
                        fields)
    res = _normalize(trade, BOARD_LOT)
    deadline = time.monotonic() + IOC_WAIT_S
    while res["status"] == "PendingSubmit" and time.monotonic() < deadline:
        time.sleep(POLL_S)
        trade = _refresh(env, trade)
        res = _normalize(trade, BOARD_LOT)
    if res["status"] == "Failed":
        raise SinopacError(f"API test order Failed: {res['msg'] or '(no msg from broker)'}")
    cancelled = res["status"] in ("Cancelled",)
    if res["status"] not in _TERMINAL:
        api, _ = _read_api(env)
        try:
            ss.throttle("order")
            api.cancel_order(trade)
            cancelled = True
        except Exception as e:
            logging.warning(f"[sinopac] API test cancel: {type(e).__name__}")
    guard.audit("order_ok", status=res["status"], seqno=res["seqno"], cancelled=cancelled,
                **fields)
    return {**res, "cancelled": cancelled}


# ── swap layer: not a SinoPac product ────────────────────────────────────────

_SPOT_ONLY = ("SinoPac trades Taiwan stocks as cash shares (spot) only — a swap/futures "
              "order path does not exist here; declare MARKET = \"spot\" in the strategy")


def get_mark_price(env, symbol):
    raise SinopacError(_SPOT_ONLY)


def get_contract_rules(env, symbol):
    raise SinopacError(_SPOT_ONLY)


def format_qty(env, symbol, qty, price=None):
    raise SinopacError(_SPOT_ONLY)


def place_market_order(env, symbol, direction, qty, client_order_id=None, reduce_only=False):
    raise SinopacError(_SPOT_ONLY)


def close_position_partial(env, symbol, side, qty, client_order_id=None):
    raise SinopacError(_SPOT_ONLY)


# ── legacy Type-B helpers ────────────────────────────────────────────────────

def place_odd_lot_order(env, symbol, action, shares, client_tag=None, confirm_timeout=90):
    """One odd-lot (零股, after-hours session) market order, CONFIRMED.
    action: 'buy'|'sell', 1 ≤ shares ≤ 999. Returns confirm_order()'s
    normalized dict.

    client_tag: ≤6 alphanumeric chars, unique per intent (e.g. 'twm107' =
    strategy initials + day-of-year) — the same tag resubmitted the same day
    is refused locally (DuplicateOrder) instead of doubling the position."""
    if action not in ("buy", "sell"):
        raise ValueError(f"action must be 'buy' or 'sell', got {action!r}")
    shares = int(shares)
    if not 1 <= shares <= MAX_ODD_LOT_SHARES:
        raise ValueError(f"odd-lot order must be 1-{MAX_ODD_LOT_SHARES} shares, got {shares}")
    if client_tag is not None and not re.fullmatch(r"[A-Za-z0-9]{1,6}", client_tag):
        raise ValueError(f"client_tag must be 1-6 alphanumeric chars, got {client_tag!r}")
    symbol = _norm_code(symbol)
    intent = "entry" if action == "buy" else "reduce"
    fields = {
        "symbol": symbol, "action": action, "shares": shares,
        "lot": "Odd", "price_type": "MKT", "intent": intent, "venue": VENUE,
        "simulation": _simulation(env),
        **({"client_tag": client_tag} if client_tag else {}),
    }
    # before the broker session is even opened: after a machine restart no order goes out
    guard.check_restart_stop(intent, {"symbol": symbol, "action": action, "shares": shares})

    trade = _send_order(env, symbol, "Buy" if action == "buy" else "Sell", shares, "Odd",
                        "MKT", 0, "ROD", client_tag, intent, fields)
    try:
        result = confirm_order(env, trade, timeout=confirm_timeout)
    except Exception as e:
        guard.audit("order_error", error=str(e), **fields)
        raise
    guard.audit("order_ok", seqno=result["seqno"], status=result["status"],
                filled_qty=result["filled_qty"], **fields)
    logging.info(
        f"sinopac {action} {symbol} {shares} shares → {result['status']} "
        f"filled={result['filled_qty']} avg={result['avg_fill_price']:.2f}"
    )
    return result


def place_order_sinopac(env, symbol, signed_diff, client_tag=None, confirm_timeout=90):
    """Legacy Type-B entry point (the reconciler now trades through the spot
    layer above). signed_diff is in TWD (>0 buy, <0 sell);
    shares = floor(|signed_diff| / last price), split into ≤999-share odd-lot
    orders. Returns a summary dict {'orders': [...], 'filled_qty', 'target_qty'},
    or False if the diff is below one share (skip, matching lib conventions).
    Chunk tags derive from client_tag: 'twm7' → 'twm7', 'twm7a', 'twm7b'…"""
    symbol = _norm_code(symbol)
    price = _last_price(env, symbol)
    if price <= 0:
        raise SinopacError(f"no valid last price for {symbol}")

    target_qty = int(abs(signed_diff) / price)
    if target_qty < 1:
        logging.info(
            f"sinopac skip {symbol}: diff {abs(signed_diff):.0f} TWD < 1 share @ {price:.2f}"
        )
        return False

    action = "buy" if signed_diff > 0 else "sell"
    results = []
    remaining = target_qty
    chunk_i = 0
    while remaining > 0:
        shares = min(remaining, MAX_ODD_LOT_SHARES)
        tag = None
        if client_tag:
            tag = client_tag if chunk_i == 0 else f"{client_tag[:5]}{chr(ord('a') + chunk_i - 1)}"
        results.append(
            place_odd_lot_order(env, symbol, action, shares,
                                client_tag=tag, confirm_timeout=confirm_timeout)
        )
        remaining -= shares
        chunk_i += 1

    return {
        "symbol": symbol,
        "action": action,
        "target_qty": target_qty,
        "filled_qty": sum(r["filled_qty"] for r in results),
        "orders": results,
    }
