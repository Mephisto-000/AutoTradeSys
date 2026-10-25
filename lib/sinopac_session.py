# AutoTradeSys fork addition (2026-10-25): shared Shioaji session for the SinoPac libs.
# Licensed under the Apache License, Version 2.0 (same as the upstream Blave Agent).
"""
SinoPac (永豐金證券) Shioaji session — ONE login per process, shared by
lib/order_sinopac.py (orders), lib/account_sinopac.py (equity / holdings) and
lib/sinopac_data.py (historical K bars for backtests).

Why one module owns the login (references/sinopac-broker.md › Limits):
  - SinoPac allows 5 connections per person and 1,000 api.login() calls per
    day; a process that logs in per call (the desktop account reader runs
    every minute in a fresh process) would exhaust both.
  - Shioaji's API moved under the old code: 1.7 dropped login(fetch_contract=),
    looks contracts up with api.contracts.get(), and its enums print as
    "OrderStatus.Filled" (compare .value, never str()). Every version quirk is
    absorbed here, so the libs above read one interface on 1.5 and 1.7 alike.

Credentials (.env, written by manager/sinopac_setup.py — never by hand-copied
code): sinopac_api_key, sinopac_secret_key; for real orders also
SINOPAC_LIVE=true, sinopac_ca_path, sinopac_ca_passwd, optional
sinopac_person_id. Names are matched case-insensitively. Without
SINOPAC_LIVE=true every session is a SIMULATION session against SinoPac's fake
account (lesson 1 in the reference).

Never logs or raises a credential value: messages carry the exception class and
a message scrubbed of every .env value (scrub()).
"""
import atexit
import collections
import inspect
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

VENUE = "sinopac"
TAIPEI = timezone(timedelta(hours=8))

# Process-local throttles under SinoPac's published limits (使用限制): market
# data 50 / 10 s (snapshots, kbars, ticks), accounting 25 / 5 s (balances,
# positions, settlements), orders 250 / 10 s (place / cancel / update_status).
# Kept below them: a breach suspends the service for a minute.
_LIMITS = {"market": (40, 10.0), "account": (20, 5.0), "order": (200, 10.0)}
# A session unused this long is probed before an order goes out through it:
# a laptop that slept keeps a dead connection object (same reason as the
# reconciler's WAKE_GAP_S for 群益).
IDLE_PROBE_S = 600
# Real SinoPac keys are long random strings; anything this short is a typo or
# a placeholder, and logging in with it only burns one of the day's 1,000 logins.
MIN_KEY_LEN = 16
# named in messages only — this module never runs it (a constant keeps the path out of
# the call arguments tests/check_sched_bash_guard.py reads as "launches a script")
SETUP_CLI = "manager/sinopac_setup.py"


class SinopacError(Exception):
    """A SinoPac failure the caller should surface as is (no secrets inside)."""


_lock = threading.RLock()
_api = None
_live = None
_key_fp = None
_ca_ok = False
_last_ok = 0.0
_rl_lock = threading.Lock()
_calls = {}
_atexit_armed = False


# ── shioaji import + version shims ───────────────────────────────────────────

def shioaji():
    """The shioaji module, or a SinopacError that says how to install it."""
    if "shioaji" not in sys.modules and not os.environ.get("SJ_LOG_PATH"):
        # the SDK opens shioaji.log in the working directory on import — the workspace root;
        # keep it with the machine's other state instead
        try:
            os.makedirs("state", exist_ok=True)
            os.environ["SJ_LOG_PATH"] = os.path.abspath(os.path.join("state", "shioaji.log"))
        except OSError as e:
            logging.info(f"[sinopac] shioaji log stays in the working directory ({e})")
    try:
        import shioaji as sj
    except ImportError as e:
        raise SinopacError(
            "shioaji 未安裝 — 電腦版請執行 ~/Blave/venv/bin/python -m pip install shioaji "
            "(Blave 的引擎刻意不預裝它,只有綁永豐的人需要)") from e
    return sj


def const(name):
    """A Shioaji enum class by name: top level on 1.5+, sj.constant before."""
    sj = shioaji()
    c = getattr(sj, name, None)
    if c is None:
        c = getattr(getattr(sj, "constant", None), name, None)
    if c is None:
        raise SinopacError(f"shioaji {getattr(sj, '__version__', '?')} has no {name}")
    return c


def enum_value(x):
    """'Filled' for OrderStatus.Filled on every version: 1.7's native enums
    str() as 'OrderStatus.Filled' and compare equal to 'Filled' only through
    .value; 1.5's str-Enums carry .value too."""
    v = getattr(x, "value", x)
    s = "" if v is None else str(v)
    head, _, tail = s.rpartition(".")
    return tail if head and head[:1].isalpha() and tail[:1].isalpha() else s


def _params(fn):
    try:
        return inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}


# ── .env access ──────────────────────────────────────────────────────────────

def env_get(env, name, default=""):
    """Case-insensitive .env lookup (the onboarding doc writes lowercase
    sinopac_api_key; a hand-edited file may not)."""
    env = env or {}
    if name in env:
        return env.get(name) or default
    want = name.lower()
    for k, v in env.items():
        if str(k).lower() == want:
            return v or default
    return default


