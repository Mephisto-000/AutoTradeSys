# AutoTradeSys fork addition (2026-10-25)
"""lib/account_sinopac.py + lib/sinopac_session.py — offline (tests/sinopac_fake.py):

  - the account page reads a SNAPSHOT: a fresh one costs no login (the desktop
    reader runs every minute in a new process; SinoPac allows 1,000 logins a
    day), a stale one is refreshed once, a rebind's snapshot is never served;
  - equity = cash + settlements due after today + shares at last price;
    get_positions is [] (TW stocks are spot inventory), get_holdings lists them;
  - classify: dead connection / expired token = transient, a refused key or CA
    = credential (the reconciler halts), anything else to the floor;
  - the session: 1.7 login without fetch_contract (1.5 with it), a re-login
    when SINOPAC_LIVE or the keys change, CA only for orders in live mode,
    short keys never reach the network, secrets scrubbed from messages,
    a read retried once on a fresh login after a connection error.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_account.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="sinopac-acct-")
os.environ["BLAVE_AGENT_HOME"] = os.environ["BLAVECLAW_HOME"] = WS
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(WS)
os.makedirs("state", exist_ok=True)

import sinopac_fake  # noqa: E402

B = sinopac_fake.install()
from lib import account_sinopac as acct  # noqa: E402
from lib import sinopac_session as ss  # noqa: E402
from lib import venue_errors  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


KEY, SEC = "k" * 32, "s" * 32
SIM = {"sinopac_api_key": KEY, "sinopac_secret_key": SEC}
LIVE = dict(SIM, SINOPAC_LIVE="true", sinopac_ca_path="/x/Sinopac.pfx", sinopac_ca_passwd="pw123456")
NOW = [datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)]
ss.now_taipei = lambda: NOW[0]


def fresh():
    B.reset()
    B.quote("0050", 200.0)
    B.quote("00679B", 30.0)
    B.positions.update({"0050": 1500, "00679B": 2000})
    B.cash = 100_000.0
    B.settlements[:] = [("2026-10-27", 0, -5_000.0), ("2026-10-28", 1, -20_000.0),
                        ("2026-10-29", 2, 7_000.0)]
    ss.reset()
    for p in (acct.SNAPSHOT_PATH, acct.FAIL_PATH):
        if os.path.exists(p):
            os.remove(p)


print("== equity, holdings, positions, account id")
fresh()
eq = acct.get_equity(LIVE)
want = 100_000 + (-20_000 + 7_000) + 1500 * 200 + 2000 * 30
check(eq == {"equity": float(want), "currency": "TWD"},
      f"cash + settlements due after today + shares at last ({eq['equity']:,.0f} == {want:,.0f}; "
      f"today's −5,000 already in the balance)")
check(acct.get_positions(LIVE) == [], "get_positions: [] — no derivative position on a stock account")
h = acct.get_holdings(LIVE)
check([(r["asset"], r["amount"], r["usdt_value"], r["wallet"]) for r in h]
      == [("0050", 1500.0, 300_000.0, "stock"), ("TWD", 100_000.0, 100_000.0, "cash"),
          ("00679B", 2000.0, 60_000.0, "stock")],
      f"holdings sorted by value, with the settlement cash ({h})")
check(acct.get_account_id(LIVE) == "9A95-1234567", "account id = broker-account")
snap = json.load(open(acct.SNAPSHOT_PATH))
check(KEY not in json.dumps(snap) and SEC not in json.dumps(snap), "the snapshot carries no key")

print("== one login per TTL, not per read")
logins = B.logins
for _ in range(5):
    acct.get_equity(LIVE)
    acct.get_holdings(LIVE)
check(B.logins == logins, f"5 more reads inside the TTL: no new login ({B.logins - logins})")
ss.reset()   # a fresh process (the desktop reader's next run)
acct.get_equity(LIVE)
check(B.logins == logins, "a new process with a fresh snapshot: still no login")
snap["read_at"] -= acct.TTL_SESSION_S + 1
json.dump(snap, open(acct.SNAPSHOT_PATH, "w"))
acct.get_equity(LIVE)
check(B.logins == logins + 1, "a stale snapshot (trading day TTL 5 min) refreshes with one login")
NOW[0] = datetime(2026, 10, 27, 20, 0, tzinfo=ss.TAIPEI)
check(acct._ttl(LIVE) == acct.TTL_OFF_S, "outside 08:30–14:30 the TTL is 30 min")
NOW[0] = datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)
other = dict(LIVE, sinopac_api_key="o" * 32)
ss.reset()
logins = B.logins
acct.get_equity(other)
check(B.logins == logins + 1, "other keys (a rebind): the old snapshot is never served")

print("== a failed refresh")
fresh()
acct.get_equity(LIVE)
snap = json.load(open(acct.SNAPSHOT_PATH))
snap["read_at"] -= acct.TTL_SESSION_S + 5
json.dump(snap, open(acct.SNAPSHOT_PATH, "w"))
ss.reset()
B.login_raises = sinopac_fake.ShioajiConnectionError("down")
check(acct.get_equity(LIVE)["equity"] > 0, "refresh fails, snapshot under 3 TTLs old → served")
snap["read_at"] -= 3 * acct.TTL_SESSION_S
json.dump(snap, open(acct.SNAPSHOT_PATH, "w"))
try:
    acct.get_equity(LIVE)
    raised = None
except Exception as e:  # noqa: BLE001
    raised = e
check(raised is not None, f"…older than that → the failure surfaces ({type(raised).__name__})")
check(acct.classify(raised) == venue_errors.TRANSIENT,
      "a dead connection classifies TRANSIENT (also while the next refresh waits out its TTL)")
B.login_raises = None

print("== a broken read does not spend a login every minute")
fresh()
B.login_raises = sinopac_fake.AuthError("bad key")
ss.reset()
try:
    acct.get_equity(LIVE)
except Exception:  # noqa: BLE001 — the first failure surfaces
    pass
n = B.logins
for _ in range(3):
    ss.reset()   # each desktop reader run is a new process
    try:
        acct.get_equity(LIVE)
        surfaced = False
    except ss.SinopacError as e:
        surfaced = "next try after" in str(e)
check(B.logins == n and surfaced, f"inside the TTL after a failure: no new login, the failure says so ({B.logins - n})")
try:
    acct.get_account_id(LIVE)
except Exception as e:  # noqa: BLE001
    held = e
check(acct.classify(held) == venue_errors.CREDENTIAL,
      "…and keeps the first failure's class: a refused key stays a credential problem")
B.login_raises = None
data = json.load(open(acct.FAIL_PATH))
data["at"] -= acct.TTL_SESSION_S + 1
json.dump(data, open(acct.FAIL_PATH, "w"))
ss.reset()
check(acct.get_equity(LIVE)["equity"] > 0 and not os.path.exists(acct.FAIL_PATH),
      "after the TTL one retry; success clears the failure marker")

print("== simulation: no bank balance")
fresh()
eq = acct.get_equity(SIM)
check(eq["equity"] == 1500 * 200 + 2000 * 30 + (-20_000 + 7_000),
      f"simulation: the holdings (+ settlements), no cash read ({eq['equity']:,.0f})")
check(json.load(open(acct.SNAPSHOT_PATH))["simulation"] is True, "the snapshot says simulation")
check(acct.get_account_id(SIM) == "sim:9A95-1234567",
      "simulation's id is another account's: a mode switch restarts the bot's book")
ss.reset()
logins = B.logins
acct.get_equity(LIVE)
check(B.logins == logins + 1, "switching to live: the simulation snapshot is not served")

print("== classify")
check(acct.classify(sinopac_fake.TokenError("expired")) == venue_errors.TRANSIENT
      and acct.classify(TimeoutError()) == venue_errors.TRANSIENT, "expired token / timeout → transient")
try:
    raise ss.SinopacError("SinoPac login failed") from sinopac_fake.AuthError("bad key")
except ss.SinopacError as e:
    wrapped = e
check(acct.classify(wrapped) == venue_errors.CREDENTIAL, "a refused key (wrapped) → credential")
check(acct.classify(ss.SinopacError("shioaji 未安裝 — …")) == venue_errors.CREDENTIAL,
      "SDK not installed → credential (a human fixes setup)")
check(acct.classify(ValueError("x")) is None, "anything else → the venue_errors floor")

print("== the session")
fresh()
api = ss.get_api(SIM)
check(B.login_kwargs[-1] == {"subscribe_trade": True} and B.logins == 1,
      "1.7 login: no fetch_contract argument (it was removed)")
ss.get_api(SIM)
check(B.logins == 1, "one login per process")
ss.get_api(LIVE)
check(B.logins == 2 and B.logouts >= 1, "SINOPAC_LIVE flipped → logout, log in again")
check(not B.ca_calls, "live reads need no CA")
ss.get_api(LIVE, need_ca=True)
check(len(B.ca_calls) == 1 and B.ca_calls[0] == ("/x/Sinopac.pfx", "A123456789"),
      "an order's session activates the CA once, person_id from the account")
ss.get_api(LIVE, need_ca=True)
check(len(B.ca_calls) == 1, "…and only once")
ss.reset()
n = B.logins
for bad in ({}, {"sinopac_api_key": "x", "sinopac_secret_key": "x"}):
    try:
        ss.get_api(bad)
        refused = False
    except ss.SinopacError:
        refused = True
    check(refused and B.logins == n, f"missing / short keys refused before any login ({sorted(bad)})")
check(ss.env_get({"SINOPAC_API_KEY": "A"}, "sinopac_api_key") == "A", "env names match case-insensitively")
check(ss.scrub(f"bad key {KEY} for x", SIM) == "bad key *** for x", "scrub() removes .env values")
fresh()
calls = []


def flaky(a):
    calls.append(1)
    if len(calls) == 1:
        raise sinopac_fake.ShioajiConnectionError("socket closed")
    return "ok"


n = B.logins
check(ss.read(SIM, flaky) == "ok" and len(calls) == 2 and B.logins == n + 2,
      "a read hit by a dead connection is retried once on a fresh login")
calls.clear()
try:
    ss.read(SIM, lambda a: (_ for _ in ()).throw(ValueError("no")))
    retried = None
except ValueError:
    retried = False
check(retried is False, "other errors are not retried")

print("== throttle")
ss._LIMITS["test"] = (3, 0.3)
t0 = time.monotonic()
for _ in range(4):
    ss.throttle("test")
check(time.monotonic() - t0 >= 0.25, "the 4th call in a 3-per-0.3 s window waits")

ss.reset()
print("\n" + ("all ok" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
