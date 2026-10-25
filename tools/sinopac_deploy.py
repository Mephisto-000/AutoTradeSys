# AutoTradeSys fork addition (2026-10-25): put the SinoPac feature into a desktop workspace.
# Licensed under the Apache License, Version 2.0 (same as the upstream Blave Agent).
"""Copy this fork's SinoPac (永豐金) feature into a Blave desktop workspace.

    python3 tools/sinopac_deploy.py                    # dry run: what would change
    python3 tools/sinopac_deploy.py --apply            # copy; every replaced file is backed up
    python3 tools/sinopac_deploy.py --to /path/to/workspace --apply

Why a tool: the desktop app copies its OWN lib/ manager/ references/ examples/
into ~/Blave/workspace whenever it updates (shell/main.js syncOfficialOnUpdate)
— this fork's edits to official files are then backed up to .official-backup/
and replaced, while its new files stay. Re-run this after every app update
(after merging that upstream version into `custom`, docs/fork-workflow.md).

Refuses to copy when the workspace's VERSION is not this repo's (the fork's
lib/portfolio.py next to another version's lib would mix two releases), or
while a reconcile round is running (state/execution/round). Restart the app
afterwards so the order daemon loads the new code.
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    # new files (the app's update never touches them)
    "lib/sinopac_session.py", "lib/account_sinopac.py", "lib/sinopac_data.py",
    "manager/sinopac_setup.py", "examples/tw_sinopac_ma/strategy.py",
    # official files this fork changes (replaced again by every app update)
    "lib/order_sinopac.py", "lib/venue_traits.py", "lib/portfolio.py", "lib/execute.py",
    "references/sinopac-broker.md", "references/lib.md", "examples/README.md",
]


def _version(root):
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _venv_python(ws):
    for p in (os.path.join(os.path.dirname(ws), "venv", "bin", "python3"),
              os.path.join(os.path.dirname(ws), "venv", "bin", "python"),
              os.path.join(os.path.dirname(ws), "venv", "Scripts", "python.exe")):
        if os.path.exists(p):
            return p
    return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--to", default=os.path.expanduser("~/Blave/workspace"),
                    help="the workspace (default ~/Blave/workspace)")
    ap.add_argument("--apply", action="store_true", help="copy (default: dry run)")
    a = ap.parse_args(argv)
    ws = os.path.abspath(os.path.expanduser(a.to))
    if not os.path.isdir(os.path.join(ws, "lib")):
        print(f"✋ {ws} is not a Blave workspace (no lib/)")
        return 2
    mine, theirs = _version(REPO), _version(ws)
    if mine != theirs:
        print(f"✋ VERSION differs — this repo {mine}, the workspace {theirs}. Merge that upstream "
              f"version into `custom` first (docs/fork-workflow.md §3), then deploy.")
        return 2
    if os.path.exists(os.path.join(ws, "state", "execution", "round")):
        print("✋ a reconcile round is running right now — try again in a minute "
              "(or pause trading on the 自動下單 page first).")
        return 2
    changes = []
    for rel in FILES:
        src, dst = os.path.join(REPO, rel), os.path.join(ws, rel)
        if not os.path.exists(src):
            print(f"✋ missing in the repo: {rel}")
            return 2
        if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
            continue
        changes.append((rel, src, dst, os.path.exists(dst)))
    if not changes:
        print(f"✅ {ws} already has this fork's SinoPac files ({len(FILES)} checked).")
    for rel, _, _, exists in changes:
        print(f"  {'replace' if exists else 'add    '} {rel}")
    if changes and not a.apply:
        print(f"\n(dry run — {len(changes)} file(s) would change; add --apply to copy)")
    if changes and a.apply:
        backup = os.path.join(ws, ".official-backup", f"sinopac-deploy-{time.strftime('%Y%m%d-%H%M%S')}")
        for rel, src, dst, exists in changes:
            if exists:
                os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
                shutil.copy2(dst, os.path.join(backup, rel))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = f"{dst}.{os.getpid()}.tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        print(f"\n✅ copied {len(changes)} file(s); replaced ones backed up under {backup}")
        print("   Quit and reopen Blave so the order daemon loads the new code.")
    py = _venv_python(ws)
    if py:
        ok = subprocess.run([py, "-c", "import shioaji"], capture_output=True).returncode == 0
        if not ok:
            print(f"\n⚠️ shioaji is not installed in the app's Python — install it once:\n"
                  f"   {py} -m pip install shioaji")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
