# AutoTradeSys fork addition (2026-10-25)
"""SinoPac (永豐金) end to end through the platform's own pipeline — the real
lib/venue_wiring auto-wire, lib/portfolio.reconcile, manager/reconciler's
get_positions / place_order and manager/flatten, against the offline broker
of tests/sinopac_fake.py:

  - .env keys + both libs = the bound venue (no reconciler block of its own);
  - a TW stock target in TWD buys board lots + the odd remainder, and the
    bot's book holds exactly the shares that filled (fees are TWD cash);
  - the user's own shares of the same stock are never sold — not by a close,
    not by close-all; a short signal is flat (cash shares cannot short);
  - while the TWSE session is shut the keys are held quietly (no order, no
    error), and close-all defers to the open;
  - a Type C portfolio of TW stocks trades through the same path.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_wiring.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="sinopac-wire-")
os.environ["BLAVE_AGENT_HOME"] = os.environ["BLAVECLAW_HOME"] = WS
os.environ["BLAVE_AGENT_BASE"] = WS
os.environ["BLAVE_AGENT_WORKSPACE"] = WS
os.environ.pop("BLAVE_AGENT_LOCAL", None)
os.environ.pop("BLAVE_MODE", None)
for d in ("manager", "state", "strategies/tw_a", "strategies/tw_c", "lib"):
    os.makedirs(os.path.join(WS, d), exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))


def _no_real_env(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes)) \
            and os.path.abspath(os.fsdecode(args[0])) == os.path.join(ROOT, ".env"):
        raise PermissionError("the repo .env must never be read by a test")


sys.addaudithook(_no_real_env)
os.chdir(WS)
open(".env", "w").write(f"sinopac_api_key={'k' * 32}\nsinopac_secret_key={'s' * 32}\n"
                        f"SINOPAC_LIVE=true\nsinopac_ca_path=/x/Sinopac.pfx\n"
                        f"sinopac_ca_passwd=pw123456\n")
for p in ("lib/account_sinopac.py", "lib/order_sinopac.py"):   # venue discovery reads the workspace
    open(p, "w").close()

import sinopac_fake  # noqa: E402

B = sinopac_fake.install()
from lib import guard, paper_data, portfolio, venue_wiring  # noqa: E402
from lib import order_sinopac as o  # noqa: E402
from lib import sinopac_session as ss  # noqa: E402
from manager import reconciler  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


SESSION = [True]
ss.now_taipei = lambda: datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)
o._session_open = lambda env, now: SESSION[0]
paper_data.tw_session_open = lambda env=None, now=None: SESSION[0]
o.POLL_S, o.ODD_WAIT_S, o.CANCEL_WAIT_S, o.IOC_WAIT_S = 0.0, 0.05, 0.05, 0.05
portfolio._notify_best_effort = lambda msg: None
ERRORS = []
portfolio._record_order_error = lambda *a, **k: ERRORS.append(a)
CFG, SEED, ORDERS = "manager/portfolio_config.json", "manager/ledger_seed.json", "manager/orders.jsonl"


def config(amounts, exchanges=None):
    json.dump({"amounts": amounts, "self_ledger": True,
               "exchanges": exchanges or {n: "sinopac" for n in amounts}}, open(CFG, "w"))


def signal(pos):
    open("strategies/tw_a/strategy.py", "w").write('MARKET = "spot"\nSYMBOL = "0050"\nINTERVAL = "1d"\n')
    json.dump({"symbol": "0050", "position": pos, "updated_at": int(time.time())},
              open("strategies/tw_a/state.json", "w"))


def fresh():
    B.reset()
    B.quote("0050", 200.0, bid=199.5, ask=200.0)
    B.quote("00679B", 30.0, bid=29.95, ask=30.0)
    B.cash = 5_000_000.0
    ss.reset()
    o._px_cache.clear()
    guard.release_memory_halt()
    for p in (SEED, ORDERS, "manager/last_reconcile.json", "manager/spot_scope.json",
              "state/HALT", "state/paper_tw_close.json", "state/sinopac_account.json"):
        if os.path.exists(p):
            os.remove(p)
    reconciler._min_order_gate.clear()
    json.dump({"seeded_at": "2026-10-01T00:00:00", "own_only_basis": 1, "symbols": {}}, open(SEED, "w"))
    del ERRORS[:]


def rnd():
    reconciler._min_order_gate.clear()
    return portfolio.reconcile(get_positions_fn=reconciler.get_positions,
                               place_order_fn=reconciler.place_order,
                               threshold=reconciler._symbol_threshold)


def bot(key="0050@spot"):
    return (portfolio.ledger_positions("sinopac").get(key) or {}).get("qty", 0.0)


def legs():
    try:
        return [l for row in map(json.loads, open(ORDERS)) for l in row["legs"]]
    except FileNotFoundError:
        return []


print("== the venue")
fresh()
check(venue_wiring.detect_venue(venue_wiring.read_env()) == "sinopac",
      "sinopac keys + both libs → the auto-wired venue")
check(reconciler._hand_wired_routed() is None, "no hand-wired reconciler block involved")

print("== 250,000 TWD of 0050 at 200: one lot + 250 odd shares, booked exactly")
fresh()
config({"tw_a": 250_000})
signal(1.0)
rnd()
check(B.positions.get("0050") == 1250 and bot() == 1250.0,
      f"account 1,250 shares, the bot's book 1,250 ({B.positions.get('0050')}, {bot()})")
lg = legs()
check(len(lg) == 1 and lg[0]["executed_qty"] == 1250.0 and lg[0]["fill_price"] == 200.0
      and lg[0]["exchange"] == "sinopac" and lg[0]["signed_diff"] == 250_000.0,
      f"orders.jsonl: the confirmed fill, in TWD ({lg})")
n = len(B.placed)
rnd()
check(len(B.placed) == n, "the next round has nothing to do")

print("== the user's own shares of the same stock")
B.positions["0050"] += 3000   # bought by hand in the broker's app
rnd()
check(len(B.placed) == n, "a manual 3,000 shares are not the bot's: no order")
signal(0.0)
rnd()
check(B.positions["0050"] == 3000 and bot() == 0.0,
      f"signal flat: the bot sells its 1,250, the user's 3,000 stay ({B.positions['0050']})")

print("== a short signal on a cash stock is flat")
signal(1.0)
rnd()
signal(-1.0)
rnd()
check(B.positions["0050"] == 3000 and bot() == 0.0 and all(
          od.action.value == "Sell" for _, od in B.placed[-2:]),
      f"−1 closes the long and opens nothing short ({B.positions['0050']})")

print("== TWSE shut: held quietly")
fresh()
config({"tw_a": 250_000})
signal(1.0)
SESSION[0] = False
rnd()
snap = json.load(open("manager/last_reconcile.json"))
check(not B.placed and not ERRORS and "0050@spot" in (snap.get("market_closed") or []),
      f"no order, no error, the page shows the market closed ({snap.get('market_closed')})")
SESSION[0] = True
rnd()
check(bot() == 1250.0, "the session opens: bought on the next round")

print("== close-all keeps the user's shares; outside the session it waits for the open")
B.positions["0050"] += 500
from manager import flatten  # noqa: E402  (chdirs to the repo root on import)
os.chdir(WS)
flatten._wait_for_inflight = lambda *a, **k: []
flatten.LOCK_PATH = os.path.join(WS, "state", "flatten.lock")
SESSION[0] = False
flatten._LOCK = None
flatten.flatten()
check(os.path.exists("state/HALT") and B.positions["0050"] == 1750
      and json.load(open("state/paper_tw_close.json"))["keys"] == ["0050@spot"],
      "market shut: HALT set, nothing sold, the close deferred to the open")
SESSION[0] = True
rnd()   # the first round after the open sends the deferred close under the close pass
check(B.positions["0050"] == 500 and bot() == 0.0 and os.path.exists("state/HALT"),
      f"after the open: the bot's 1,250 sold, the user's 500 kept, still paused ({B.positions['0050']})")
fresh()
config({"tw_a": 250_000})
signal(1.0)
rnd()
B.positions["0050"] += 700
flatten._LOCK = None
flatten.flatten()
check(B.positions["0050"] == 700 and bot() == 0.0, "in session: close-all sells the bot's share at once")

print("== a Type C portfolio of TW stocks")
fresh()
open("strategies/tw_c/strategy.py", "w").write('MARKET = "spot"\nUNIVERSE = ["0050", "00679B"]\n')
json.dump({"type": "portfolio", "market": "spot", "weights": {"0050": 0.8, "00679B": 0.2},
           "rebalance_at": 1, "updated_at": int(time.time())}, open("strategies/tw_c/state.json", "w"))
os.remove("strategies/tw_a/state.json")
config({"tw_c": 100_000})
rnd()
check(B.positions.get("0050") == 400 and B.positions.get("00679B") == 666
      and bot("00679B@spot") == 666.0,
      f"80% / 20% of 100,000 TWD → 400 + 666 odd shares ({B.positions})")

print("== the size gate is whole shares")
from lib import execute  # noqa: E402
entry, lot = execute._venue_sizes_usd("0050@spot", 10)
check(abs(entry - 210.0) < 1e-9 and lot == 200.0, f"entry gate 1.05 shares (TWD), one share = one lot ({entry}, {lot})")

print("== a suffixed symbol ('0050.TW') buys and sells like the bare code (review 2026-10-25)")
fresh()
open("strategies/tw_a/strategy.py", "w").write('MARKET = "spot"\nSYMBOL = "0050.TW"\nINTERVAL = "1d"\n')
json.dump({"symbol": "0050.TW", "position": 1.0, "updated_at": int(time.time())},
          open("strategies/tw_a/state.json", "w"))
os.path.exists("strategies/tw_c/state.json") and os.remove("strategies/tw_c/state.json")
config({"tw_a": 250_000})
rnd()
key = "0050.TW@spot"
check(B.positions.get("0050") == 1250 and bot(key) == 1250.0, f"bought 1,250 under {key}")
json.dump({"symbol": "0050.TW", "position": 0.0, "updated_at": int(time.time())},
          open("strategies/tw_a/state.json", "w"))
rnd()
rnd()
check(B.positions.get("0050") == 0 and bot(key) == 0.0,
      f"the exit sells them — never a write-off with the shares still held ({B.positions.get('0050')})")

print("== live → simulation: two books, never one (review 2026-10-25)")
fresh()
signal(1.0)
config({"tw_a": 250_000})
rnd()
env_live = venue_wiring.read_env()
check(portfolio.book_account_check(env_live, "sinopac")[0] == "ok" and bot() == 1250.0,
      "the live book is recorded against the live account")
from manager import sinopac_setup  # noqa: E402  (chdirs to the repo root on import)
os.chdir(WS)
sinopac_setup._need_tty = lambda what: None
import builtins  # noqa: E402
answers = iter(["yes"])
real_input, builtins.input = builtins.input, lambda prompt="": next(answers)
try:
    rc = sinopac_setup.cmd_live(["off"])
finally:
    builtins.input = real_input
env_sim = venue_wiring.read_env()
check(rc == 0 and env_sim.get("SINOPAC_LIVE") == "false" and env_sim.get("SINOPAC_BOUND_TS")
      and os.path.exists("state/HALT"),
      "live off: asked first (the bot holds live shares), paused trading, mode + bind stamp written")
verdict, detail = portfolio.book_account_check(env_sim, "sinopac")
check(verdict == "reset" and bot() == 0.0 and B.positions["0050"] == 1250,
      f"the account guard reads another account: the bot's book restarts empty, the real shares "
      f"are not touched ({verdict})")

ss.reset()
print("\n" + ("all ok" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
