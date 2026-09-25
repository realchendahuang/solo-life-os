#!/usr/bin/env python3
"""X-Tiller multi-device git sync (pull --rebase, commit, push).

Manual and explicit: run this only when the user asks to sync (e.g. after a
post has been archived, or to move work to another device). Drafting and
editing never trigger it — unconfirmed work stays in the chat and local files.

Usage:
    python3 scripts/sync.py [-m "message"] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def run_cmd(argv: list[str], *, check: bool = True, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    res = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
    if check and res.returncode != 0:
        cmd_str = " ".join(argv)
        err_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"Command failed ({cmd_str}): {err_msg}")
    return res


def generate_commit_message(changes: list[tuple[str, str]]) -> str:
    """Group the changed top-level dirs into a short semantic message."""
    now = dt.datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M")
    scopes: list[str] = []
    known = {
        "topics": "workspace/topics/",
        "inbox": "workspace/inbox/",
        "posts": "workspace/posts/",
        "candidates": "workspace/candidates",
        "profile": "profile/",
        "scripts": "scripts/",
        "skills": ".agents/skills/",
    }
    paths = [p for _, p in changes]
    for name, prefix in known.items():
        if any(p.startswith(prefix) for p in paths):
            scopes.append(name)
    if any(p == "AGENTS.md" for p in paths):
        scopes.append("rules")
    if not scopes:
        scopes.append("workspace")
    scope_str = ", ".join(scopes[:3]) + ("..." if len(scopes) > 3 else "")
    return f"sync({scope_str}): multi-device sync ({len(paths)} files) [{now}]"


def run_sync(args: argparse.Namespace) -> int:
    print("🔄 X-Tiller 多端同步（手动触发）")

    changes = [
        (line[:2].strip(), line[2:].strip().strip('"'))
        for line in run_cmd(["git", "status", "--porcelain"]).stdout.splitlines()
        if line.strip()
    ]
    if changes:
        commit_msg = args.message or generate_commit_message(changes)
        print(f"   提交 {len(changes)} 个文件: {commit_msg}")
        if not args.dry_run:
            run_cmd(["git", "add", "-A"])
            run_cmd(["git", "commit", "-m", commit_msg])
    else:
        print("   本地无未提交变更")

    print("   对齐远程 (pull --rebase)...")
    if not args.dry_run:
        pull = run_cmd(["git", "pull", "--rebase", "origin", "main"], check=False)
        if pull.returncode != 0:
            if run_cmd(["git", "rebase", "--abort"], check=False).returncode == 0:
                print("⚠️ 无法自动对齐远程，已回退 rebase；本地提交完好，请手动合并后重试。")
            else:
                print(f"❌ pull --rebase 失败: {pull.stderr or pull.stdout}")
            return 1
        push = run_cmd(["git", "push", "origin", "main"], check=False)
        if push.returncode != 0:
            print(f"❌ push 失败: {push.stderr or push.stdout}")
            return 1
        head = run_cmd(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        print(f"🎉 同步完成（{head}）")
    else:
        print("   [dry-run] 未执行 pull/push")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X-Tiller multi-device git synchronization.")
    parser.add_argument("-m", "--message", help="Custom commit message.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen.")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        sys.exit(run_sync(args))
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
    except Exception as exc:
        print(f"\n❌ 同步失败: {exc}")
        sys.exit(1)
