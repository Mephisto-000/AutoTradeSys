# AutoTradeSys fork addition (2026-10-25): SinoPac (永豐金) setup and checks, run by the user.
# Licensed under the Apache License, Version 2.0 (same as the upstream Blave Agent).
"""SinoPac (永豐金) setup for the 自動下單 page — run from the workspace, by the user:

    python3 manager/sinopac_setup.py bind        # API key / secret / CA → .env (asks, never echoes)
    python3 manager/sinopac_setup.py check       # login, accounts, CA, usage — no order
    python3 manager/sinopac_setup.py live on|off # real orders on / back to simulation
    python3 manager/sinopac_setup.py account     # equity + holdings as the page will show them
    python3 manager/sinopac_setup.py quote 0050  # price, limits, the protected order prices
    python3 manager/sinopac_setup.py api-test    # SinoPac's required simulation order test
    python3 manager/sinopac_setup.py unbind      # remove every sinopac_* line from .env

On the desktop app use the app's Python: ~/Blave/venv/bin/python manager/sinopac_setup.py …
(install the SDK there once: ~/Blave/venv/bin/python -m pip install shioaji).

`bind`, `live`, `unbind` and `api-test` change what this machine trades (or
send an order), so they only run in an interactive terminal — a script or an
agent cannot feed them keys — and they never print a key. One machine, one trading venue: `bind` refuses while
another venue's keys are in .env — unbind it on the 自動下單 page first.
Reference: references/sinopac-broker.md.
"""
import getpass
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

ENV_PATH = ".env"
MANIFEST_PATH = os.path.join("manager", "credentials.ui.json")
_PAIR_RE = re.compile(r"^([A-Za-z0-9_]+)_(API_KEY|SECRET_KEY|PASSWORD|PASSPHRASE)$", re.I)
_OWN_RE = re.compile(r"^sinopac_", re.I)
_KEEP_IDS = {"BLAVE", "ADMIN", "SINOPAC"}


def _say(msg=""):
    print(msg, flush=True)


def _need_tty(what):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _say(f"✋ {what} 只能在終端機裡由你親自執行(不接受腳本或管線輸入)。")
        sys.exit(2)


def _read_lines():
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


def _env():
    env = {}
    for line in _read_lines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env


def _write_lines(lines):
    tmp = f"{ENV_PATH}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.replace(tmp, ENV_PATH)


def _other_venues(lines):
    """Venue ids holding a credential pair in .env other than SinoPac (the
    runtime's pair rule; DATA_* are data sources, never a venue)."""
    roles = {}
    for line in lines:
        name = line.split("=", 1)[0].strip()
        m = _PAIR_RE.match(name)
        if not m:
            continue
        vid = m.group(1).upper()
        if vid in _KEEP_IDS or vid.startswith("DATA_"):
            continue
        roles.setdefault(vid, set()).add(m.group(2).upper())
    own = {"PRESIDENT"} if any(l.split("=", 1)[0].strip().lower() == "president_account"
                               for l in lines) else set()
    return sorted({v for v, r in roles.items()
                   if "API_KEY" in r and r & {"SECRET_KEY", "PASSWORD", "PASSPHRASE"}} | own)


def _manifest_add(vid):
    """The UI bind manifest, when this machine has one, must list the venue —
    else lib/venue_wiring and the 下單設定 save treat the keys as unbound."""
    if not os.path.exists(MANIFEST_PATH):
        return False
    from lib.winreplace import load_json
    try:
        doc = load_json(MANIFEST_PATH, encoding="utf-8")
    except (OSError, ValueError):
        doc = {}
    ids = [str(i).lower() for i in (doc.get("ids") or []) if isinstance(i, str)]
    if vid not in ids:
        ids.append(vid)
    doc["ids"] = sorted(set(ids))
    tmp = f"{MANIFEST_PATH}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, MANIFEST_PATH)
    return True


def _manifest_drop(vid):
    if not os.path.exists(MANIFEST_PATH):
        return
    from lib.winreplace import load_json
    try:
        doc = load_json(MANIFEST_PATH, encoding="utf-8")
        doc["ids"] = sorted(str(i).lower() for i in (doc.get("ids") or []) if str(i).lower() != vid)
        tmp = f"{MANIFEST_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.replace(tmp, MANIFEST_PATH)
    except (OSError, ValueError) as e:
        _say(f"⚠️ 綁定清單沒更新({type(e).__name__})")


