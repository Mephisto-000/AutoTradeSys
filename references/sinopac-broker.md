<!-- Modified by Mephisto-000 on 2026-10-25: rewritten for the AutoTradeSys fork's SinoPac
     integration — auto-wired TW-stock spot venue, user-run setup CLI, SinoPac kbars for backtests.
     Original work: Copyright 2025-2026 WuChi Technology Company Limited; Apache License 2.0 -->
# SinoPac (永豐金) Broker — Agent Reference (AutoTradeSys fork)

Use this document whenever a user asks to connect, check, trade or backtest with SinoPac
(永豐金證券, the Shioaji API). User guide in Chinese: `docs/sinopac.md`.

**What this fork supports:** Taiwan stocks and ETFs as **cash shares (現股)** — board lots
(整股) and intraday odd lots (盤中零股) — traded by the 自動下單 page's reconciler, plus
SinoPac's 1-minute K bars for backtests. **Not supported:** futures/options (no futures order
path — 台指期 goes to 群益 / 統一), margin trading or short selling (融資融券), 盤後零股 in the
reconciler.

**Never hand-write Shioaji calls.** Orders: `lib/order_sinopac.py`. Account reads:
`lib/account_sinopac.py`. Data: `lib/sinopac_data.py`. Login: `lib/sinopac_session.py` (one
session per process). Every rule in *Field-Verified Lessons* below is encoded there.

---

## The user's hands vs. the agent's

| Step | Who | How |
|---|---|---|
| Install the SDK | automatic in this fork's desktop build | the engine installs `shioaji==1.7.9` as its optional package group `sinopac` (shell/main.js `OPTIONAL_DEPS`) on app start; a failure retries next launch. Only the official app (no such group) needs `~/Blave/venv/bin/python -m pip install shioaji==1.7.9` — the user runs it (the agent may show the command) |
| API key + CA certificate | user | SinoPac's API management page (Step 1) |
| Write keys into `.env` | **user only** | the desktop's 選擇下單帳戶 dialog (真實帳戶 → 台股 → 永豐金證券: API key + secret, simulation; the runtime reads the simulation account before writing), or `python3 manager/sinopac_setup.py bind` in a terminal (adds the CA; interactive, never echoes, refuses non-interactive runs) |
| Simulation API test | user | `python3 manager/sinopac_setup.py api-test` |
| Switch to real orders | **user only** | `python3 manager/sinopac_setup.py live on` (types `LIVE` to confirm; trips HALT first) |
| Amounts, 啟動下單, 暫停 | user | the 自動下單 page (deployment redline) |
| Check connection / account / quote | agent or user | `check`, `account`, `quote <code>` subcommands — read-only |

**A key pasted in chat:** do NOT write it anywhere. Tell the user to run `bind` in a terminal
themselves and — because the key passed through chat — to regenerate it on SinoPac's API page
first. `lib.venue.bind` refuses TW brokers; never edit `.env` by hand for SinoPac either.

---

## Step 1 — API key and CA certificate

- API key: https://www.sinotrade.com.tw/newweb/PythonAPIKey/ (新增 API KEY, 2FA). Tick the
  permissions 行情/資料, 帳務, 交易 and 正式環境; an IP restriction is recommended. The Secret
  Key is shown once.
- CA certificate (needed for real orders only): 下載憑證 on the same page → `Sinopac.pfx`. Its
  password defaults to the national ID. A certificate never activated must first be activated
  in SinoPac's own app.
- Terms + API test (required before SinoPac enables real orders): sign the API agreements in
  SinoPac's 簽署中心, then run the simulation test (Step 3). Approval takes ~5 minutes;
  `check` then shows `已簽署 API 條款: True`.

## Step 2 — bind and check

```bash
python3 manager/sinopac_setup.py bind      # API key, secret, optional CA path/password/person id
python3 manager/sinopac_setup.py check     # login, account, CA (live), daily data usage
```

`bind` writes `sinopac_api_key`, `sinopac_secret_key`, `sinopac_ca_path`,
`sinopac_ca_passwd`, optional `sinopac_person_id`, and `SINOPAC_LIVE=false` (simulation), mode
600. It refuses while another venue's key pair is in `.env` (one machine, one trading venue —
unbind on the 自動下單 page first) and adds `sinopac` to `manager/credentials.ui.json` when that
manifest exists. `unbind` removes every `sinopac_*` line.

