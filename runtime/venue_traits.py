# Modified by Mephisto-000 on 2026-10-25: sinopac (永豐金) is auto-wired as a TW-stock spot venue
#   (new trait tw_stock_spot); runtime/venue_traits.py carries the same bytes.
#   (2026-11-18) upstream c1db277b turned this row into its gated-off 永豐 futures row
#   (verified_modes (), bound_marker, cred_env); the fork keeps its TW-stock row instead.
#   The row declares upstream's crypto gate cells as not compared (instrument_class None).
#   (2026-11-28) upstream 0.1.61 opened its futures row (verified_modes futures, hand_wired, cred_env,
#   bound_marker); the fork still keeps the TW-stock row and _SINOPAC_MODES = ().
# Original work: Copyright 2025-2026 WuChi Technology Company Limited
# Licensed under the Apache License, Version 2.0
"""Which venues break the crypto auto-wire contract, and how.

Every branch in manager/, lib/ and runtime/ that behaves differently for a
Taiwan broker asks this table instead of comparing a venue id string, so
wiring in another broker is one row here plus its own libs — not a hunt
through the reconciler, flatten and the runtime for `== "capital"`.
tests/check_venue_traits.py fails on a bare venue-id literal outside this
file, the venue's own libs, and runtime/venue_traits.py (a verbatim copy:
the runtime ships on its own channel and may sit on an older workspace).

A missing trait means the crypto default (auto-wired, perp, sized in
account currency). Trait meanings:
  auto_wire          False: lib.venue_wiring never routes it (signed-diff
                     contract; the reconciler or nothing handles it)
  hand_wired         manager/reconciler.py routes get_positions/place_order
                     to this venue's own block when a strategy is bound to it
  native_units       rows are diffed in lots, not account currency
  perp               False: manager/close_symbol.py refuses it
  windows_identity   only a password-logon Windows Administrator can log in
                     to it: flatten skips it under any other identity, the
                     report's can_flatten says so, the reconciler service
                     runs as Administrator
  resolved_contracts positions come back as root+YYMM contract codes
                     (TM2610) that flatten maps to the book key (TMF)
  lots_close_partial flatten closes its lots through close_position_partial
                     (not place_contract_market_order)
  close_needs_fill   flatten books a close as done only on a confirmed fill
  snapshot_settle_wait  the worker's position snapshot lags an order sent on
                     this machine: flatten reads it only once a read started
                     lib.<venue>_vault.ORDER_SETTLE_S after the last send
                     (last_order_at on the vault, else on lib.order_<venue>)
  tw_stock_spot      TW stocks routed here are cash shares, like on paper:
                     spot keys, never short, held as is while the TWSE
                     session is shut (lib.portfolio, lib.execute)
  bound_marker       a workspace-relative file only this venue's own bind leaves, never
                     removed: without it the venue's keys are left over from before
                     (dormant()) — never read by runtime/account_reader, never flattened
  reference          the onboarding doc chat binding points to
  label              the broker's name in user-facing messages
  verified_modes     the account types whose real-account run passed (Bitget:
                     "uta" / "classic"). Declared only by a venue whose libs ship
                     ahead of that run (venue-onboarding §3). Empty = unverified:
                     never auto-wired, never read by runtime/account_reader, not
                     bindable from chat, and the venue's own libs sign nothing.
                     Non-empty: the venue wires, and its libs refuse a key whose
                     account is of a type not listed (bind and every read say
                     so). The libs read the raw cell (verified_modes()), so a
                     deleted row or cell stays closed. Filled in by the backend in
                     the commit that merges the verified libs.

Crypto cells, read by lib.venue_wiring.instrument_gate / kline_venue. Every crypto
venue with a lib/order_<id>.py declares the two gate cells explicitly
(tests/check_crypto_venue_traits.py), so a venue left out of a check says why here:
  instrument_class   which classes its get_contract_rules "category" reports, compared
                     with Binance's underlyingType before an entry on Binance bars:
                     "coin_stock_commodity" (all three), "stock" (only a stock is
                     citable; anything else falls back to the coin-vs-US-stock mirror
                     on "equity"), None (not compared)
  binance_name_gate  an entry on Binance bars into a ticker Binance does not list is
                     refused: this venue names multiplied coins per coin (PEPEUSDT)
                     where Binance's bars are per 1000 (1000PEPEUSDT)
  native_kline       the lib.data fetcher that reads this venue's own contract (a
                     strategy only on it is not compared with Binance)
"""

import os

CAPITAL = "capital"
PRESIDENT = "president"
SINOPAC = "sinopac"

# AutoTradeSys fork: upstream opened its 永豐 futures gate here (_SINOPAC_MODES = ("futures",), 0.1.61);
# the fork keeps it shut — `sinopac` is the fork's TW-stock venue. runtime/sinopac_connect.workspace_open
# and the tests read this line as text; the row below carries no verified_modes on purpose.
_SINOPAC_MODES = ()