def _mask(s):
    s = str(s or "")
    return (s[:2] + "…" + s[-2:]) if len(s) > 6 else "…"


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_bind(_args):
    _need_tty("綁定永豐金鑰")
    lines = _read_lines()
    others = _other_venues(lines)
    if others:
        _say(f"✋ 這台電腦已綁定其他交易所/券商({', '.join(others)})。一台電腦只交易一個帳戶:"
             f"請先在「自動下單」頁解除綁定,再回來綁永豐。")
        return 2
    _say("永豐金 API 金鑰設定(輸入內容不會顯示,也不會被印出來)。")
    _say("金鑰在永豐「API 管理」頁申請:https://www.sinotrade.com.tw/newweb/PythonAPIKey/")
    api_key = getpass.getpass("API Key: ").strip()
    secret = getpass.getpass("Secret Key: ").strip()
    if len(api_key) < 16 or len(secret) < 16:
        _say("✋ 金鑰太短,看起來沒貼完整 — 沒有寫入。")
        return 2
    ca_path = input("憑證檔路徑(Sinopac.pfx,只做模擬可直接按 Enter 略過): ").strip()
    ca_passwd = person_id = ""
    if ca_path:
        ca_path = os.path.expanduser(ca_path)
        if not os.path.isfile(ca_path):
            _say(f"✋ 找不到憑證檔:{ca_path} — 沒有寫入。")
            return 2
        ca_passwd = getpass.getpass("憑證密碼: ").strip()
        person_id = input("身分證字號(可留空,預設用登入帳戶的身分): ").strip().upper()
    block = ["# SinoPac (永豐金) — written by manager/sinopac_setup.py bind",
             f"sinopac_api_key={api_key}", f"sinopac_secret_key={secret}"]
    if ca_path:
        block += [f"sinopac_ca_path={ca_path}", f"sinopac_ca_passwd={ca_passwd}"]
        if person_id:
            block.append(f"sinopac_person_id={person_id}")
    block.append("SINOPAC_LIVE=false")
    block.append(f"SINOPAC_BOUND_TS={int(time.time())}")
    kept = [l for l in lines if not _OWN_RE.match(l.split("=", 1)[0].strip())
            and l.strip() != "# SinoPac (永豐金) — written by manager/sinopac_setup.py bind"]
    _write_lines(kept + block)
    from lib import venue_traits
    listed = _manifest_add(venue_traits.SINOPAC)
    _say("✅ 已寫入 .env(權限 600),目前是「模擬模式」:不會送出真實委託。")
    if listed:
        _say("   已加進這台電腦的綁定清單(manager/credentials.ui.json)。")
    _say("下一步:python3 manager/sinopac_setup.py check 測試登入;"
         "確認無誤、通過永豐的 API 測試後,再用 live on 開啟實盤。")
    return 0


def cmd_unbind(_args):
    _need_tty("解除永豐綁定")
    lines = _read_lines()
    kept = [l for l in lines if not _OWN_RE.match(l.split("=", 1)[0].strip())
            and l.strip() != "# SinoPac (永豐金) — written by manager/sinopac_setup.py bind"]
    if len(kept) == len(lines):
        _say("這台電腦沒有永豐的設定。")
        return 0
    ans = input("確定要移除 .env 裡所有永豐設定?輸入 yes 確認: ").strip().lower()
    if ans != "yes":
        _say("已取消。")
        return 1
    _write_lines(kept)
    from lib import venue_traits
    _manifest_drop(venue_traits.SINOPAC)
    from lib import sinopac_session as ss
    ss.reset()
    _say("✅ 已移除永豐設定。帳上持股不受影響;自動下單頁會在下次讀取時顯示未綁定。")
    return 0


