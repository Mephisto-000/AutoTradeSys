# AutoTradeSys fork addition (2026-10-25)
"""lib/order_sinopac.py — the SinoPac spot layer the reconciler trades TW stocks
through, against an offline Shioaji stand-in (tests/sinopac_fake.py):

  - a share count splits into board lots (IOC limit) + an odd-lot remainder
    (intraday odd lot, ROD limit), enums never strings, prices protected on the
    tick grid and inside limit-up / limit-down;
  - a live buy never exceeds settlement cash (T+2: a buy the bank account
    cannot settle is a default) — pending settlements count as owed;
  - only exchange-confirmed fills are returned; nothing filled raises (never
    False, which the auto-wire would book as an unsellable remainder);
  - a leg whose end cannot be seen trips HALT;
  - HALT / the restart stop refuse before the broker session is opened;
  - simulation trades whole board lots only (Shioaji's simulation has no odd lots);
  - the legacy after-hours odd-lot helper still sends Odd + MKT + ROD.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_spot_layer.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="sinopac-spot-")
os.environ["BLAVE_AGENT_HOME"] = os.environ["BLAVECLAW_HOME"] = WS  # notify: log-only
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(WS)
os.makedirs("state", exist_ok=True)

import sinopac_fake  # noqa: E402

B = sinopac_fake.install()
from lib import guard, reject_token  # noqa: E402
from lib import order_sinopac as o  # noqa: E402
from lib import sinopac_session as ss  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


KEY, SEC = "k" * 32, "s" * 32
SIM = {"sinopac_api_key": KEY, "sinopac_secret_key": SEC}
LIVE = dict(SIM, SINOPAC_LIVE="true", sinopac_ca_path="/x/Sinopac.pfx", sinopac_ca_passwd="pw123456")
NOW = [datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)]
SESSION = [True]
ss.now_taipei = lambda: NOW[0]
o._session_open = lambda env, now: SESSION[0]
o.POLL_S = 0.0
o.ODD_WAIT_S = 0.05
o.CANCEL_WAIT_S = 0.05
o.IOC_WAIT_S = 0.05


def fresh(**knobs):
    B.reset()
    B.quote("0050", 200.0, bid=199.5, ask=200.0, reference=198.0)
    B.quote("2330", 1000.0, bid=995.0, ask=1000.0, reference=1000.0)
    for k, v in knobs.items():
        setattr(B, k, v)
    ss.reset()
    o._px_cache.clear()
    guard.release_memory_halt()  # a HALT this test tripped stays in-process otherwise
    for p in ("state/HALT", "state/reconciler_stopped.json", "state/audit.jsonl",
              "state/sinopac_day_buys.json"):
        if os.path.exists(p):
            os.remove(p)


def placed():
    return [(c, od.action.value, od.quantity, od.price, od.price_type.value, od.order_type.value,
             od.order_lot.value, od.order_cond.value, od.custom_field) for c, od in B.placed]


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except Exception as e:  # noqa: BLE001 — the test reads the type
        return e


# ── helpers ──────────────────────────────────────────────────────────────────
print("== protected prices sit on the TWSE tick grid, inside the day's limits")
pp = o.protected_price
check([pp("buy", 49.98), pp("buy", 99.96), pp("sell", 100.2), pp("sell", 10.03), pp("buy", 1234)]
      == [50.5, 101.0, 99.1, 9.92, 1250.0],
      "±1% then rounded away from the market on the band's own tick (50.5 / 101 / 99.1 / 9.92 / 1250)")
check(pp("buy", 200, limit_up=201.0) == 201.0 and pp("sell", 200, limit_down=199.5) == 199.5,
      "clamped to limit-up / limit-down")
cid = "rc251027100000000001"
check(o._tag(cid, "L") == o._tag(cid, "L") and o._tag(cid, "L") != o._tag(cid, "O")
      and len(o._tag(cid, "L")) == 6 and o._tag(cid, "L")[0] == "b"
      and len({o._tag(f"rc{i}", "L") for i in range(5000)}) == 5000,
      "leg tags: 6 chars, 'b' + 5 base36 of hash(id, leg) — stable, distinct per leg, no clash in 5,000")
check(ss.enum_value(sinopac_fake.OrderStatus.Filled) == "Filled"
      and str(sinopac_fake.OrderStatus.Filled) == "OrderStatus.Filled",
      "1.7 enums print 'OrderStatus.Filled' — the lib reads .value")

# ── live buy: board lots + odd lot ──────────────────────────────────────────
print("== live buy of 250,000 TWD of 0050 at 200: 1 board lot (IOC) + 250 odd shares (ROD)")
fresh()
r = o.place_spot_market_order(LIVE, "0050", "buy", quote_qty=250_000, client_order_id="rc1")
p = placed()
check(len(p) == 2 and p[0][1:] == ("Buy", 1, 202.0, "LMT", "IOC", "Common", "Cash", o._tag("rc1", "L"))
      and p[1][1:] == ("Buy", 250, 202.0, "LMT", "ROD", "IntradayOdd", "Cash", o._tag("rc1", "O")),
      f"two enum-built limit orders at the protected 202 ({p})")
check(r["executed_qty"] == 1250.0 and r["status"] == "filled" and abs(r["avg_price"] - 200.0) < 1e-9
      and r["commission_asset"] == "TWD" and r["exchange"] == "sinopac" and r["simulation"] is False,
      f"1,250 shares confirmed at 200, fee in TWD ({ {k: r[k] for k in ('executed_qty', 'status', 'avg_price')} })")
check(B.ca_calls and B.ca_calls[0][1] == "A123456789",
      "live: CA activated after login with the account's own person_id")
audit = [json.loads(l) for l in open("state/audit.jsonl")]
check([a["event"] for a in audit].count("order_attempt") == 2 and audit[-1]["event"] == "order_ok",
      "every leg audited, the outcome too")

print("== the cash check: pending settlements count as owed, whatever their sign")
fresh(cash=100_000.0, settlements=[("2026-10-27", 0, 0.0), ("2026-10-28", 1, -30_000.0),
                                    ("2026-10-29", 2, 20_000.0)])
r = o.place_spot_market_order(LIVE, "0050", "buy", quote_qty=200_000, client_order_id="rc2")
afford = int((100_000 - 50_000 - 40) // (202.0 * (1 + o.FEE_RATE + o.CASH_BUFFER)))
check(r["orig_qty"] == afford and r["executed_qty"] == afford,
      f"buy trimmed to {afford} shares (cash 100,000 − 50,000 pending)")
fresh(cash=150.0)
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", quote_qty=50_000, client_order_id="rc3")
check(isinstance(e, ss.SinopacError) and str(e).startswith("[order_reject:insufficient_margin]")
      and not B.placed, f"not one share affordable → refused before any order ({e})")

print("== simulation: whole board lots only")
fresh()
r = o.place_spot_market_order(SIM, "0050", "buy", quote_qty=250_000, client_order_id="rc4")
check([x[6] for x in placed()] == ["Common"] and r["executed_qty"] == 1000.0 and r["simulation"],
      "1 lot sent, the 250-share remainder not (no odd lots in Shioaji's simulation)")
fresh()
check(o.place_spot_market_order(SIM, "0050", "buy", quote_qty=50_000, client_order_id="rc5") is False
      and not B.placed, "under one lot in simulation → False, nothing sent")
check(o.format_spot_qty(SIM, "0050", 1500) == "1000" and o.format_spot_qty(LIVE, "0050", 1500.7) == "1500"
      and o.format_spot_qty(LIVE, "0050", 0.4) == "", "format_spot_qty: lots in simulation, shares live")

# ── sells ────────────────────────────────────────────────────────────────────
print("== sell 1,300.9 shares: floored to 1,300 = 1 lot + 300 odd, protected below the bid")
fresh(positions={"0050": 5000})
r = o.place_spot_market_order(LIVE, "0050", "sell", base_qty=1300.9, client_order_id="rc6")
p = placed()
check([(x[1], x[2], x[3], x[6]) for x in p] == [("Sell", 1, 197.5, "Common"), ("Sell", 300, 197.5, "IntradayOdd")]
      and r["executed_qty"] == 1300.0 and B.positions["0050"] == 3700,
      f"sold 1,300 at limit 197.5 (bid 199.5 − 1%) ({p})")
check(o.place_spot_market_order(LIVE, "0050", "sell", base_qty=0.6, client_order_id="rc7") is False,
      "under one share → False, nothing sent")

# ── partial and missing fills ────────────────────────────────────────────────
print("== IOC partial / odd lot that never fills / nothing fills")
fresh(board_fill="partial", cash=10_000_000.0)
r = o.place_spot_market_order(LIVE, "2330", "buy", base_qty=4000, client_order_id="rc8")
check(r["executed_qty"] == 2000.0 and r["status"] == "partially_filled",
      f"IOC 4 lots, 2 filled, the rest cancelled by the exchange → 2,000 shares reported ({r['executed_qty']})")
fresh(odd_fill="never")
r = o.place_spot_market_order(LIVE, "0050", "buy", base_qty=1500, client_order_id="rc9")
check(r["executed_qty"] == 1000.0 and len(B.cancels) == 1 and r["legs"][1]["status"] == "Cancelled",
      "odd lot unfilled in its wait → cancelled, confirmed; the board lot still reported")
fresh(odd_fill="partial")
r = o.place_spot_market_order(LIVE, "0050", "buy", base_qty=300, client_order_id="rc10")
check(r["executed_qty"] == 150.0 and r["legs"][0]["status"] == "Cancelled",
      "odd lot half filled then cancelled → the 150 that filled")
fresh(board_fill="none")
e = raises(o.place_spot_market_order, LIVE, "2330", "sell", base_qty=1000, client_order_id="rc11")
check(isinstance(e, o.NoFill), f"nothing filled → NoFill raised, never False ({type(e).__name__})")
fresh(fail_msg="集保賣出餘股數不足")
e = raises(o.place_spot_market_order, LIVE, "0050", "sell", base_qty=1000, client_order_id="rc12")
check(isinstance(e, ss.SinopacError) and "集保賣出餘股數不足" in str(e),
      f"a broker rejection surfaces its message ({e})")

print("== a leg whose end cannot be seen trips HALT")
fresh(odd_fill="never", cancel_confirms=False)
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=500, client_order_id="rc13")
check(isinstance(e, o.OrderNotConfirmed) and os.path.exists("state/HALT"),
      "odd-lot cancel never confirmed, nothing filled → OrderNotConfirmed + HALT")
fresh(odd_fill="never", cancel_confirms=False)
r = o.place_spot_market_order(LIVE, "0050", "buy", base_qty=1500, client_order_id="rc14")
check(r["executed_qty"] == 1000.0 and os.path.exists("state/HALT")
      and any("unknown" in x for x in r.get("errors", [])),
      "board lot filled, odd lot lost → the fill is reported AND HALT is set")
fresh(place_raises=sinopac_fake.OrderOutcomeUnknownError("timeout"), place_raises_after=True)
r = o.place_spot_market_order(LIVE, "0050", "buy", base_qty=1000, client_order_id="rc15")
check(r["executed_qty"] == 1000.0 and not os.path.exists("state/HALT"),
      "place_order outcome unknown but the order is on the book (by its tag) → followed to its fill")
fresh(place_raises=sinopac_fake.OrderOutcomeUnknownError("timeout"))
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=1000, client_order_id="rc16")
check(isinstance(e, o.OrderNotConfirmed) and os.path.exists("state/HALT"),
      "outcome unknown and not on the book → OrderNotConfirmed + HALT")

print("== a reply lost after the order may have left (review 2026-10-25)")
fresh(place_raises=sinopac_fake.ResponseError("reply lost"), place_raises_after=True)
r = o.place_spot_market_order(LIVE, "0050", "buy", base_qty=1250, client_order_id="rc30")
check(r["executed_qty"] == 1250.0 and B.positions["0050"] == 1250 and not os.path.exists("state/HALT"),
      f"any error out of place_order: looked up by its tag, the landed order followed ({r['executed_qty']})")
fresh(place_raises=sinopac_fake.ResponseError("reply lost"))
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=1250, client_order_id="rc31")
check(isinstance(e, o.OrderNotConfirmed) and os.path.exists("state/HALT") and len(B.placed) == 1,
      "not found by its tag → outcome unknown: HALT, and no odd-lot order after it")
fresh(place_raises=ValueError("bad price"))
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=1000, client_order_id="rc32")
check(isinstance(e, ValueError) and not os.path.exists("state/HALT"),
      "an SDK argument error (raised before sending) stays a plain failure, no HALT")

print("== a board lot whose end is unknown blocks the odd-lot order")
fresh(cash=10_000_000.0, odd_fill="never", cancel_confirms=False)
NOW[0] = datetime(2026, 10, 27, 13, 26, tzinfo=ss.TAIPEI)
o.AUCTION_GRACE_S = -1e6
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=1500, client_order_id="rc33")
o.AUCTION_GRACE_S = 40
check(isinstance(e, o.OrderNotConfirmed) and len(B.placed) == 1 and os.path.exists("state/HALT"),
      f"auction lot unconfirmed at 13:26 → HALT, the 500 odd shares never sent ({len(B.placed)} order)")

print("== after the session's last match a silent cancel is not an unknown outcome")
fresh(odd_fill="never", cancel_confirms=False)
NOW[0] = datetime(2026, 10, 27, 13, 33, tzinfo=ss.TAIPEI)
trade = o._send_order(LIVE, "0050", "Buy", 10, "IntradayOdd", "LMT", 202.0, "ROD", "bzzzzz",
                      "entry", {"symbol": "0050"})
res = o._settle_leg(LIVE, trade, 1, 0)
check(res["status"] == "Expired" and not res.get("unconfirmed"),
      f"13:33: the remainder is final (no later match), no HALT ({res['status']})")
NOW[0] = datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)

print("== today's buys count against settlement cash (T+2: the balance has not moved yet)")
fresh(cash=500_000.0, cash_moves=False)
if os.path.exists(o.DAY_BUYS_PATH):
    os.remove(o.DAY_BUYS_PATH)
r1 = o.place_spot_market_order(LIVE, "0050", "buy", quote_qty=250_000, client_order_id="rc34")
r2 = o.place_spot_market_order(LIVE, "0050", "buy", quote_qty=300_000, client_order_id="rc35")
spent = r1["quote_qty"] * (1 + o.FEE_RATE)
afford = int((500_000 - spent - 40) // (202.0 * (1 + o.FEE_RATE + o.CASH_BUFFER)))
check(r1["executed_qty"] == 1250.0 and r2["orig_qty"] == afford,
      f"the second buy is capped by what is left after the first ({r2['orig_qty']} == {afford})")

print("== suffixed codes read the same holdings")
fresh(positions={"0050": 1500, "6488": 200})
bal = o.get_spot_balances(SIM)
check(bal.get("0050.TW") == 1500 and bal.get("6488.TWO") == 200 and bal["0050"] == 1500
      and "0050.TW" in bal, "get_spot_balances answers '0050.TW' / '6488.TWO' as their bare code")


# ── guards ───────────────────────────────────────────────────────────────────
print("== HALT, the restart stop and a closed session refuse before any login")
fresh()
guard.trip_halt("test", "test")
for side, kw in (("buy", {"quote_qty": 100_000}), ("sell", {"base_qty": 1000})):
    e = raises(o.place_spot_market_order, LIVE, "0050", side, client_order_id="rc17", **kw)
    check(isinstance(e, guard.Halted) and B.logins == 0 and not B.placed,
          f"HALT: {side} refused, no login, nothing sent")
with guard.halt_close_pass("0050@spot", "test"):
    B.positions["0050"] = 1000
    r = o.place_spot_market_order(LIVE, "0050", "sell", base_qty=1000, client_order_id="rc18")
check(r["executed_qty"] == 1000.0, "the user's close pass lets a sell through under HALT")
fresh()
json.dump({"ts": 1}, open("state/reconciler_stopped.json", "w"))
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", quote_qty=100_000, client_order_id="rc19")
check(isinstance(e, guard.Halted) and B.logins == 0, "after a machine restart: refused before the login")
fresh()
SESSION[0] = False
e = raises(o.place_spot_market_order, LIVE, "0050", "sell", base_qty=1000, client_order_id="rc20")
check(type(e).__name__ == "PaperMarketClosed" and not B.placed,
      "TWSE shut → PaperMarketClosed (flatten defers on that name), nothing sent")
SESSION[0] = True

print("== untradeable stocks and unknown codes")
fresh(info_extra={"0050": {"disposition_prepay_ratio": 1.0}})
e = raises(o.place_spot_market_order, LIVE, "0050", "buy", quote_qty=100_000, client_order_id="rc21")
check(isinstance(e, ss.SinopacError) and "處置股" in str(e) and not B.placed, "a disposition stock needing prepayment is refused")
fresh(unknown={"9999"})
e = raises(o.place_spot_market_order, LIVE, "9999", "buy", quote_qty=100_000, client_order_id="rc22")
check(isinstance(e, ss.SinopacError) and str(e).startswith("[order_reject:symbol_unavailable]"),
      f"unknown code → symbol_unavailable token ({e})")

print("== timing: the closing auction and the first odd-lot match")
fresh(cash=10_000_000.0)
NOW[0] = datetime(2026, 10, 27, 13, 26, tzinfo=ss.TAIPEI)
o.AUCTION_GRACE_S = -1e6  # don't really wait for 13:30 here: cancelled at once, NoFill
raises(o.place_spot_market_order, LIVE, "2330", "buy", base_qty=1000, client_order_id="rc23")
check(placed() and placed()[0][5] == "ROD" and placed()[0][6] == "Common",
      "13:25–13:30: the board lot goes into the closing auction as ROD (IOC is not taken there)")
o.AUCTION_GRACE_S = 40
seen = []
real_settle = o._settle_leg
o._settle_leg = lambda env, trade, mult, wait_s: seen.append(round(wait_s)) or real_settle(env, trade, mult, 0)
fresh()
NOW[0] = datetime(2026, 10, 27, 9, 2, tzinfo=ss.TAIPEI)
o.ODD_WAIT_S = 45
raises(o.place_spot_market_order, LIVE, "0050", "buy", base_qty=10, client_order_id="rc24")
check(seen == [8 * 60 + 45], f"an odd lot sent at 09:02 waits for the 09:10 match + 45 s ({seen})")
o._settle_leg = real_settle
o.ODD_WAIT_S = 0.05
NOW[0] = datetime(2026, 10, 27, 10, 0, tzinfo=ss.TAIPEI)

# ── reads ────────────────────────────────────────────────────────────────────
print("== reads")
fresh(positions={"0050": 1500, "00679B": 3000})
B.quote("00679B", 30.0)
bal = o.get_spot_balances(SIM)
check(bal == {"0050": 1500, "00679B": 3000}, f"get_spot_balances: shares per code ({bal})")
check(os.path.exists("state/sinopac_account.json"), "…and the account snapshot is refreshed from the same session")
check(o.get_spot_price(SIM, "0050") == 200.0, "get_spot_price: the last trade")
e = raises(o.place_market_order, SIM, "0050", "long", 1)
check(isinstance(e, ss.SinopacError) and "spot" in str(e), "the swap layer refuses: TW stocks are spot only")

print("== legacy after-hours odd-lot helper")
fresh(odd_fill="full")
r = o.place_odd_lot_order(LIVE, "0050", "buy", 10, client_tag="leg1")
p = placed()
check(p and p[0][4:8] == ("MKT", "ROD", "Odd", "Cash") and p[0][8] == "leg1" and r["status"] == "Filled",
      f"Odd + MKT + ROD, enums, confirmed ({p})")
e = raises(o.place_odd_lot_order, LIVE, "0050", "buy", 10, client_tag="leg1")
check(isinstance(e, o.DuplicateOrder), "the same client_tag again today → DuplicateOrder")

ss.reset()
print("\n" + ("all ok" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
