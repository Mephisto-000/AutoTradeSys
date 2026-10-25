# AutoTradeSys fork addition (2026-10-25): SinoPac account reader for the 自動下單 page.
# Licensed under the Apache License, Version 2.0 (same as the upstream Blave Agent).
"""
SinoPac (永豐金) stock-account reader — the lib/account_TEMPLATE.py contract the
platform's readers discover by filename (runtime/account_reader.py, flatten,
the reconciler's account guard and error classifier).

TW stocks trade as SPOT inventory here (lib/order_sinopac.py spot layer, the
paper venue's TW-stock model): get_positions() is [] — there is no derivative
position — and the cash shares are listed by get_holdings() and valued in
get_equity(). The reconciler reads its own inventory through
order_sinopac.get_spot_balances, never through this file.

Snapshot, not a login per read (why): the desktop account reader runs every
minute in a FRESH process; SinoPac allows 1,000 logins a day and 5 connections
per person. So every read here comes from state/sinopac_account.json:
  - the reconciler refreshes it whenever it reads holdings (its session is
    already logged in — order_sinopac.get_spot_balances → refresh_if_stale);
  - a read finding it older than its TTL (5 min in the trading day, 30 min
    otherwise; SINOPAC_ACCOUNT_TTL_S overrides) refreshes it here: one login,
    three reads, logout at process exit.
A snapshot written under other credentials (a rebind) or in the other mode
(simulation vs SINOPAC_LIVE=true) is never served. A failed refresh is
remembered (state/sinopac_account_fail.json): the next one waits out the
same TTL, so a broken read cannot spend a login every minute.

The account id carries the mode ("sim:" in simulation): switching
SINOPAC_LIVE reads as another account to lib.portfolio.book_account_check,
which restarts the bot's SinoPac book — a book bought in simulation is never
sold out of the real account, nor the real one forgotten into simulation.

Equity = settlement-account cash + pending settlements due AFTER today + the
cash shares at their last price. Shioaji does not document the sign of a
settlement amount; the broker convention (negative = payable, a buy) is used
for this DISPLAY number only — lib/order_sinopac's pre-buy cash check counts
every pending settlement as owed, whatever its sign.
"""
import json
import logging
import math
import os
import time

from lib import sinopac_session as ss
from lib import venue_errors
from lib.winreplace import atomic_replace, load_json

SNAPSHOT_PATH = "state/sinopac_account.json"
FAIL_PATH = "state/sinopac_account_fail.json"
TTL_SESSION_S = 300
TTL_OFF_S = 1800
REFRESH_MIN_S = 60      # the reconciler's own refresh: at most once a minute
STALE_SERVE_X = 3       # a failed refresh may still serve a snapshot this many TTLs old


# ── reads ────────────────────────────────────────────────────────────────────

def stock_rows(env, api=None):
    """Cash (現股) long rows of the stock account, in SHARES — margin and short
    rows are not spot inventory (they close with other order conditions)."""
    api = api or ss.get_api(env)
    account = ss.stock_account(api)
    unit = ss.const("Unit").Share
    rows = ss.read(env, lambda a: a.list_positions(account, unit=unit), kind="account") or []
    out = []
    for p in rows:
        code = str(getattr(p, "code", "") or "").strip().upper()
        qty = _num(getattr(p, "quantity", 0))
        direction = ss.enum_value(getattr(p, "direction", "Buy"))
        cond = ss.enum_value(getattr(p, "cond", "Cash") or "Cash")
        if not code or qty <= 0 or direction != "Buy" or cond != "Cash":
            continue
        out.append({"code": code, "quantity": qty,
                    "price": _num(getattr(p, "price", 0)),
                    "last_price": _num(getattr(p, "last_price", 0)),
                    "pnl": _num(getattr(p, "pnl", 0), allow_negative=True)})
    return out


def _num(v, allow_negative=False):
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f) or (f < 0 and not allow_negative):
        return 0.0
    return f


def _settlements(env, api, account):
    rows = ss.read(env, lambda a: a.settlements(account), kind="account") or []
    out = []
    for r in rows:
        if hasattr(r, "amount"):
            out.append({"date": str(getattr(r, "date", "") or ""),
                        "T": int(getattr(r, "T", 0) or 0),
                        "amount": _num(getattr(r, "amount", 0), allow_negative=True)})
        else:  # the pre-V1 shape: one row with three money fields
            for t, k in ((0, "t_money"), (1, "t1_money"), (2, "t2_money")):
                out.append({"date": str(getattr(r, k.replace("money", "day"), "") or ""),
                            "T": t, "amount": _num(getattr(r, k, 0), allow_negative=True)})
    return out