def is_live(env):
    """Real orders only with SINOPAC_LIVE=true — anything else is simulation."""
    return str(env_get(env, "SINOPAC_LIVE")).strip().lower() == "true"


def credentials(env):
    api_key = str(env_get(env, "sinopac_api_key")).strip()
    secret = str(env_get(env, "sinopac_secret_key")).strip()
    if not api_key or not secret:
        raise SinopacError("sinopac_api_key / sinopac_secret_key missing from .env — "
                           f"run {SETUP_CLI} bind")
    if len(api_key) < MIN_KEY_LEN or len(secret) < MIN_KEY_LEN:
        raise SinopacError("sinopac_api_key / sinopac_secret_key look truncated (too short) — "
                           f"not logging in with them; re-run {SETUP_CLI} bind")
    return api_key, secret


def scrub(msg, env):
    """msg without any .env value of 6+ characters in it."""
    out = str(msg)
    for v in sorted((str(v) for v in (env or {}).values() if v), key=len, reverse=True):
        if len(v) >= 6 and v in out:
            out = out.replace(v, "***")
    return out


def key_fingerprint(env):
    import hashlib
    h = hashlib.sha256()
    for name in ("sinopac_api_key", "sinopac_secret_key", "sinopac_ca_path"):
        h.update(f"{name}={env_get(env, name)}\n".encode())
    return h.hexdigest()


# ── throttling ───────────────────────────────────────────────────────────────

def throttle(kind):
    """Block until one more call of `kind` fits SinoPac's per-window limit."""
    limit, window = _LIMITS[kind]
    while True:
        with _rl_lock:
            q = _calls.setdefault(kind, collections.deque())
            now = time.monotonic()
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) < limit:
                q.append(now)
                return
            wait = window - (now - q[0]) + 0.05
        time.sleep(max(wait, 0.05))


# ── the session ──────────────────────────────────────────────────────────────

def _logout_quietly(api):
    try:
        api.logout()
    except Exception as e:  # leaving anyway: a failed logout only ages out server-side
        logging.info(f"[sinopac] logout: {type(e).__name__}")


def _at_exit():
    with _lock:
        if _api is not None:
            _logout_quietly(_api)


def reset():
    """Drop the session (logout); the next get_api() logs in again — after
    SINOPAC_LIVE or the keys change, or a connection error."""
    global _api, _live, _key_fp, _ca_ok
    with _lock:
        if _api is not None:
            _logout_quietly(_api)
        _api, _live, _key_fp, _ca_ok = None, None, None, False


def _login(env, live):
    global _api, _live, _key_fp, _ca_ok, _atexit_armed
    api_key, secret = credentials(env)   # bad keys stop here: no SDK import, no log file
    sj = shioaji()
    api = sj.Shioaji(simulation=not live)
    kw = {}
    params = _params(api.login)
    if "fetch_contract" in params:
        kw["fetch_contract"] = True   # ≤1.5 downloads contracts at login; 1.7 loads them on query
    if "subscribe_trade" in params:
        kw["subscribe_trade"] = True
    try:
        api.login(api_key=api_key, secret_key=secret, **kw)
    except Exception as e:
        raise SinopacError(f"SinoPac login failed ({type(e).__name__}: {scrub(e, env)[:200]})") from e
    _api, _live, _key_fp, _ca_ok = api, live, key_fingerprint(env), False
    note_ok()
    if not _atexit_armed:
        atexit.register(_at_exit)
        _atexit_armed = True
    logging.info(f"[sinopac] login ok (simulation={not live}, shioaji "
                 f"{getattr(sj, '__version__', '?')})")


def _activate_ca(env):
    """Live orders need the CA certificate, activated AFTER login (lesson 2).
    person_id: .env sinopac_person_id, else the logged-in account's own id,
    else the CA password (SinoPac's default password is the national ID)."""
    global _ca_ok
    ca_path = str(env_get(env, "sinopac_ca_path")).strip()
    ca_passwd = str(env_get(env, "sinopac_ca_passwd")).strip()
    if not ca_path or not ca_passwd:
        raise SinopacError("SINOPAC_LIVE=true but sinopac_ca_path / sinopac_ca_passwd missing — "
                           "live orders are impossible without the CA certificate")
    acct = getattr(_api, "stock_account", None)
    person_id = (str(env_get(env, "sinopac_person_id")).strip()
                 or str(getattr(acct, "person_id", "") or "").strip() or ca_passwd)
    try:
        ok = _api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd, person_id=person_id)
    except Exception as e:
        raise SinopacError(f"CA activation failed ({type(e).__name__}: {scrub(e, env)[:200]}) — "
                           "check sinopac_ca_path / sinopac_ca_passwd; a certificate never "
                           "activated must first be activated in SinoPac's own app") from e
    if not ok:
        raise SinopacError("CA activation returned falsy — certificate not usable; activate it "
                           "in SinoPac's own app (e-Leader / 大戶投) first")
    _ca_ok = True
    logging.info("[sinopac] CA activated")


