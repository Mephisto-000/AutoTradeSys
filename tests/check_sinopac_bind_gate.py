# AutoTradeSys fork addition (2026-11-24)
"""The desktop app's SinoPac (永豐金) stock bind still writes .env after upstream 0.1.58.

Upstream 0.1.58 sends every `sinopac_*` line of the `credentials` command (any case) through
runtime/sinopac_service.bind_gate: only its futures connect flow (sinopac_service.store) may bind
SinoPac. The fork's stock bind is venue-connect's plain SINOPAC_API_KEY + SINOPAC_SECRET_KEY pair,
checked by _local_real_key_gate (lib/account_sinopac reads the simulation account) — so
command_listener._fork_sinopac_stock_bind lets exactly that pair through, on this computer only.

1. Desktop, the plain pair: bind_gate is not asked, _local_real_key_gate is (once, with the pair),
   and both lines land in .env.
2. The checker refusing: nothing written.
3. Still refused by upstream's bind_gate (nothing written, the key check never runs):
   a third SinoPac line (SINOPAC_LIVE, SINOPAC_CA_PATH), half a pair, `vault:` sentinel values,
   the lowercase futures set store() writes when store() did not stage it, an empty value.
4. The cloud box (BLAVE_AGENT_LOCAL unset): the plain pair is refused — the fork's SinoPac is
   desktop-only, upstream's refusal stands there.
5. Upstream's own path is untouched: a write store() staged (sinopac_service._PENDING) passes
   bind_gate and does not run the stock key check.
6. Unbind (credentials_remove) of the fork's names still drops all of them.

No network, no broker: _local_real_key_gate is replaced. Keys are not-a-real-* strings.
Run: cd blave-agent && .venv/bin/python tests/check_sinopac_bind_gate.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = tempfile.mkdtemp(prefix="sinopac-bindgate-")
WS = os.path.join(BASE, "workspace")
os.makedirs(os.path.join(WS, "manager"))
os.environ["BLAVE_AGENT_BASE"] = BASE
os.environ["BLAVE_AGENT_WORKSPACE"] = WS
os.environ["BLAVE_AGENT_LOCAL"] = "1"
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, ROOT)
os.chdir(WS)  # lib/guard writes state/HALT relative to the cwd — keep it out of the repo
import command_listener as cl  # noqa: E402
import sinopac_service  # noqa: E402

with open(os.path.join(WS, "manager", "portfolio_config.json"), "w") as f:
    f.write("{}")
cl._sync_strategy_crons = lambda names: None
cl.LOCAL_OPEN_VENUES = frozenset(cl.LOCAL_OPEN_VENUES | {"SINOPAC"})  # = local_daemon (fork: always)

fails = 0
ENV_PATH = os.path.join(WS, ".env")
KEY, SECRET = "not-a-real-sinopac-key-0001", "not-a-real-sinopac-secret-0001"
PAIR = {"SINOPAC_API_KEY": KEY, "SINOPAC_SECRET_KEY": SECRET}


def check(cond, msg, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + msg + ("" if cond or got is None else f"  → {got!r}"))
    fails += 0 if cond else 1


key_calls, gate_calls = [], []
real_gate = sinopac_service.bind_gate


def fake_key_gate(answer=None):
    def gate(vid, env):
        key_calls.append((vid, dict(env)))
        if answer is not None:
            raise ValueError(answer)
    cl._local_real_key_gate = gate


def spy_bind_gate(env):
    gate_calls.append(dict(env))
    return real_gate(env)


sinopac_service.bind_gate = spy_bind_gate


def env_lines():
    try:
        with open(ENV_PATH) as f:
            return [l.split("=", 1)[0] for l in f.read().splitlines() if "=" in l]
    except FileNotFoundError:
        return []


def attempt(env):
    key_calls.clear()
    gate_calls.clear()
    try:
        cl._cmd_credentials({"env": dict(env)})
        return None
    except ValueError as e:
        return str(e)


def reset():
    if os.path.exists(ENV_PATH):
        os.remove(ENV_PATH)


# 1 ─ the plain pair on the desktop
fake_key_gate()
reset()
err = attempt(PAIR)
check(err is None, "1 desktop: the plain SINOPAC_API_KEY + SINOPAC_SECRET_KEY pair binds", err)
check(not gate_calls, "1 upstream's bind_gate is not asked for the stock pair", gate_calls)
check(key_calls == [("SINOPAC", PAIR)], "1 _local_real_key_gate runs once, with the pair (simulation-account read)", key_calls)
check(set(env_lines()) >= {"SINOPAC_API_KEY", "SINOPAC_SECRET_KEY"}, "1 both lines in .env", env_lines())

# 2 ─ the checker refuses → nothing written
reset()
fake_key_gate("REJECTED: SinoPac said no")
err = attempt(PAIR)
check(err is not None and "REJECTED" in err and not env_lines(), "2 the key check refusing → nothing written", err)
fake_key_gate()

# 3 ─ everything else still goes to upstream's bind_gate and is refused
for name, env in (
        ("a third line (SINOPAC_LIVE)", dict(PAIR, SINOPAC_LIVE="true")),
        ("a third line (SINOPAC_CA_PATH)", dict(PAIR, SINOPAC_CA_PATH="/tmp/not-a-real.pfx")),
        ("half a pair", {"SINOPAC_API_KEY": KEY}),
        ("vault: sentinels", {"SINOPAC_API_KEY": "vault:abc", "SINOPAC_SECRET_KEY": "vault:secret"}),
        ("the futures set store() writes, not staged", sinopac_service.bound_env(KEY, SECRET, WS)),
        ("an empty value", {"SINOPAC_API_KEY": KEY, "SINOPAC_SECRET_KEY": " "}),
):
    reset()
    err = attempt(env)
    check(err is not None and "永豐期貨只能從連接帳戶的流程綁定" in err and gate_calls and not key_calls and not env_lines(),
          f"3 refused by bind_gate: {name}", (err, len(gate_calls), key_calls, env_lines()))

# 4 ─ the cloud box keeps upstream's refusal
os.environ.pop("BLAVE_AGENT_LOCAL")
reset()
err = attempt(PAIR)
check(err is not None and "永豐期貨只能從連接帳戶的流程綁定" in err and not env_lines(), "4 cloud: the plain pair is refused", err)
os.environ["BLAVE_AGENT_LOCAL"] = "1"

# 5 ─ upstream's staged write: bind_gate passes it, the stock key check does not run
reset()
staged = sinopac_service.bound_env(KEY, SECRET, WS)
sinopac_service._PENDING["env"] = {k.casefold(): v for k, v in staged.items()}
try:
    err = attempt(staged)
finally:
    sinopac_service._PENDING["env"] = None
check(err is None and gate_calls and not key_calls and "sinopac_api_key" in env_lines(),
      "5 a write store() staged goes through bind_gate, no stock key check", (err, key_calls, env_lines()))

# 6 ─ unbind drops every fork line, any case
reset()
attempt(PAIR)
with open(ENV_PATH, "a") as f:
    f.write("SINOPAC_CA_PATH=/x/not-a-real.pfx\nSINOPAC_CA_PASSWD=not-a-real\nSINOPAC_PERSON_ID=not-a-real\n"
            "SINOPAC_LIVE=false\nSINOPAC_BOUND_TS=1\nOTHER_LINE=keep\n")
names = ["sinopac_api_key", "sinopac_secret_key", "sinopac_ca_passwd", "sinopac_person_id", "sinopac_ca_path",
         "sinopac_live", "sinopac_bound_ts"]   # = shell/daemon.js SINOPAC_ENV lowercased (main.js sinopacUnbind)
try:
    cl._cmd_credentials_remove({"env": names})
    left = env_lines()
except Exception as e:  # noqa: BLE001
    left = [f"{type(e).__name__}: {e}"]
check(not [k for k in left if k.casefold().startswith("sinopac_")] and "OTHER_LINE" in left,
      "6 unbind with the merged SINOPAC_ENV drops all seven SinoPac lines, keeps the rest", left)

print("all passed" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