def cmd_live(args):
    _need_tty("切換永豐實盤")
    want = (args[0] if args else "").lower()
    if want not in ("on", "off"):
        _say("用法:python3 manager/sinopac_setup.py live on|off")
        return 2
    lines = _read_lines()
    env = _env()
    if not any(_OWN_RE.match(k) for k in env):
        _say("✋ 還沒綁定永豐 — 先執行 bind。")
        return 2
    if want == "on":
        if not env.get("sinopac_ca_path") or not env.get("sinopac_ca_passwd"):
            _say("✋ 實盤需要憑證:請重新執行 bind 並填入憑證檔路徑與密碼。")
            return 2
        _say("⚠️ 開啟後,「自動下單」頁的策略金額會用真錢下單(台股現股,T+2 交割)。")
        _say("   請確認:已通過永豐 API 測試、交割戶餘額足夠、自動下單頁的金額正確。")
        if input("輸入 LIVE 確認開啟實盤: ").strip() != "LIVE":
            _say("已取消,維持模擬模式。")
            return 1
    from lib import sinopac_session as ss
    if (want == "on") == ss.is_live(env):
        _say("已經是" + ("實盤" if want == "on" else "模擬") + "模式,沒有變更。")
        return 0
    if want == "off":
        held = _bot_book()
        if held:
            _say("⚠️ 機器人在永豐實盤還有部位:" + "、".join(f"{k} {v:g} 股" for k, v in held.items()))
            _say("   切回模擬後機器人會「忘記」這些部位(仍在你的帳戶裡,不會被賣出),"
                 "請先在自動下單頁「暫停並全部平倉」或自行處理。")
            if input("仍要切回模擬?輸入 yes 確認: ").strip().lower() != "yes":
                _say("已取消,維持實盤。")
                return 1
    # pause first: a reconcile round already under way must not send its remaining
    # legs through a session of the other mode (lib/order_sinopac checks HALT per order)
    from lib import guard
    guard.trip_halt(f"SinoPac mode switched to {'live' if want == 'on' else 'simulation'} — "
                    f"the bot's SinoPac book restarts empty; check amounts, then 啟動下單",
                    "sinopac_setup")
    out, seen = [], set()
    for l in lines:
        name = l.split("=", 1)[0].strip().upper()
        if name in ("SINOPAC_LIVE", "SINOPAC_BOUND_TS"):
            if name not in seen:
                out.append(f"SINOPAC_LIVE={'true' if want == 'on' else 'false'}" if name == "SINOPAC_LIVE"
                           else f"SINOPAC_BOUND_TS={int(time.time())}")
                seen.add(name)
            continue
        out.append(l)
    if "SINOPAC_LIVE" not in seen:
        out.append(f"SINOPAC_LIVE={'true' if want == 'on' else 'false'}")
    if "SINOPAC_BOUND_TS" not in seen:
        out.append(f"SINOPAC_BOUND_TS={int(time.time())}")
    _write_lines(out)
    _say("✅ 實盤已開啟。" if want == "on" else "✅ 已切回模擬模式。")
    _say("   自動下單已暫停。模擬與實盤是兩本帳:機器人在永豐的帳本會重新開始(另一個模式的部位不帶過來)。")
    _say("   到自動下單頁確認金額後,按「啟動下單」即以新模式交易。")
    return 0


def _bot_book():
    """{key: shares} the bot's own SinoPac book holds now (lib.portfolio's ledger)."""
    try:
        from lib import portfolio, venue_traits
        rows = portfolio.ledger_positions(venue_traits.SINOPAC) or {}
    except Exception as e:  # can't tell: say so rather than claim the book is empty
        _say(f"⚠️ 讀不到機器人的帳本({type(e).__name__}),請先確認自動下單頁的部位。")
        return {"?": 0.0}
    return {k: float(r.get("qty") or 0) for k, r in rows.items()
            if r.get("side") == "long" and float(r.get("qty") or 0) > 0}