def refresh(env, positions=None):
    """Read the account now and write the snapshot. `positions` = stock_rows()
    the caller already has (the reconciler's holdings read), else read here."""
    api = ss.get_api(env)
    account = ss.stock_account(api)
    snap = {"read_at": int(time.time()), "simulation": not ss.is_live(env),
            "key_fp": ss.key_fingerprint(env), "account_id": ss.account_id(api),
            "cash": None, "settlements": [], "errors": {}}
    snap["positions"] = positions if positions is not None else stock_rows(env, api)
    try:
        bal = ss.read(env, lambda a: a.account_balance(account), kind="account")
        row = bal[0] if isinstance(bal, (list, tuple)) else bal
        err = str(getattr(row, "errmsg", "") or "")
        if err:
            raise ss.SinopacError(err)
        snap["cash"] = _num(getattr(row, "acc_balance", 0), allow_negative=True)
    except Exception as e:
        if not snap["simulation"]:
            raise
        # simulation has no bank balance (Shioaji 模擬模式) — equity is the holdings alone
        snap["errors"]["cash"] = f"{type(e).__name__}"
    try:
        snap["settlements"] = _settlements(env, api, account)
    except Exception as e:
        if not snap["simulation"]:
            raise
        snap["errors"]["settlements"] = f"{type(e).__name__}"
    _write(snap)
    return snap


def _write(snap):
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    tmp = f"{SNAPSHOT_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    atomic_replace(tmp, SNAPSHOT_PATH)


def _load():
    """The snapshot, or None (absent / unreadable → refreshed). Read through
    lib.winreplace: on Windows a read can meet the reconciler's replace."""
    try:
        snap = load_json(SNAPSHOT_PATH, encoding="utf-8")
        return snap if isinstance(snap, dict) else None
    except (OSError, ValueError):
        return None


def _ttl(env):
    raw = ss.env_get(env, "SINOPAC_ACCOUNT_TTL_S") or os.environ.get("SINOPAC_ACCOUNT_TTL_S", "")
    try:
        return max(60, int(float(raw)))
    except (TypeError, ValueError):
        pass
    now = ss.now_taipei()
    mins = now.hour * 60 + now.minute
    return TTL_SESSION_S if now.weekday() < 5 and 8 * 60 + 30 <= mins < 14 * 60 + 30 else TTL_OFF_S


def _usable(snap, env):
    return (snap is not None and snap.get("key_fp") == ss.key_fingerprint(env)
            and snap.get("simulation") == (not ss.is_live(env)))


class ReadBackoff(ss.SinopacError):
    """A refresh not attempted: the last one failed less than a TTL ago. Carries
    that failure's classification (classify) — a broken key stays a credential
    problem for the reconciler, a dead line a transient one."""

    def __init__(self, msg, kind=None):
        super().__init__(msg)
        self.kind = kind


def _last_failure(env):
    """(epoch, message, kind) of the last failed refresh under these
    credentials and mode, or None."""
    try:
        rec = load_json(FAIL_PATH, encoding="utf-8")
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("key_fp") != ss.key_fingerprint(env) \
            or rec.get("simulation") != (not ss.is_live(env)):
        return None
    return float(rec.get("at") or 0), str(rec.get("error") or ""), rec.get("kind")


def _note_failure(env, e):
    try:
        os.makedirs(os.path.dirname(FAIL_PATH), exist_ok=True)
        tmp = f"{FAIL_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": time.time(), "key_fp": ss.key_fingerprint(env),
                       "simulation": not ss.is_live(env), "kind": classify(e),
                       "error": f"{type(e).__name__}: {ss.scrub(e, env)[:200]}"}, f,
                      ensure_ascii=False)
        atomic_replace(tmp, FAIL_PATH)
    except OSError as we:
        logging.warning(f"[sinopac] failure marker not written ({we})")


def _clear_failure():
    try:
        os.remove(FAIL_PATH)
    except FileNotFoundError:
        pass
    except OSError as e:
        logging.warning(f"[sinopac] failure marker not removed ({e})")


