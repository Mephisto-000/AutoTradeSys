# AutoTradeSys fork addition (2026-10-26)
"""runtime/portfolio_reporter.venues() — the report's venue entry for 永豐金 carries
`simulation`, so the desktop page marks SinoPac's simulation environment 模擬 and
not 真錢. Same rule as the order layer (lib/sinopac_session.is_live over
lib.venue_wiring.read_env): real orders only with SINOPAC_LIVE=true — quotes
stripped, the exact name first, then any case. Other venues' entries unchanged.

Run: cd blave-agent && .venv/bin/python tests/check_sinopac_reporter.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="sinopac-reporter-")
os.environ["BLAVE_AGENT_WORKSPACE"] = WS
os.environ["BLAVE_AGENT_BASE"] = WS
os.environ["BLAVE_AGENT_HOME"] = os.environ["BLAVECLAW_HOME"] = WS
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "runtime"))
os.makedirs(os.path.join(WS, "lib"))
for f in ("order_sinopac.py", "account_sinopac.py", "order_binance.py", "account_binance.py"):
    open(os.path.join(WS, "lib", f), "w").close()

import portfolio_reporter as pr  # noqa: E402
from lib import sinopac_session as ss  # noqa: E402
from lib.venue_wiring import read_env  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


ENV_PATH = os.path.join(WS, ".env")
KEYS = "sinopac_api_key=not-a-real-sinopac-key-0001\nsinopac_secret_key=not-a-real-sinopac-secret-01\n"


def venues_with(extra):
    with open(ENV_PATH, "w") as f:
        f.write(KEYS + extra)
    return pr.venues()


cases = [
    ("", True, "no SINOPAC_LIVE line (the app's bind writes none)"),
    ("SINOPAC_LIVE=false\n", True, "SINOPAC_LIVE=false (the terminal tool's default)"),
    ("SINOPAC_LIVE=true\n", False, "SINOPAC_LIVE=true (live on)"),
    ('SINOPAC_LIVE="true"\n', False, "a quoted true"),
    ("sinopac_live=TRUE\n", False, "lowercase name, uppercase value"),
    ("SINOPAC_LIVE=yes\n", True, "anything but true is simulation"),
    ("SINOPAC_LIVE=false\nsinopac_live=true\n", True, "the exact name wins over another case"),
    ("# SINOPAC_LIVE=true\n", True, "a commented-out line is not a setting"),
]
for extra, sim, why in cases:
    v = venues_with(extra)
    entry = v.get("sinopac") or {}
    check(entry.get("simulation") is sim, f"{why} → simulation {sim}")
    check(ss.is_live(read_env(ENV_PATH)) is (not sim), f"…the same verdict as the order layer's is_live ({why})")

v = venues_with("")
check(v.get("sinopac", {}).get("pair") is True and v["sinopac"]["order"] and v["sinopac"]["account"],
      "the SinoPac entry is a bound venue (pair, order lib, account lib)")
with open(ENV_PATH, "w") as f:
    f.write("BINANCE_API_KEY=not-a-real-key\nBINANCE_SECRET_KEY=not-a-real-secret\n")
check(pr.venues() == {"binance": {"credentials": True, "pair": True, "order": True, "account": True}},
      "other venues: the entry is exactly as before (no simulation key)")

# The agent's reply rule (runtime/agent_turn._STYLE_RULES, 2026-11-04): venues by name, never the bare id.
# 永豐金 is listed with the shell's sino.venue msgstr, so a reply about it says 永豐金證券, not "sinopac".
os.environ.setdefault("BLAVE_AGENT_DB", os.path.join(WS, "session.db"))
sys.modules.setdefault("claude_agent_sdk", __import__("types").ModuleType("claude_agent_sdk"))
import agent_turn as at  # noqa: E402

check(at._VENUE_NAMES.get("sinopac") == ("永豐金證券", "SinoPac Securities"),
      "the reply rule's venue names list sinopac as 永豐金證券 / SinoPac Securities")
check("sinopac 寫永豐金證券(英文 SinoPac Securities)" in at._STYLE_RULES,
      "…and the shared style rules carry that line")
po = {lang: open(os.path.join(ROOT, "shell", "i18n", lang + ".po"), encoding="utf-8").read() for lang in ("zh", "en")}
check('msgid "sino.venue"\nmsgstr "永豐金證券"' in po["zh"] and 'msgid "sino.venue"\nmsgstr "SinoPac Securities"' in po["en"],
      "…the same words as the shell's sino.venue")

print("\n" + ("all ok" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