TRAITS = {
    CAPITAL: {
        "auto_wire": False,
        "hand_wired": True,
        "native_units": True,
        "perp": False,
        "windows_identity": True,
        "resolved_contracts": True,
        "lots_close_partial": True,
        "close_needs_fill": True,
        "snapshot_settle_wait": True,
        "reference": "references/capital-broker.md",
        "label": "群益",
    },
    # auto-wired (lib/venue_wiring) through its spot layer: lib/order_sinopac + lib/account_sinopac
    # (AutoTradeSys fork). Upstream's futures cells are left out on purpose: verified_modes () /
    # bound_marker would make account_reader and flatten skip these stocks (dormant()), and cred_env
    # would change which SINOPAC_* lines a rebind evicts and _env_flags reads.
    SINOPAC: {
        "perp": False,
        "tw_stock_spot": True,
        "reference": "references/sinopac-broker.md",
        "label": "永豐金",
        # auto-wired, so tests/check_crypto_venue_traits.py asks for the two gate cells: TW stocks are
        # spot keys on TW stock bars, never compared with Binance (the gate skips spot anyway)
        "instrument_class": None,
        "binance_name_gate": False,
    },
    # real-account runs passed on a classic account (2026-10-22, both position modes) and a UTA
    # (T1–T12; T11c's stop-loss re-run 2026-10-26)
    "bitget": {
        "verified_modes": ("classic", "uta"),
        "reference": "references/exchange-connect.md",
        "label": "Bitget",
        # v3 symbolType / instrumentType stock|etf (lib/stock_perps.bitget_is_stock). Its
        # metal class covers PAXGUSDT / XAUTUSDT, which Binance lists as coins (2026-10-28)
        "instrument_class": "stock",
        # multiplied-coin names not in references/lib.md's table: unverified, not gated
        "binance_name_gate": False,
    },
    # instCategory 1 crypto / 3 stocks / 4 commodities (measured 2026-11-14); PEPE-USDT-SWAP
    # is per coin where Binance has 1000PEPEUSDT (references/lib.md, multiplied contracts)
    "okx": {"label": "OKX", "native_kline": "fetch_okx_kline",
            "instrument_class": "coin_stock_commodity", "binance_name_gate": True},
    # contract_type "stocks" (lib/order_gateio). Its "metals" covers PAXG_USDT, a coin on
    # Binance (2026-10-19). Name gate off until Gate.io has its own kline in lib.data: PEPE_USDT
    # is per coin (references/lib.md), but refusing it — and every Gate-only coin or stock perp
    # Binance does not list — would leave no bars to move to
    "gateio": {"label": "Gate.io", "instrument_class": "stock", "binance_name_gate": False},
    # symbolType stock / ETF (references/stock-perps.md); no commodity value verified.
    # Name gate off: SHIB1000USDT is Binance's 1000SHIBUSDT spelled otherwise (a name check
    # would refuse a matching contract); 10000SATSUSDT vs Binance 1000SATSUSDT is a real
    # 10x gap this leaves ungated (references/lib.md, multiplied contracts)
    "bybit": {"label": "Bybit", "instrument_class": "stock", "binance_name_gate": False},
    # stock swaps are NCSK… names only lib/stock_perps maps to, never a coin's; own bars
    "bingx": {"label": "BingX", "native_kline": "fetch_bingx_kline",
              "instrument_class": None, "binance_name_gate": False},
    # no class field read by its libs or documented (references/stockcoin-skill.md):
    # unverified, not compared
    "stockcoin": {"label": "StockCoin", "instrument_class": None, "binance_name_gate": False},
    # the data source itself
    "binance": {"label": "Binance", "instrument_class": None, "binance_name_gate": False},
    # the simulator: no venue contract to compare with
    "paper": {"instrument_class": None, "binance_name_gate": False},
    PRESIDENT: {
        "auto_wire": False,
        "hand_wired": True,
        "native_units": True,
        "perp": False,
        "close_needs_fill": True,
        "snapshot_settle_wait": True,
        "reference": "references/president-broker.md",
        "label": "統一期貨",
        # the five names bound machines already use are locked; the last two
        # switch to production
        "cred_env": {
            "president_account": "API_KEY",
            "president_password": "PASSWORD",
            "president_test_url": "EXTRA",
            "president_ca_path": "EXTRA",
            "president_ca_password": "EXTRA",
            "president_url": "EXTRA",
            "president_live": "EXTRA",
        },
    },
}

_DEFAULTS = {"auto_wire": True, "perp": True}


def get(venue, trait):
    # exact id match, no case folding: the branches this replaced compared == "capital"
    row = TRAITS.get(venue, {}) if isinstance(venue, str) else {}
    return row.get(trait, _DEFAULTS.get(trait, False))


def has(venue, trait):
    return bool(get(venue, trait))


def venues(trait, value=True):
    """Venue ids whose `trait` equals `value` (defaults applied)."""
    return frozenset(v for v in TRAITS if get(v, trait) == value)


def verified_modes(venue):
    """The account types a venue's own libs may trade (raw cell: a venue whose row has no
    verified_modes gets () here — its libs stay shut). Only those libs ask this."""
    row = TRAITS.get(venue, {}) if isinstance(venue, str) else {}
    return tuple(row.get("verified_modes") or ())


def unverified():
    """Venue ids that declare verified_modes and have none yet: kept off every surface. A
    venue without the cell (every venue that shipped verified, an agent-written lib)
    is not in it."""
    return frozenset(v for v, t in TRAITS.items() if "verified_modes" in t and not t["verified_modes"])


def dormant(workspace):
    """Venue ids nothing reads or flattens in `workspace`: unverified() ones, and a venue whose
    bound_marker file is not there."""
    return unverified() | frozenset(
        v for v, t in TRAITS.items()
        if t.get("bound_marker") and not os.path.exists(os.path.join(workspace, t["bound_marker"])))


def cred_env(name):
    """(VENUE_ID, role) when `name` is one of a venue's own cred_env names
    (case-insensitive), else None."""
    n = str(name or "").strip().casefold()
    for v, t in TRAITS.items():
        role = (t.get("cred_env") or {}).get(n)
        if role:
            return v.upper(), role
    return None


def hand_wired_routed(exchanges):
    """The first hand-wired venue among `exchanges` (portfolio_config's
    strategy -> venue values), or None."""
    for v in exchanges or ():
        if has(v, "hand_wired"):
            return v
    return None