def cmd_check(_args):
    from lib import sinopac_session as ss
    env = _env()
    sj = ss.shioaji()
    live = ss.is_live(env)
    _say(f"shioaji {getattr(sj, '__version__', '?')} · 模式:{'實盤' if live else '模擬'}")
    api = ss.get_api(env)
    acct = ss.stock_account(api)
    _say(f"✅ 登入成功 · 證券帳戶 {acct.broker_id}-{_mask(acct.account_id)}"
         f" · 已簽署 API 條款:{getattr(acct, 'signed', '?')}")
    try:
        u = ss.read(env, lambda a: a.usage(), kind="account")
        _say(f"   今日流量 {int(u.bytes) / 1e6:.1f} / {int(u.limit_bytes) / 1e6:.0f} MB · "
             f"連線數 {u.connections}")
    except Exception as e:
        _say(f"   流量查詢失敗({type(e).__name__})")
    if live:
        try:
            ss.get_api(env, need_ca=True)
            pid = env.get("sinopac_person_id") or getattr(acct, "person_id", "")
            exp = api.get_ca_expiretime(pid) if hasattr(api, "get_ca_expiretime") else None
            _say(f"✅ 憑證已啟用" + (f" · 到期 {exp}" if exp else ""))
        except Exception as e:
            _say(f"❌ 憑證啟用失敗:{ss.scrub(e, env)}")
            return 1
    from lib import account_sinopac
    snap = account_sinopac.refresh(env)
    _say(f"   持股 {len(snap['positions'])} 檔"
         + (f" · 交割戶餘額 {snap['cash']:,.0f} TWD" if snap.get("cash") is not None
            else " · 模擬模式沒有交割戶餘額"))
    return 0


def cmd_account(_args):
    from lib import account_sinopac
    env = _env()
    eq = account_sinopac.get_equity(env)
    _say(f"權益 {eq['equity']:,.0f} {eq['currency']}(現金 + T+1/T+2 未交割款 + 持股市值)")
    for h in account_sinopac.get_holdings(env):
        v = h["usdt_value"]
        _say(f"  {h['wallet']:<6} {h['asset']:<8} {h['amount']:>12,.0f}  "
             f"{('%s TWD' % format(v, ',.0f')) if v is not None else '—'}")
    return 0


def cmd_quote(args):
    if not args:
        _say("用法:python3 manager/sinopac_setup.py quote 0050")
        return 2
    from lib import order_sinopac as o
    env = _env()
    q = o._quote(env, o._norm_code(args[0]))
    slip = o._slippage(env)
    _say(f"{args[0]} 成交 {q['last']:g} · 買一 {q['bid']:g} · 賣一 {q['ask']:g} · "
         f"參考 {q['reference']:g} · 漲停 {q['limit_up']:g} · 跌停 {q['limit_down']:g}")
    for side, ref in (("buy", q["ask"] or q["last"]), ("sell", q["bid"] or q["last"])):
        if ref:
            px = o.protected_price(side, ref, q["limit_up"], q["limit_down"], slip)
            _say(f"  {side:<4} 保護價 {px:g}(±{slip:.1%})")
    return 0


def cmd_api_test(_args):
    _need_tty("永豐 API 測試(會送出一筆模擬委託)")
    from lib import order_sinopac as o
    env = {k: v for k, v in _env().items() if k.upper() != "SINOPAC_LIVE"}  # always simulation
    _say("永豐 API 測試(模擬環境):登入 + 一筆 2890 整股限價買單(遠離市價、不會成交),送出後撤單。")
    _say("測試時段:週一至週五 08:00–20:00(18:00 後僅限台灣 IP)。")
    result = o.simulation_api_test(env)
    _say(f"✅ 委託已送出 · 狀態 {result['status']} · 委託書號 {result['seqno'] or '—'}"
         f" · 撤單 {'成功' if result.get('cancelled') else '未確認'}")
    _say("約 5 分鐘後,用 check 確認「已簽署 API 條款」或到永豐簽署中心查看測試結果。")
    return 0


COMMANDS = {"bind": cmd_bind, "unbind": cmd_unbind, "live": cmd_live, "check": cmd_check,
            "account": cmd_account, "quote": cmd_quote, "api-test": cmd_api_test}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        _say(__doc__)
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:]) or 0
    except KeyboardInterrupt:
        _say("\n已取消。")
        return 1
    except Exception as e:
        try:
            from lib import sinopac_session as ss
            msg = ss.scrub(e, _env())
        except Exception:
            msg = type(e).__name__
        _say(f"❌ {type(e).__name__}: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
