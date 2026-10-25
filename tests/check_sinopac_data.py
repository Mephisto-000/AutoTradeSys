# AutoTradeSys fork addition (2026-10-25)
"""lib/sinopac_data.py — SinoPac kbars for backtests, offline (tests/sinopac_fake.py):

  - Shioaji labels a 1-minute bar by its END minute (09:01 = 09:00–09:01): the
    frame carries START labels like lib.data.fetch_twstock_ohlcv — intraday on a
    tz-aware UTC index, '1d' on Asia/Taipei midnights, Volume in lots;
  - N-minute bars sit on 09:00; the bar holding the 13:30 closing auction is the
    last of the day; a forming bar is never returned (a live tick must not read one);
  - one request spans ≤ 30 days; months are cached — a backtest re-run fetches
    nothing, a stale current month only from its last cached day, a live tick
    always refreshes today;
  - adjust=True scales each day by adjusted ÷ raw close (lib.data daily series),
    volume untouched; a missing factor source raises instead of returning raw;
  - registered in lib.data, so lib/runner's look-ahead recorder records and
    replays it like any lib.data fetcher.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_data.py
"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="sinopac-data-")
os.environ["BLAVE_AGENT_HOME"] = os.environ["BLAVECLAW_HOME"] = WS
os.environ.pop("BLAVE_MODE", None)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(WS)
open(".env", "w").write(f"sinopac_api_key={'k' * 32}\nsinopac_secret_key={'s' * 32}\n")

import pandas as pd  # noqa: E402
import sinopac_fake  # noqa: E402

B = sinopac_fake.install()
import lib.data as D  # noqa: E402
from lib import sinopac_data as sd  # noqa: E402
from lib import sinopac_session as ss  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


NOW = [datetime(2024, 3, 5, 20, 0, tzinfo=ss.TAIPEI)]
ss.now_taipei = lambda: NOW[0]
EPOCH = pd.Timestamp("1970-01-01")


def day_price(d):
    return 100.0 + (d - date(2024, 1, 1)).days


def source(code, start, end):
    """Weekday sessions, ts = Taipei wall clock of the bar END as epoch ns (Shioaji's
    encoding), cut at NOW for today."""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    out = {k: [] for k in ("ts", "Open", "High", "Low", "Close", "Volume", "Amount")}
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            base = day_price(d)
            for i in range(270):  # 09:01 … 13:30
                end_t = datetime(d.year, d.month, d.day, 9, 1) + timedelta(minutes=i)
                if end_t > NOW[0].replace(tzinfo=None):
                    break
                px = base + i * 0.01
                out["ts"].append(int((pd.Timestamp(end_t) - EPOCH).value))
                out["Open"].append(px)
                out["High"].append(px + 0.5)
                out["Low"].append(px - 0.5)
                out["Close"].append(px + 0.005)
                out["Volume"].append(2)
                out["Amount"].append(2 * 1000 * px)
        d += timedelta(days=1)
    return out


B.kbars_source = source
B.quote("2330", 100.0)

print("== labels, units, timezone")
f1 = sd.fetch_sinopac_kbars("2330", "1m", "2024-01-02", "2024-01-02")
first = f1.index[0].tz_convert("Asia/Taipei")
check(str(f1.index.tz) == "UTC" and first.hour == 9 and first.minute == 0 and len(f1) == 270,
      f"1m: 270 bars, first labelled 09:00 Taipei (Shioaji's 09:01), UTC index ({first})")
check(f1["Volume"].iloc[0] == 2 and list(f1.columns) == ["Open", "High", "Low", "Close", "Volume", "Amount"]
      and f1.attrs.get("source") == "SinoPac", "Volume in lots as Shioaji gives it; Amount TWD")

print("== resampling")
f5 = sd.fetch_sinopac_kbars("2330", "5m", "2024-01-02", "2024-01-02")
t5 = f5.index.tz_convert("Asia/Taipei")
check(len(f5) == 54 and (t5[0].hour, t5[0].minute) == (9, 0) and (t5[-1].hour, t5[-1].minute) == (13, 25),
      f"5m: 54 bars 09:00 … 13:25 ({len(f5)})")
check(abs(f5["Open"].iloc[0] - f1["Open"].iloc[0]) < 1e-12 and abs(f5["Close"].iloc[0] - f1["Close"].iloc[4]) < 1e-12
      and f5["Volume"].iloc[0] == 10, "5m bar = first open, fifth close, summed volume")
check(abs(f5["Close"].iloc[-1] - f1["Close"].iloc[-1]) < 1e-12,
      "the 13:25 bar closes on the closing auction (Shioaji's 13:30 bar)")
f60 = sd.fetch_sinopac_kbars("2330", "60m", "2024-01-02", "2024-01-02")
check([t.hour for t in f60.index.tz_convert("Asia/Taipei")] == [9, 10, 11, 12, 13], "60m: 09:00 … 13:00")
fd = sd.fetch_sinopac_kbars("2330", "1d", "2024-01-02", "2024-01-05")
check(str(fd.index.tz) == "Asia/Taipei" and [t.day for t in fd.index] == [2, 3, 4, 5]
      and fd.index[0].hour == 0 and fd["Volume"].iloc[0] == 540
      and abs(fd["Close"].iloc[0] - f1["Close"].iloc[-1]) < 1e-12,
      "1d: Taipei midnights, the day's last close, 540 lots")

print("== chunking and the cache")
B.kbars_calls.clear()
sd.fetch_sinopac_kbars("2330", "5m", "2024-01-01", "2024-03-05")
spans = [(date.fromisoformat(s), date.fromisoformat(e)) for _, s, e in B.kbars_calls]
check(spans and all((e - s).days + 1 <= 30 for s, e in spans),
      f"every request ≤ 30 days ({[(str(s), str(e)) for s, e in spans]})")
check(os.path.exists(os.path.join(sd.CACHE_DIR, "2330", "2024-02.parquet")), "months cached")
B.kbars_calls.clear()
sd.fetch_sinopac_kbars("2330", "15m", "2024-01-01", "2024-03-05")
check(B.kbars_calls == [], "a re-run inside the cache TTL fetches nothing")
sd.CACHE_TTL_S = -1
B.kbars_calls.clear()
sd.fetch_sinopac_kbars("2330", "15m", "2024-01-01", "2024-03-05")
check(B.kbars_calls == [("2330", "2024-03-05", "2024-03-05")],
      f"a stale current month refetches only from its last cached day ({B.kbars_calls})")
sd.CACHE_TTL_S = 3600
os.environ["BLAVE_MODE"] = "live"
B.kbars_calls.clear()
sd.fetch_sinopac_kbars("2330", "15m", "2024-02-01", "2024-03-05")
check(B.kbars_calls == [("2330", "2024-03-05", "2024-03-05")], "a live tick always refreshes today")
os.environ.pop("BLAVE_MODE")

print("== closed bars only (a live tick: today is always re-read)")
os.environ["BLAVE_MODE"] = "live"
NOW[0] = datetime(2024, 3, 6, 10, 7, tzinfo=ss.TAIPEI)
f5 = sd.fetch_sinopac_kbars("2330", "5m", "2024-03-06", "2024-03-06")
last = f5.index[-1].tz_convert("Asia/Taipei")
check((last.hour, last.minute) == (10, 0), f"at 10:07 the last 5m bar is 10:00 (10:05 still forming) ({last})")
fd = sd.fetch_sinopac_kbars("2330", "1d", "2024-03-04", "2024-03-06")
check([t.day for t in fd.index] == [4, 5], "today's daily bar is not returned before 13:35")
NOW[0] = datetime(2024, 3, 6, 13, 30, 30, tzinfo=ss.TAIPEI)
f5 = sd.fetch_sinopac_kbars("2330", "5m", "2024-03-06", "2024-03-06")
last = f5.index[-1].tz_convert("Asia/Taipei")
check((last.hour, last.minute) == (13, 20), f"13:30:30: the auction bar (13:25) waits for 13:31 ({last})")
NOW[0] = datetime(2024, 3, 6, 13, 31, tzinfo=ss.TAIPEI)
f5 = sd.fetch_sinopac_kbars("2330", "5m", "2024-03-06", "2024-03-06")
check((f5.index[-1].tz_convert("Asia/Taipei").minute) == 25, "13:31: the 13:25 auction bar is in")
os.environ.pop("BLAVE_MODE")
NOW[0] = datetime(2024, 3, 6, 13, 0, tzinfo=ss.TAIPEI)
for ext in ("parquet", "json"):   # start the month over: the cache holds the day up to 13:00 only
    os.remove(os.path.join(sd.CACHE_DIR, "2330", f"2024-03.{ext}"))
sd.fetch_sinopac_kbars("2330", "1m", "2024-03-06", "2024-03-06")
NOW[0] = datetime(2024, 3, 6, 13, 40, tzinfo=ss.TAIPEI)
fd = sd.fetch_sinopac_kbars("2330", "1d", "2024-03-04", "2024-03-06")  # served from that cache
check([t.day for t in fd.index] == [4, 5],
      "a cache filled mid-session never passes the partial day off as today's daily bar")
NOW[0] = datetime(2024, 3, 6, 20, 0, tzinfo=ss.TAIPEI)

print("== adjustment")
calls = []


def daily(adjusted):
    def f(code, start, end, hdrs):
        calls.append((code, adjusted))
        idx = pd.date_range("2024-02-20", "2024-03-06", freq="B")
        raw = pd.Series([day_price(d.date()) + 0.275 for d in idx], index=idx)
        if adjusted:
            raw = raw * [0.9 if d < pd.Timestamp("2024-03-01") else 1.0 for d in idx]
        return pd.DataFrame({"Open": raw, "Close": raw})
    return f


D.fetch_twstock_price_adj, D.fetch_twstock_price = daily(True), daily(False)
raw = sd.fetch_sinopac_kbars("2330", "1d", "2024-02-26", "2024-03-05")
adj = sd.fetch_sinopac_kbars("2330", "1d", "2024-02-26", "2024-03-05", adjust=True)
ratio = (adj["Close"] / raw["Close"]).round(6)
check(list(ratio) == [0.9, 0.9, 0.9, 0.9, 1.0, 1.0, 1.0] and (adj["Volume"] == raw["Volume"]).all()
      and adj.attrs.get("adjusted") is True,
      f"each day × its factor (0.9 before the event, 1.0 after), volume untouched ({list(ratio)})")


def broken(*a, **k):
    raise OSError("factor source down")


D.fetch_twstock_price_adj = broken
try:
    sd.fetch_sinopac_kbars("2330", "1d", "2024-02-26", "2024-03-05", adjust=True)
    refused = False
except sd.SinopacDataError:
    refused = True
check(refused, "no factors → raised, never raw prices under adjust=True")

print("== a month's last day is not frozen by its own date (review 2026-10-25)")
os.environ["BLAVE_MODE"] = "live"
B.kbars_calls.clear()
NOW[0] = datetime(2024, 2, 29, 10, 0, tzinfo=ss.TAIPEI)
for ext in ("parquet", "json"):
    pth = os.path.join(sd.CACHE_DIR, "2330", f"2024-02.{ext}")
    if os.path.exists(pth):
        os.remove(pth)
sd.fetch_sinopac_kbars("2330", "1m", "2024-02-29", "2024-02-29")
NOW[0] = datetime(2024, 2, 29, 11, 0, tzinfo=ss.TAIPEI)
f1 = sd.fetch_sinopac_kbars("2330", "1m", "2024-02-29", "2024-02-29")
last = f1.index[-1].tz_convert("Asia/Taipei")
check(len(B.kbars_calls) == 2 and (last.hour, last.minute) == (10, 59),
      f"11:00 on 02-29: re-read, bars through 10:59 ({last.time()}, {len(B.kbars_calls)} calls)")
os.environ.pop("BLAVE_MODE")
NOW[0] = datetime(2024, 3, 1, 20, 0, tzinfo=ss.TAIPEI)
B.kbars_calls.clear()
fd = sd.fetch_sinopac_kbars("2330", "1d", "2024-02-28", "2024-02-29")
check(B.kbars_calls == [("2330", "2024-02-29", "2024-02-29")] and fd["Volume"].iloc[-1] == 540,
      f"the next day: 02-29 fetched once more, complete (540 lots) ({B.kbars_calls})")
B.kbars_calls.clear()
sd.CACHE_TTL_S = -1
sd.fetch_sinopac_kbars("2330", "1d", "2024-02-28", "2024-02-29")
sd.CACHE_TTL_S = 3600
check(B.kbars_calls == [], "…and from then on February is final: no request even with a stale TTL")
NOW[0] = datetime(2024, 3, 6, 20, 0, tzinfo=ss.TAIPEI)

print("== adjust=True on intraday bars (review 2026-10-25)")


def daily_until(adjusted, last):
    full = daily(adjusted)

    def f(code, start, end, hdrs):
        return full(code, start, end, hdrs).loc[:last]   # the newest day not published yet
    return f


D.fetch_twstock_price_adj, D.fetch_twstock_price = daily_until(True, "2024-03-01"), daily_until(False, "2024-03-01")
raw60 = sd.fetch_sinopac_kbars("2330", "60m", "2024-02-28", "2024-03-04")
adj60 = sd.fetch_sinopac_kbars("2330", "60m", "2024-02-28", "2024-03-04", adjust=True)
r = (adj60["Close"] / raw60["Close"]).round(6)
days_ = r.index.tz_convert("Asia/Taipei").normalize()
before = r[days_ < pd.Timestamp("2024-03-01", tz="Asia/Taipei")]
after = r[days_ >= pd.Timestamp("2024-03-01", tz="Asia/Taipei")]
check(len(adj60) == len(raw60) and set(before) == {0.9} and set(after) == {1.0},
      f"60m bars, factors ending 03-01: every bar × its day's factor, 03-04 on the last one "
      f"({sorted(set(r))})")
D.fetch_twstock_price_adj, D.fetch_twstock_price = daily(True), daily(False)

print("== start clamp, call styles")
B.kbars_calls.clear()
sd.fetch_sinopac_kbars("2330", "1d", "2019-06-01", "2020-03-10")
check(B.kbars_calls and min(s for _, s, _ in B.kbars_calls) >= "2020-03-02",
      f"a start before 2020-03-02 is moved up ({sorted(B.kbars_calls)[:1]})")
hdrs = {"api-key": "", "secret-key": ""}
out = sd.fetch_sinopac_kbars("2330", "1d", "2024-01-02", "2024-01-03", hdrs)
check(len(out) == 2, "Blave headers passed lib.data-style (…, start, end, hdrs) → keys read from .env")

print("== lib/runner's look-ahead recorder sees it")
check(vars(D).get("fetch_sinopac_kbars") is sd._fetch_sinopac_kbars
      and D._PRICE_FETCHERS.get("fetch_sinopac_kbars") == "tw", "registered in lib.data as a TW price fetcher")
from lib.runner import _FetchRecorder  # noqa: E402


def fetch_data(hdrs):
    return sd.fetch_sinopac_kbars("2330", "5m", "2024-03-04", "2024-03-05")


rec = _FetchRecorder({})
with rec.recording():
    full = fetch_data({})
check(len(rec.records) == 1, f"the call is recorded ({len(rec.records)})")
cut = full.index[50]
B.kbars_calls.clear()
with rec.replaying(cut, full.index):
    part = fetch_data({})
check(len(part) == 50 and part.index[-1] < cut and B.kbars_calls == [],
      "replay hands back the recorded frame cut before the bar — no fetch")

ss.reset()
print("\n" + ("all ok" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