The desktop's connect dialog (2026-10-26) is the other writer: it sends `SINOPAC_API_KEY` +
`SINOPAC_SECRET_KEY` through the same path as OKX (`venue-connect` → daemon → runtime
`_local_real_key_gate`, which calls `lib.account_sinopac.get_equity` on the simulation account;
no write when that read fails). Env names are matched case-insensitively everywhere, so the two
writers replace each other's lines rather than duplicating them; the page's unbind also removes
the terminal tool's CA / `SINOPAC_LIVE` / `SINOPAC_BOUND_TS` lines. The dialog never takes the
certificate: real orders still need `live on` in a terminal.

## Step 3 — the simulation API test

```bash
python3 manager/sinopac_setup.py api-test   # weekdays 08:00–20:00 (18:00 on: Taiwan IPs only)
```

One board-lot limit buy of 2890 at the day's limit-down in SinoPac's SIMULATION environment
(ignores `SINOPAC_LIVE`), acknowledged, then cancelled. Never real money.

## Step 4 — strategies that trade on SinoPac

- `SYMBOL` / `UNIVERSE`: TWSE / TPEx stock or ETF codes (`"0050"`, `"2330"`, `"00679B"`).
- `MARKET = "spot"` (cash shares). The venue's `tw_stock_spot` trait makes TW stocks spot keys
  on SinoPac whatever `MARKET` says, and a short signal is flat — but declare it so the backtest
  matches (`signal.clip(lower=0)`).
- Type A and Type C both work. `asset_specs` type `shares` / `futures_contracts` are not routed
  here (amounts are TWD notional).
- `self_ledger` (the default) keeps the user's own holdings safe: the bot only ever sells what
  its own book bought. On the first round a Type A strategy's existing holding of its symbol
  may be adopted as the bot's (up to its target — lib.portfolio `_auto_baseline`); a Type C
  member's never is. Tell the user before they start if they already hold the symbol.

## Step 5 — go live

1. Backtest first, and say how it did against its benchmark (AGENTS.md).
2. The user: `live on`, amounts on the 自動下單 page, 啟動下單.
   **Simulation and live are two books.** `live on/off` trips HALT, then writes
   `SINOPAC_LIVE` + `SINOPAC_BOUND_TS`; the new bind stamp makes the reconciler re-run its
   account guard, and `lib/account_sinopac.get_account_id` answers `sim:<id>` in simulation —
   another account to `lib.portfolio.book_account_check`, which restarts the bot's SinoPac
   book. A simulation book is never sold out of the real account. `live off` with live
   positions in the bot's book asks first: after it the bot no longer manages them.
3. Watch the first round: `state/audit.jsonl`, `manager/orders.jsonl`, the page's trade history.

---

## How orders work (`lib/order_sinopac.py` spot layer)

The venue is **auto-wired** (`lib/venue_wiring`) like the paper venue's TW stocks: `.env` keys +
`lib/order_sinopac.py` + `lib/account_sinopac.py` = the bound venue; no reconciler block of its
own. Execution styles: market and TWAP work; chase falls back to market (no limit layer).

- **Session:** while TWSE is shut (outside 09:00–13:30 on a trading day) lib.portfolio holds
  SinoPac's TW keys as they are — no order, no error; the page shows the market closed. A daily
  strategy's evening signal trades on the first round after 09:00. Close-all outside the
  session is deferred to the open (`PaperMarketClosed` → `defer_paper_tw_close`).
- **Sizing:** TWD diff ÷ the best ask (buy) → whole shares; sells come in shares from the
  bot's book. The size gate is ≈1.05 shares (lib.execute).
- **Board lots** (`shares // 1000`): `StockOrderLot.Common`, LMT **IOC** at the protected price;
  13:25–13:30 (closing auction) ROD, cancelled if unfilled after the auction.
- **Odd lots** (`shares % 1000`): `StockOrderLot.IntradayOdd`, LMT **ROD** (the odd-lot market
  takes no market or IOC orders; it matches by call auction every 5 s from 09:10). Unfilled
  after ~45 s (counted from 09:10 when sent earlier) → cancelled; what filled is reported.
- **Price protection:** best ask/bid ± `SINOPAC_MAX_SLIPPAGE` (`.env`, default 0.01 = 1%),
  rounded away from the market on the TWSE tick grid (valid for ETFs too), clamped to
  limit-up / limit-down.
- **Cash check (live buys):** bank balance − every pending settlement (T, T+1, T+2, counted as
  owed whatever the sign) − the bot's own buys today (`state/sinopac_day_buys.json`, in case
  the settlement rows only show them after the close) − fees − 0.5% buffer ÷ the limit price.
  Over it → trimmed; not one share → `[order_reject:insufficient_margin]`. Taiwan cash shares
  settle T+2 and the broker does not check cash at order time: a buy the account cannot settle
  is a default (違約交割).
