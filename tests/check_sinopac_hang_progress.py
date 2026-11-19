# AutoTradeSys fork addition (2026-11-20)
"""A SinoPac stock leg that waits for its end keeps the reconciler's hang watch quiet.

Upstream 0.1.57's hang watch (runtime/hang_watch.py) kills a reconciler whose progress stamp
(state/heartbeat/reconciler_progress) has not moved for HANG_STALL_S, sized for ~120 s legs. A
SinoPac board-lot leg sent in the 13:25 closing auction waits for the 13:30 print plus
AUCTION_GRACE_S, then a cancel; an odd lot sent before 09:10 waits for the first match. Both pass
240 s with the broker answering every poll. lib/order_sinopac._settle_leg touches the stamp on each
poll that came back — but only in the process that wrote it (the reconciler): flatten or an agent
turn using the lib never hides a stalled reconciler.

1. The path is the reconciler's and the hang watch's.
2. Own stamp moved; another pid's left alone; a stamp replaced by a new reconciler is re-read;
   no stamp → nothing created; an unreadable stamp → left alone.
3. _settle_leg over a closing-auction-length wait (fake clock, fake broker answering each poll):
   the stamp is never older than one poll when the watch looks, and the leg's result is unchanged.
4. A broker poll that never returns: no touch (the watch still sees the hang).
5. No wait longer than the watch in the lib's own constants, apart from the polled settle loop.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_hang_progress.py
"""
import json
import os
import re
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.modules.setdefault("shioaji", types.ModuleType("shioaji"))

from lib import order_sinopac as o  # noqa: E402
import hang_watch  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  → {detail}"))
    if not cond:
        fails += 1


# 1 ─ the same file the reconciler stamps and the watch reads
src = open(os.path.join(ROOT, "manager", "reconciler.py"), encoding="utf-8").read()
m = re.search(r"^PROGRESS_PATH = Path\('([^']+)'\)", src, re.M)
check("1 path = manager/reconciler.PROGRESS_PATH",
      m is not None and os.path.normpath(m.group(1)) == os.path.normpath(o._PROGRESS_PATH), m and m.group(1))
check("1 path = runtime/hang_watch.PROGRESS",
      os.path.normpath(hang_watch.PROGRESS) == os.path.normpath(o._PROGRESS_PATH), hang_watch.PROGRESS)

WS = tempfile.mkdtemp(prefix="sinopac-hang-")
os.chdir(WS)  # the reconciler runs with the workspace as its cwd
os.makedirs(os.path.join("state", "heartbeat"))
P = o._PROGRESS_PATH
OLD = 1_000_000.0


def write_stamp(pid):
    tmp = P + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "ppid": 1, "at": time.time(), "v": 1}, f)
    os.replace(tmp, P)
    os.utime(P, (OLD, OLD))


# 2 ─ whose stamp
write_stamp(os.getpid())
o._touch_progress()
check("2 own stamp moved", os.path.getmtime(P) > OLD + 1, os.path.getmtime(P))
write_stamp(os.getpid() + 7)
o._touch_progress()
check("2 another process's stamp (a reconciler, this is flatten) left alone", os.path.getmtime(P) == OLD)
write_stamp(os.getpid())
o._touch_progress()
check("2 stamp replaced again by this process → moved", os.path.getmtime(P) > OLD + 1)
os.remove(P)
o._touch_progress()
check("2 no stamp → none created", not os.path.exists(P))
with open(P, "w", encoding="utf-8") as f:
    f.write("{half")
os.utime(P, (OLD, OLD))
o._touch_progress()
check("2 unreadable stamp → left alone, no raise", os.path.getmtime(P) == OLD)

# 3 ─ a closing-auction wait: 13:25:00 → print at 13:30 + AUCTION_GRACE_S, then a cancel
write_stamp(os.getpid())
clock = {"t": 0.0}
real = {k: getattr(o, k) for k in ("_refresh", "_normalize", "_read_api", "POLL_S")}
real_mono, real_sleep = o.time.monotonic, o.time.sleep
wait_s = 5 * 60 + o.AUCTION_GRACE_S
fill_at = wait_s - 3          # the auction prints inside the window
polls, worst, last_touch = [0], [0.0], [None]


def fake_refresh(env, trade):
    polls[0] += 1
    return trade


def fake_normalize(trade, mult=1):
    done = clock["t"] >= fill_at
    return {"status": "Filled" if done else "Submitted", "order_qty": 2, "filled_qty": 2 if done else 0,
            "cancel_qty": 0, "seqno": "S1"}


def fake_sleep(s):
    # the watch's view: how long since the stamp last moved, measured on the fake clock
    m_now = os.path.getmtime(P)
    if last_touch[0] is None or m_now != last_touch[0][0]:
        last_touch[0] = (m_now, clock["t"])
    worst[0] = max(worst[0], clock["t"] + s - last_touch[0][1])
    clock["t"] += s


try:
    o._refresh, o._normalize, o.POLL_S = fake_refresh, fake_normalize, 5.0
    o.time.monotonic, o.time.sleep = (lambda: clock["t"]), fake_sleep
    os.utime(P, (OLD, OLD))
    res = o._settle_leg({}, object(), 1000, wait_s)
finally:
    for k, v in real.items():
        setattr(o, k, v)
    o.time.monotonic, o.time.sleep = real_mono, real_sleep
check("3 the leg ran past the watch's threshold", clock["t"] > hang_watch.HANG_STALL_S, clock["t"])
check("3 leg result unchanged (Filled)", res.get("status") == "Filled", res)
check("3 the stamp never stood still longer than one poll",
      worst[0] <= 5.0 + 0.001 and worst[0] < hang_watch.HANG_STALL_S, worst[0])
check("3 one touch per answered poll", os.path.getmtime(P) > OLD + 1 and polls[0] > 1, polls[0])

# 4 ─ a poll that never returns: _refresh raises the way a dead session would hang — no touch happens
write_stamp(os.getpid())


def dead_refresh(env, trade):
    raise TimeoutError("broker never answered")


try:
    o._refresh = dead_refresh
    try:
        o._settle_leg({}, object(), 1000, 1.0)
    except TimeoutError:
        pass
finally:
    o._refresh = real["_refresh"]
check("4 a broker call that never answers moves nothing", os.path.getmtime(P) == OLD)

# 5 ─ the lib's other waits stay under the watch (confirm_order's default timeout, IOC, odd lot, cancel)
import inspect  # noqa: E402

confirm_default = inspect.signature(o.confirm_order).parameters["timeout"].default
short = {"IOC_WAIT_S": o.IOC_WAIT_S, "ODD_WAIT_S + CANCEL_WAIT_S": o.ODD_WAIT_S + o.CANCEL_WAIT_S,
         "confirm_order timeout": confirm_default}
check("5 waits without a touch stay under HANG_STALL_S",
      all(v < hang_watch.HANG_STALL_S for v in short.values()), short)

print("all passed" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
