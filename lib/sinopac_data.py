# AutoTradeSys fork addition (2026-10-25): SinoPac historical K bars for backtests.
# Licensed under the Apache License, Version 2.0 (same as the upstream Blave Agent).
"""
Taiwan stock / ETF K bars from SinoPac's Shioaji (永豐金 API) — the bars a
strategy backtests on with lib/runner.py, and that its live tick reads.

    from lib.sinopac_data import fetch_sinopac_kbars
    df = fetch_sinopac_kbars('2330', '5m', '2024-01-01', None)        # raw prices
    df = fetch_sinopac_kbars('0050', '1d', '2021-01-01', None, adjust=True)

Intervals: '1m' '5m' '15m' '30m' '60m' (also '1min' '5min' '15min' '30min'
'1h' '60min') and '1d'. Same conventions as lib.data.fetch_twstock_ohlcv, so a
strategy can swap the two fetchers without touching its time logic:
  - intraday bars carry minute-START labels on a tz-aware UTC index (Shioaji
    labels a 1-minute bar by its END minute — 09:01 is 09:00–09:01 — and that
    is converted here); '1d' bars carry Asia/Taipei midnight labels;
  - Volume is in lots (張), Shioaji's own unit; Amount is TWD;
  - prices are RAW (as traded). adjust=True scales each day's bars by that
    day's adjusted/raw close ratio from lib.data.fetch_twstock_price_adj /
    fetch_twstock_price — the exchanges' own price-continuity events (除權息,
    減資, 分割) — so a backtest across ex-dividend dates sees no fake gaps.
    Volume is never adjusted.
  - CLOSED bars only: a bar whose period has not ended in Taipei time is left
    out (the 13:30 closing auction counts as printed from 13:31), so a live
    tick never computes on a forming bar.

Coverage: Shioaji kbars start 2020-03-02 (an earlier start is moved up, with a
note). Board-lot (整股) trades only — odd lots are not in kbars.

Cache: cache/sinopac_kbars/<CODE>/<YYYY-MM>.parquet holds the 1-minute bars;
a finished month is fetched once, the current month again from its last
cached day once older than CACHE_TTL_S (BLAVE_MODE=live: every call). One
request spans at most 30 days (the kbars limit).

Quota (SinoPac 使用限制): kbars draw on the account's daily market-data traffic
(500 MB for an account with no trading volume) and on 270 kbars queries per
trading session; a deep cold backfill belongs after the close. Logging in
needs the same .env keys as trading; no CA certificate is needed for data.

Registered into lib.data's namespace on import (fetch_sinopac_kbars), so
lib/runner's look-ahead check records and replays it like any lib.data
fetcher and covers fetch_data as well as compute_signals — import it at the
TOP of strategy.py: the recorder wraps lib.data's fetchers when fetch_data
starts, and a fetcher first imported inside fetch_data is registered too late
(the check then covers compute_signals only).
"""
import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd

from lib import sinopac_session as ss

DATA_START = date(2020, 3, 2)
CACHE_DIR = os.path.join("cache", "sinopac_kbars")
CACHE_TTL_S = 3600
MAX_SPAN_DAYS = 30
SESSION_OPEN = (9, 0)
SESSION_CLOSE = (13, 30)
AUCTION_PRINT_GRACE = timedelta(minutes=1)
DAILY_FINAL = (13, 35)
_INTERVALS = {"1m": 1, "1min": 1, "5m": 5, "5min": 5, "15m": 15, "15min": 15,
              "30m": 30, "30min": 30, "60m": 60, "60min": 60, "1h": 60, "1d": None}
_COLS = ["Open", "High", "Low", "Close", "Volume", "Amount"]
_noted = set()


class SinopacDataError(ss.SinopacError):
    """Bars could not be fetched — never answered with an empty frame."""


def _note_once(key, msg):
    if key not in _noted:
        _noted.add(key)
        print(f"  ⚠️ {msg}")
        logging.warning(f"[sinopac_data] {msg}")


def _read_env(path=".env"):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