- **Results:** only exchange-confirmed fills. Nothing filled → `NoFill` (the next round tries
  again); a broker rejection → `SinopacError` with SinoPac's message. Any exception out of
  `place_order` except the SDK's pre-send ones (argument / login / CA / terms errors) may have
  reached the exchange: the order is looked up by its 6-char tag (`custom_field`) and followed;
  not found → **HALT** + `OrderNotConfirmed`, and no further leg is sent. A mid-session cancel
  that never confirms → the same. A remainder still open after 13:32 is final (the session's
  last match is over) and reported `Expired`, not unknown.
- **Simulation** (`SINOPAC_LIVE` not `true`): whole board lots only — Shioaji's simulation has
  no odd lots; a target under one lot does nothing there.
- **Guards:** `_send_order` is the one chokepoint — restart stop, HALT freeze (a user's close
  pass aside), account hold, then the broker; everything lands in `state/audit.jsonl`. One
  spot execution at a time per process.
- **Symbols:** `0050.TW` / `6488.TWO` work like the bare code (holdings answer both forms).
- Disposition stocks that need prepayment (處置股預收) and suspended stocks are refused.

## Account page (`lib/account_sinopac.py`)

`get_equity` = settlement cash + settlements due after today + cash shares at last price (TWD;
the settlement sign is undocumented — the broker convention, negative = payable, is assumed for
this display figure only). `get_positions` is `[]` (no derivative position); `get_holdings` lists
every cash-share holding (the user's too — display only) and the cash. Reads come from
`state/sinopac_account.json`: refreshed by the reconciler's own session each round (≤1/min),
otherwise when older than 5 min (trading day) / 30 min (`SINOPAC_ACCOUNT_TTL_S`). Never one
login per read: the desktop reader runs every minute and SinoPac allows 1,000 logins a day — a
failed refresh is remembered (`state/sinopac_account_fail.json`) and not retried for one TTL.

---

## Backtesting with SinoPac data (`lib/sinopac_data.py`)

```python
from lib.sinopac_data import fetch_sinopac_kbars   # at the TOP of strategy.py

def fetch_data(hdrs):
    df = fetch_sinopac_kbars(SYMBOL, INTERVAL, START, END, adjust=True)
    return _add_indicators(df)
```

- Intervals `1m 5m 15m 30m 60m` (also `1min 5min … 1h`) and `1d`. Same conventions as
  `lib.data.fetch_twstock_ohlcv`: minute-START labels on a UTC index (Shioaji's own labels are
  bar ENDs — converted), `1d` on Asia/Taipei midnights, Volume in lots (張), plus `Amount` TWD.
- From **2020-03-02** (earlier starts are moved up). Board lots only. Closed bars only.
- `adjust=True` scales each day by adjusted ÷ raw close from `fetch_twstock_price_adj` /
  `fetch_twstock_price` (the exchanges' continuity events); raises rather than return raw.
- Import it at the top: registered into lib.data on import, it is then recorded and replayed by
  lib/runner's look-ahead check (fetch_data + compute_signals). Imported inside fetch_data, the
  check covers compute_signals only.
- Cache: `cache/sinopac_kbars/<code>/<YYYY-MM>.parquet`; a re-run fetches nothing, a live tick
  refreshes today only. Prefetch: `python3 -m lib.sinopac_data 0050 5m 2021-01-01`.
- Quota: market-data traffic 500 MB/day for an account with no trading volume, 270 kbars
  queries per trading session, 50 market-data requests / 10 s — deep cold backfills after hours.
- Daily strategies can keep `fetch_twstock_price_adj` (public CDN from 2010, no key); SinoPac's
  value is free intraday history. Example: `examples/tw_sinopac_ma/`.
- Live: `manager/wait_for_bar.py` knows the TWSE calendar for `fetch_twstock_price*` daily bars
  only — a strategy on SinoPac kbars can get "bar not landed" notices after the close, at
  weekends and holidays (the same as `fetch_twstock_ohlcv` intraday). Say so before deploying one;
  a daily strategy keeps its signal on `fetch_twstock_price_adj` and still orders through SinoPac.
- Logging in for data needs the keys but no CA, in simulation or live mode alike.

---

## Field-Verified Lessons (live account, 2026-07)

The first live Taiwan-stock deployment lost **three rounds of orders to silent rejections** —
Shioaji's `place_order` does not raise on rejection. Each lesson cost a real debugging round;
the libs encode all of them:

1. **`SINOPAC_LIVE=true` must be set, or nothing is real.** Without it the session is
   simulation, against a fake account whose holdings have nothing to do with the user's (the
   simulation account showed 24 fake positions worth $24.4M while the real account was empty).
   Never diagnose position mismatches before confirming which mode you're in (`check` says).
2. **CA activation happens AFTER `login()`.** Live orders before activation fail with
   `CA not activated for: <person_id>`. `lib/sinopac_session` activates it (person id: `.env`,
   else the logged-in account's own) and raises at connect time.
3. **Enums, never strings.** The bare string `"MKT"` as `order_type` was silently rejected and
   sat unnoticed for 13 hours. Shioaji 1.7's native enums also PRINT as `OrderStatus.Filled`:
   compare `.value` (`sinopac_session.enum_value`), never `str()`.
4. **Share counts under 1000 MUST be odd-lot orders.** A Common-lot order's `quantity` is in 張;
   a share count sent as a Common lot silently vanishes. `Odd` = 盤後零股 (after-hours, 13:40–
   14:30, the legacy helper); `IntradayOdd` = 盤中零股 (the spot layer).
5. **Always confirm against order status, never trust `place_order`'s return.**
   `Failed`/`Inactive` = rejected (read `status.msg`); an IOC's unfilled rest comes back
   `Cancelled` with its deals.
6. **Warning-flagged stocks (警示股)** may require pre-funded settlement (「警示股預收條件」) —
   surface the message, never retry.
7. **Orders placed outside market hours rest as `PendingSubmit`/`PreSubmitted`** until the next
   session — the spot layer never sends one (session hold); the legacy helper may.

Shioaji 1.7 (2026-07) also removed `login(fetch_contract=…)` — contracts load on query
(`api.contracts.get`) — and keeps `api.Contracts` only for compatibility; the session handles
1.5 and 1.7.

---

## Legacy Type-B helpers (unchanged behaviour)

`place_odd_lot_order(env, symbol, 'buy'|'sell', shares, client_tag=…)` — one after-hours odd-lot
market order (1–999 shares), confirmed; `place_order_sinopac(env, symbol, signed_diff_twd,
client_tag=…)` — a TWD diff split into ≤999-share odd lots. Both pass `_send_order` (HALT, restart
stop, audit) and return exchange-confirmed fill data — report those numbers, never the intent.
`get_sinopac_positions(env)` / `get_account_balance(env)` read the account.

---

## Limits & Gotchas

| Limit | Value |
|-------|-------|
| Connections per person | 5 (each `login()` is one) |
| Logins per day | 1,000 |
| Market data (snapshots, kbars, ticks) | 50 / 10 s; kbars 270 per trading session |
| Accounting (balance, positions, settlements) | 25 / 5 s |
| Orders (place, cancel, update_status) | 250 / 10 s |
| Over-rate penalty | 1-minute suspension; repeated → IP / ID suspension |
| Daily data traffic | 500 MB (no trading volume) → 2 GB → 10 GB, reset 08:00 |
| Max clock drift | `receive_window` 30 s (`Sign data is timeout`) — sync the clock |

- `lib/sinopac_session` throttles below these per process; never loop logins.
- After the app updates, the desktop workspace's official files are replaced by the bundle's:
  re-run `tools/sinopac_deploy.py --apply` from the fork (docs/sinopac.md).
- Clock: a laptop that slept keeps a dead session — the session probes before an order after
  10 idle minutes and logs in again.

## Trading Hours

| Market | Hours (台灣時間) |
|--------|-----------------|
| 台灣股票 整股 | 09:00 – 13:25 continuous, 13:25 – 13:30 closing auction (Mon–Fri) |
| 盤中零股 | 09:00 – 13:30, call auction every 5 s (from 09:10) |
| 盤後零股 | 13:40 – 14:30, one auction at 14:30 |

## Verification Checklist for Agent

1. `python3 manager/sinopac_setup.py check` → login ok, which mode, account id, CA (live).
2. `python3 manager/sinopac_setup.py account` → equity and holdings as the page shows them.
3. `python3 manager/sinopac_setup.py quote <code>` → price, limits, the protected order prices.
4. Only after the user confirmed: they switch `live on` and press 啟動下單; then verify the first
   fills in `manager/orders.jsonl` and SinoPac's app — report what the broker returned.