def get_api(env, need_ca=False):
    """The process's logged-in Shioaji client (thread-safe singleton). A change
    of SINOPAC_LIVE or of the keys since the last login logs in again.
    need_ca=True (orders): activates the CA certificate in live mode."""
    with _lock:
        live = is_live(env)
        if _api is not None and (live != _live or key_fingerprint(env) != _key_fp):
            logging.info("[sinopac] credentials or SINOPAC_LIVE changed — logging in again")
            reset()
        if _api is None:
            _login(env, live)
        if need_ca and _live and not _ca_ok:
            _activate_ca(env)
        return _api


def simulation():
    """True/False for the current session, None before the first login."""
    return None if _live is None else not _live


def note_ok():
    global _last_ok
    _last_ok = time.monotonic()


def is_connection_error(e):
    """Errors a fresh login can fix (dead socket, expired token, timeout)."""
    if isinstance(e, (ConnectionError, TimeoutError)):
        return True
    try:
        sj = shioaji()
    except SinopacError:
        return False
    kinds = tuple(k for k in (getattr(sj, n, None) for n in (
        "ShioajiConnectionError", "ShioajiTimeoutError", "TokenError")) if isinstance(k, type))
    return bool(kinds) and isinstance(e, kinds)


def read(env, fn, kind="account", need_ca=False):
    """fn(api) for a READ, throttled, retried once on a fresh login when the
    connection died. Never use for orders: a retried order can fill twice."""
    for attempt in (0, 1):
        api = get_api(env, need_ca=need_ca)
        throttle(kind)
        try:
            out = fn(api)
        except Exception as e:
            if attempt == 0 and is_connection_error(e):
                logging.warning(f"[sinopac] {type(e).__name__} on a read — logging in again")
                reset()
                continue
            raise
        note_ok()
        return out


def ensure_fresh(env):
    """Before an order: a session idle past IDLE_PROBE_S is probed with a cheap
    authenticated call and replaced if it is dead."""
    if _api is None or time.monotonic() - _last_ok < IDLE_PROBE_S:
        return
    try:
        throttle("account")
        _api.usage()
        note_ok()
    except Exception as e:
        logging.warning(f"[sinopac] idle session probe failed ({type(e).__name__}) — "
                        f"logging in again before the order")
        reset()


# ── accounts and contracts ───────────────────────────────────────────────────

def stock_account(api):
    acct = getattr(api, "stock_account", None)
    if acct is not None:
        return acct
    for a in (api.list_accounts() if hasattr(api, "list_accounts") else []) or []:
        if enum_value(getattr(a, "account_type", "")) in ("S", "Stock") \
                or type(a).__name__ == "StockAccount":
            return a
    raise SinopacError("no stock account on this login — check the API key's accounts and "
                       "permissions in SinoPac's API management page")


def account_id(api):
    """'<broker>-<account>' of the stock account — the id the account guard
    compares (lib.portfolio.book_account_check)."""
    a = stock_account(api)
    broker, acct = getattr(a, "broker_id", "") or "", getattr(a, "account_id", "") or ""
    if not acct:
        raise SinopacError("stock account has no account_id")
    return f"{broker}-{acct}"


def stock_contract(api, code):
    """The order/quote contract of a TWSE/TPEx code (1.7 contracts.get, else
    the ≤1.5 Contracts.Stocks table). Unknown → SinopacError."""
    code = str(code).strip().upper()
    c = None
    getter = getattr(getattr(api, "contracts", None), "get", None)
    if callable(getter):
        try:
            c = getter(code)
        except Exception as e:
            logging.info(f"[sinopac] contracts.get({code}) failed ({type(e).__name__})")
            c = None
    if c is None:
        table = getattr(getattr(api, "Contracts", None), "Stocks", None)
        try:
            c = table[code] if table is not None else None
        except Exception:
            c = None
    if c is None:
        from lib import reject_token
        raise SinopacError(reject_token.tag(reject_token.SYMBOL_UNAVAILABLE,
                                            f"{code}: 永豐查無此股票代號"))
    kind = enum_value(getattr(c, "security_type", "") or "")
    if kind and kind not in ("STK", "Stock"):
        from lib import reject_token
        raise SinopacError(reject_token.tag(reject_token.SYMBOL_UNAVAILABLE,
                                            f"{code}: not a stock on SinoPac ({kind})"))
    return c


def stock_info(api, contract):
    """limit_up / limit_down / reference / trading_suspended / disposition_*
    of a stock: 1.7 api.contracts.info(), else the ≤1.5 contract itself."""
    info = getattr(getattr(api, "contracts", None), "info", None)
    if callable(info):
        try:
            got = info(contract)
            if got is not None:
                return got
        except Exception as e:
            logging.info(f"[sinopac] contracts.info failed ({type(e).__name__}) — using the contract")
    return contract


# ── time ─────────────────────────────────────────────────────────────────────

def now_taipei():
    return datetime.now(TAIPEI)