def _code(symbol):
    s = str(symbol or "").strip().upper()
    for suffix in (".TWO", ".TW"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if not s:
        raise ValueError("symbol is empty")
    return s


def _as_date(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


# ── fetching 1-minute bars ───────────────────────────────────────────────────

def _kbars_frame(kb):
    """Shioaji KBars → 1-minute frame on START labels (tz-aware Asia/Taipei).
    ts is Taipei wall clock encoded as epoch ns, and marks the bar's END."""
    def col(name):
        v = getattr(kb, name, None)
        if v is None and isinstance(kb, dict):
            v = kb.get(name)
        return list(v or [])

    ts = col("ts")
    if not ts:
        return pd.DataFrame(columns=_COLS, index=pd.DatetimeIndex([], tz="Asia/Taipei"))
    end = pd.to_datetime(pd.Series(ts, dtype="int64"), unit="ns")
    start = (end - pd.Timedelta(minutes=1)).dt.tz_localize("Asia/Taipei")
    df = pd.DataFrame({c: pd.to_numeric(pd.Series(col(c)), errors="coerce") for c in _COLS})
    df.index = pd.DatetimeIndex(start)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def _fetch_span(env, code, d0, d1):
    """1-minute bars of [d0, d1] (dates, ≤ MAX_SPAN_DAYS) from Shioaji."""
    def call(api):
        contract = ss.stock_contract(api, code)
        return api.kbars(contract, start=d0.isoformat(), end=d1.isoformat())

    try:
        kb = ss.read(env, call, kind="market")
    except ss.SinopacError:
        raise
    except Exception as e:
        name = type(e).__name__
        hint = (" — SinoPac's daily market-data quota is used up (it resets 08:00 on a trading day)"
                if "UsageLimit" in name else "")
        raise SinopacDataError(f"{code}: kbars {d0}..{d1} failed ({name}: "
                               f"{ss.scrub(e, env)[:160]}){hint}") from e
    return _kbars_frame(kb)


def _spans(d0, d1):
    out, cur = [], d0
    while cur <= d1:
        nxt = min(cur + timedelta(days=MAX_SPAN_DAYS - 1), d1)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def _month_paths(code, month):
    base = os.path.join(CACHE_DIR, code, month.strftime("%Y-%m"))
    return base + ".parquet", base + ".json"


def _load_month(code, month):
    from lib.winreplace import load_json
    pq, meta = _month_paths(code, month)
    try:
        info = load_json(meta, encoding="utf-8")
        df = pd.read_parquet(pq) if os.path.exists(pq) else pd.DataFrame(columns=_COLS)
        if len(df):
            df.index = pd.DatetimeIndex(df.index).tz_convert("Asia/Taipei")
        return df, info
    except (OSError, ValueError):
        return None, None


def _save_month(code, month, df, through, complete):
    pq, meta = _month_paths(code, month)
    os.makedirs(os.path.dirname(pq), exist_ok=True)
    tmp = f"{pq}.{os.getpid()}.tmp"
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
    out.to_parquet(tmp)
    os.replace(tmp, pq)
    tmpm = f"{meta}.{os.getpid()}.tmp"
    with open(tmpm, "w", encoding="utf-8") as f:
        json.dump({"through": through.isoformat(), "fetched_at": time.time(),
                   "complete": bool(complete)}, f)
    os.replace(tmpm, meta)


def _minute_bars(env, code, d0, d1, today, live):
    """1-minute bars of [d0, d1] through the monthly cache."""
    frames = []
    month = date(d0.year, d0.month, 1)
    while month <= d1:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        m_end = nxt - timedelta(days=1)
        want_end = min(m_end, today)
        cached, info = _load_month(code, month)
        through = _as_date((info or {}).get("through"), None)
        fresh = bool(info) and time.time() - float(info.get("fetched_at") or 0) < CACHE_TTL_S
        # complete = fetched after the month's last day was over; a fetch ON that day
        # (through == m_end) may hold a partial session and is re-read like any today
        if info and "complete" in info:
            complete = bool(info["complete"])
        else:
            fetched = datetime.fromtimestamp(float((info or {}).get("fetched_at") or 0), ss.TAIPEI)
            complete = bool(info) and fetched.date() > m_end
        # a past month must be complete; only the current one may be served within the TTL
        if cached is not None and through is not None and (
                complete or (m_end >= today and through >= want_end and fresh and not live)):
            frames.append(cached)
        else:
            # re-fetch from the last cached day (it may have been a partial day) to today
            begin = month if cached is None or through is None else max(month, through)
            begin = max(begin, DATA_START)
            got = [_fetch_span(env, code, a, b) for a, b in _spans(begin, want_end)]
            parts = [p for p in [cached if cached is not None else None] + got
                     if p is not None and len(p)]
            if parts:
                merged = pd.concat(parts)
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            else:
                merged = pd.DataFrame(columns=_COLS,
                                      index=pd.DatetimeIndex([], tz="Asia/Taipei"))
            _save_month(code, month, merged, want_end, complete=m_end < today)
            frames.append(merged)
        month = nxt
    if not frames:
        return pd.DataFrame(columns=_COLS, index=pd.DatetimeIndex([], tz="Asia/Taipei"))
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    lo = pd.Timestamp(d0).tz_localize("Asia/Taipei")
    hi = pd.Timestamp(d1 + timedelta(days=1)).tz_localize("Asia/Taipei")
    return df[(df.index >= lo) & (df.index < hi)]


# ── shaping ──────────────────────────────────────────────────────────────────

_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last",
        "Volume": "sum", "Amount": "sum"}


def _resample(df, minutes):
    """N-minute bars from 1-minute START-labelled bars (Taipei): bins anchored at
    midnight, which puts them on 09:00 for every N dividing 60."""
    if minutes == 1 or df.empty:
        return df
    out = df.resample(f"{minutes}min", label="left", closed="left").agg(_AGG)
    return out.dropna(subset=["Open", "Close"])


def _daily(df):
    if df.empty:
        return df
    days = df.index.tz_localize(None).normalize()
    out = df.groupby(days).agg(_AGG)
    out.index = pd.DatetimeIndex(out.index).tz_localize("Asia/Taipei")
    return out.dropna(subset=["Open", "Close"])


def _closed_only(df, minutes, now, last_minute=None):
    """Bars whose period ended by `now` (Taipei). '1d': today's bar only past
    13:35 AND built through the session's last minute (`last_minute`, the
    newest 1-minute label) — a cache filled mid-session must not pass a
    partial day off as the day's bar."""
    if df.empty:
        return df
    if minutes is None:
        final = now.replace(hour=DAILY_FINAL[0], minute=DAILY_FINAL[1], second=0, microsecond=0)
        today = pd.Timestamp(now.date()).tz_localize("Asia/Taipei")
        complete = last_minute is not None and last_minute >= today + pd.Timedelta(
            hours=SESSION_CLOSE[0], minutes=SESSION_CLOSE[1] - 1)
        return df[(df.index < today) | ((df.index == today) & (now >= final) & complete)]
    end = df.index + pd.Timedelta(minutes=minutes)
    days = df.index.normalize()
    close = days + pd.Timedelta(hours=SESSION_CLOSE[0], minutes=SESSION_CLOSE[1])
    # a bar holding the session's last minute holds the 13:30 closing auction:
    # final once the auction printed, however far its nominal end runs past 13:30
    end = end.where(end <= close - pd.Timedelta(minutes=1), close + AUCTION_PRINT_GRACE)
    return df[end <= pd.Timestamp(now)]


def _adjust(df, code, d0, d1, env):
    """× (adjusted close ÷ raw close) of each bar's Taipei date (lib.data daily
    series — the exchanges' own price-continuity events)."""
    if df.empty:
        return df
    import lib.data as D
    hdrs = {"api-key": ss.env_get(env, "blave_api_key"),
            "secret-key": ss.env_get(env, "blave_secret_key")}
    s, e = (d0 - timedelta(days=14)).isoformat(), (d1 + timedelta(days=1)).isoformat()
    try:
        adj = D.fetch_twstock_price_adj(code, s, e, hdrs)["Close"]
        raw = D.fetch_twstock_price(code, s, e, hdrs)["Close"]
    except Exception as ex:
        raise SinopacDataError(f"{code}: adjustment factors unavailable ({type(ex).__name__}: "
                               f"{ex}) — not returning raw prices under adjust=True") from ex
    def by_day(s_):
        idx = pd.DatetimeIndex(s_.index)
        idx = idx.tz_convert("Asia/Taipei").tz_localize(None) if idx.tz is not None else idx
        return pd.Series(s_.values, index=idx.normalize())
    factor = (by_day(adj) / by_day(raw)).replace([float("inf"), -float("inf")], float("nan")).dropna()
    factor = factor[~factor.index.duplicated(keep="last")].sort_index()
    if factor.empty:
        raise SinopacDataError(f"{code}: no adjustment factors in {s}..{e}")
    days = pd.DatetimeIndex(df.index.tz_convert("Asia/Taipei").tz_localize(None).normalize())
    udays = days.unique()   # intraday: many bars a day — reindex on the unique days first
    per_day = factor.reindex(factor.index.union(udays)).ffill().reindex(udays)
    if per_day.isna().any():
        per_day = per_day.bfill()
    f = per_day.reindex(days)
    if days.max() > factor.index.max():
        _note_once(("adjfresh", code), f"{code}: adjustment factors end {factor.index.max().date()} — "
                   f"later bars use that day's factor (an ex-dividend day not yet published "
                   f"would show as a gap)")
    out = df.copy()
    for c in ("Open", "High", "Low", "Close"):
        out[c] = out[c].values * f.values
    return out


# ── public ───────────────────────────────────────────────────────────────────

def _fetch_sinopac_kbars(symbol, interval, start, end=None, env=None, adjust=False,
                         headers=None):
    """The implementation (see the module docstring). `env` = the .env dict
    (default: ./.env); `headers` is accepted and ignored (lib.data call style)."""
    if interval not in _INTERVALS:
        raise ValueError(f"interval must be one of {sorted(_INTERVALS)}, got {interval!r}")
    code = _code(symbol)
    if isinstance(env, dict) and not any("sinopac" in str(k).lower() for k in env):
        env = None  # Blave headers passed lib.data-style (…, start, end, hdrs): not a .env
    env = env if env is not None else _read_env()
    now = ss.now_taipei()
    today = now.date()
    d0 = _as_date(start, DATA_START)
    d1 = min(_as_date(end, today), today)
    if d0 < DATA_START:
        _note_once(("clamp", code), f"{code}: SinoPac kbars start {DATA_START} — start "
                   f"{d0} moved up")
        d0 = DATA_START
    if d0 > d1:
        return pd.DataFrame(columns=_COLS)
    live = os.environ.get("BLAVE_MODE") == "live"
    bars = _minute_bars(env, code, d0, d1, today, live)
    minutes = _INTERVALS[interval]
    out = _daily(bars) if minutes is None else _resample(bars, minutes)
    out = _closed_only(out, minutes, now, bars.index.max() if len(bars) else None)
    if adjust:
        out = _adjust(out, code, d0, d1, env)
    if minutes is not None:
        out.index = out.index.tz_convert("UTC")
    out = out[_COLS].astype(float)
    out.attrs["source"] = "SinoPac"
    out.attrs["adjusted"] = bool(adjust)
    return out


def fetch_sinopac_kbars(symbol, interval, start, end=None, env=None, adjust=False,
                        headers=None):
    """OHLCV(+Amount) DataFrame of a TWSE/TPEx stock or ETF from SinoPac's
    Shioaji kbars — see the module docstring for intervals, labels, units,
    adjustment, cache and quota. Raises SinopacDataError, never an empty frame
    for a failed fetch (an empty frame means no trades in the window)."""
    import lib.data as D
    # vars(), never getattr/hasattr: lib.data's module __getattr__ raises UnknownFetcher
    # for a fetch_* name it does not define
    impl = vars(D).get("fetch_sinopac_kbars") or _fetch_sinopac_kbars
    return impl(symbol, interval, start, end, env=env, adjust=adjust, headers=headers)


def fetch_sinopac_kbars_batch(symbols, interval, start, end=None, env=None, adjust=False):
    """{code: frame} for a universe — one symbol after another (SinoPac's
    market-data limits are per account: never in parallel)."""
    env = env if env is not None else _read_env()
    return {_code(s): fetch_sinopac_kbars(s, interval, start, end, env=env, adjust=adjust)
            for s in symbols}


def _register():
    """lib.data namespace entry: lib/runner's look-ahead recorder wraps every
    lib.data fetch_* for the duration of fetch_data (record, then replay
    truncated copies) — registered, this fetcher is checked like the others."""
    try:
        import lib.data as D
    except Exception as e:  # pandas/requests missing: the fetcher still works unregistered
        logging.info(f"[sinopac_data] lib.data unavailable ({type(e).__name__}) — not registered")
        return
    if "fetch_sinopac_kbars" not in vars(D):  # hasattr raises there (lib.data.UnknownFetcher)
        D.fetch_sinopac_kbars = _fetch_sinopac_kbars
    reg = getattr(D, "_PRICE_FETCHERS", None)
    if isinstance(reg, dict):
        reg.setdefault("fetch_sinopac_kbars", "tw")


_register()


def _main(argv=None):
    """Prefetch into the cache from a shell:
    python3 -m lib.sinopac_data 2330 5m 2024-01-01 [2024-06-30] [--adjust]"""
    import argparse
    p = argparse.ArgumentParser(description="SinoPac kbars → cache (and a summary)")
    p.add_argument("symbol")
    p.add_argument("interval")
    p.add_argument("start")
    p.add_argument("end", nargs="?")
    p.add_argument("--adjust", action="store_true")
    a = p.parse_args(argv)
    t0 = time.time()
    df = fetch_sinopac_kbars(a.symbol, a.interval, a.start, a.end, adjust=a.adjust)
    if df.empty:
        print(f"{a.symbol} {a.interval}: no bars in {a.start}..{a.end or 'today'}")
        return 0
    print(f"{a.symbol} {a.interval}: {len(df)} bars, {df.index[0]} → {df.index[-1]} "
          f"({time.time() - t0:.1f}s, adjusted={a.adjust})")
    print(df.tail(5).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