def snapshot(env):
    """The account snapshot, refreshed when older than its TTL. A failed
    refresh serves a snapshot up to STALE_SERVE_X TTLs old (a blink must not
    blank the page) and raises past that; after a failure the next refresh
    waits one TTL (no login per reader run while the read stays broken)."""
    snap = _load()
    ttl = _ttl(env)
    age = time.time() - float((snap or {}).get("read_at") or 0)
    if _usable(snap, env) and age < ttl:
        return snap
    failed = _last_failure(env)
    if failed is not None and time.time() - failed[0] < ttl:
        if _usable(snap, env) and age < ttl * STALE_SERVE_X:
            return snap
        raise ReadBackoff(f"SinoPac account read failed {time.time() - failed[0]:.0f}s ago "
                          f"({failed[1]}) — next try after {ttl}s", kind=failed[2])
    try:
        snap_new = refresh(env)
    except Exception as e:
        _note_failure(env, e)
        if _usable(snap, env) and age < ttl * STALE_SERVE_X:
            logging.warning(f"[sinopac] account refresh failed ({type(e).__name__}) — serving the "
                            f"{age:.0f}s-old snapshot")
            return snap
        raise
    if failed is not None:
        _clear_failure()
    return snap_new


def refresh_if_stale(env, positions=None):
    """The reconciler's hook (order_sinopac.get_spot_balances): rewrite the
    snapshot from its already-open session at most once a minute."""
    snap = _load()
    if _usable(snap, env) and time.time() - float(snap.get("read_at") or 0) < REFRESH_MIN_S:
        return snap
    return refresh(env, positions=positions)


# ── the platform contract ────────────────────────────────────────────────────

def _today():
    return ss.now_taipei().date().isoformat()


def get_equity(env: dict) -> dict:
    """{'equity': TWD, 'currency': 'TWD'} — settlement cash + settlements due
    after today (broker sign: negative = payable) + cash shares at last price."""
    snap = snapshot(env)
    today = _today()
    unsettled = sum(float(s.get("amount") or 0) for s in snap.get("settlements") or []
                    if str(s.get("date") or "")[:10] > today)
    stocks = sum(float(p["quantity"]) * float(p.get("last_price") or p.get("price") or 0)
                 for p in snap.get("positions") or [])
    cash = float(snap.get("cash") or 0)
    return {"equity": round(cash + unsettled + stocks, 2), "currency": "TWD"}


def get_positions(env: dict) -> list:
    """[] — TW stocks are spot inventory on SinoPac (get_holdings lists them);
    there is no swap / futures position on a stock account."""
    return []


def get_holdings(env: dict) -> list:
    """Display-only: every cash-share holding of the account (the bot's and the
    user's alike — the bot's own share is its book) + the settlement cash.
    `usdt_value` carries TWD here: the account's currency is TWD."""
    snap = snapshot(env)
    rows = []
    for p in snap.get("positions") or []:
        px = float(p.get("last_price") or p.get("price") or 0)
        rows.append({"asset": p["code"], "amount": float(p["quantity"]),
                     "usdt_value": round(float(p["quantity"]) * px, 2) if px else None,
                     "wallet": "stock"})
    if snap.get("cash") is not None:
        rows.append({"asset": "TWD", "amount": float(snap["cash"]),
                     "usdt_value": float(snap["cash"]), "wallet": "cash"})
    rows.sort(key=lambda r: -(r["usdt_value"] or 0))
    return rows


def get_account_id(env: dict) -> str:
    """'<broker>-<account>' of the stock account these keys open — 'sim:'
    in front in simulation: the two modes are two books (module docstring)."""
    snap = snapshot(env)
    if not snap.get("account_id"):
        raise ss.SinopacError("no stock account id in the SinoPac snapshot")
    return ("sim:" if snap.get("simulation") else "") + str(snap["account_id"])


_TRANSIENT_NAMES = {"ShioajiConnectionError", "ShioajiTimeoutError", "TokenError",
                    "MarketDataQueryTimeoutError", "MarketDataQueryUnavailableError",
                    "SystemMaintenance", "ServerError", "ResponseRecvError"}
_CREDENTIAL_NAMES = {"AuthError", "CaError", "CaExpiredError", "CaPasswordError",
                     "AccountNotSignError", "ShioajiPermissionError"}


def classify(exc):
    """TRANSIENT / CREDENTIAL / None (→ lib.venue_errors floor) for a failed read.
    Walks the cause chain: lib/sinopac_session wraps Shioaji's login error."""
    if isinstance(exc, ReadBackoff):
        return exc.kind
    seen = 0
    e = exc
    while e is not None and seen < 5:
        name = type(e).__name__
        if name in _TRANSIENT_NAMES or isinstance(e, (ConnectionError, TimeoutError)):
            return venue_errors.TRANSIENT
        if name in _CREDENTIAL_NAMES:
            return venue_errors.CREDENTIAL
        msg = str(e)
        if isinstance(e, ss.SinopacError) and ("未安裝" in msg or "missing from .env" in msg
                                               or "look truncated" in msg or "CA " in msg):
            return venue_errors.CREDENTIAL   # only a human fixes setup
        e = e.__cause__ or e.__context__
        seen += 1
    return None
