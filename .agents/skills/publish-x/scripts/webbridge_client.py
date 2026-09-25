#!/usr/bin/env python3
"""Minimal Kimi WebBridge client using only the Python standard library.

Prints a compact summary (JSON without huge trees) so raw daemon responses
never flood the conversation. For the X-Tiller publish flow.

Usage:
    python3 webbridge_client.py navigate <url> [--new-tab] [--group "<label>"]
    python3 webbridge_client.py find_tab <url> [--active]
    python3 webbridge_client.py snapshot [--compact]
    python3 webbridge_client.py fill <selector_or_re> <value|file|->
    python3 webbridge_client.py list_tabs
    python3 webbridge_client.py evaluate "<js-code>" --unlock
    python3 webbridge_client.py raw '<json>' --unlock

`evaluate` and `raw` reach arbitrary JS / arbitrary daemon payloads on the
user's logged-in browser tab, which is outside the publish flow; both are
refused unless `--unlock` is passed explicitly.
"""

import json
import sys
import urllib.request
from pathlib import Path

DAEMON = "http://127.0.0.1:10086/command"
DEFAULT_SESSION = "x-tiller-post"
COMPACT_LIMIT = 2000


def post(payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DAEMON,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def compact(data, elide_tree: bool = False) -> str:
    """Dump `data` as compact JSON, clipped with an explicit truncation marker.

    `elide_tree` replaces a snapshot's accessibility tree with a size summary
    so `snapshot --compact` stays readable. `evaluate` code is never echoed.
    """
    if isinstance(data, dict) and "args" in data:
        data = dict(data)
        args = data.get("args")
        if isinstance(args, dict) and "code" in args:
            data["args"] = {"code": "<js omitted>"}
    if elide_tree and isinstance(data, dict) and "tree" in data:
        data = dict(data)
        tree = data.pop("tree")
        data["tree"] = f"<tree omitted: {len(str(tree))} chars>"
    text = json.dumps(data, ensure_ascii=False)
    if len(text) > COMPACT_LIMIT:
        text = f"{text[:COMPACT_LIMIT]}…[truncated {len(text) - COMPACT_LIMIT} chars]"
    return text


def _usage_error(message: str) -> int:
    print(f"error: {message}")
    print("try --help")
    return 1


def _locked_error(command: str) -> int:
    print(
        f"error: `{command}` can run arbitrary code on your logged-in browser "
        "tab, which is outside the publish flow; pass --unlock to allow it."
    )
    return 1


def _read_value(value_arg: str) -> str:
    """A literal value, a file path, or '-' to read stdin."""
    if value_arg == "-":
        return sys.stdin.read()
    path = Path(value_arg)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return value_arg


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    unlocked = "--unlock" in args
    args = [arg for arg in args if arg != "--unlock"]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if args else 1
    cmd, rest = args[0], args[1:]
    payload = {"session": DEFAULT_SESSION}
    try:
        if cmd == "navigate":
            if not rest:
                return _usage_error("navigate needs <url>")
            payload["action"] = "navigate"
            payload["args"] = {"url": rest[0], "newTab": "--new-tab" in rest}
            if "--group" in rest:
                index = rest.index("--group")
                if index + 1 >= len(rest):
                    return _usage_error("--group needs a label")
                payload["args"]["group_title"] = rest[index + 1]
        elif cmd == "find_tab":
            if not rest:
                return _usage_error("find_tab needs <url>")
            payload["action"] = "find_tab"
            payload["args"] = {"url": rest[0], "active": "--active" in rest}
        elif cmd == "snapshot":
            payload["action"] = "snapshot"
            payload["args"] = {}
        elif cmd == "list_tabs":
            payload["action"] = "list_tabs"
            payload["args"] = {}
        elif cmd == "evaluate":
            if not unlocked:
                return _locked_error("evaluate")
            if not rest:
                return _usage_error("evaluate needs <js-code>")
            payload["action"] = "evaluate"
            payload["args"] = {"code": rest[0]}
        elif cmd == "fill":
            if len(rest) < 2:
                return _usage_error("fill needs <selector_or_re> <value|file|->")
            payload["action"] = "fill"
            payload["args"] = {"selector": rest[0], "value": _read_value(rest[1])}
        elif cmd == "raw":
            if not unlocked:
                return _locked_error("raw")
            if not rest:
                return _usage_error("raw needs '<json>'")
            payload = json.loads(rest[0])
            if not isinstance(payload, dict):
                print("error: raw payload must be a JSON object")
                return 1
            if "session" not in payload:
                payload["session"] = DEFAULT_SESSION
        else:
            print(f"unknown command: {cmd}")
            print("try --help")
            return 1
        result = post(payload)
        print(compact(result, elide_tree=(cmd == "snapshot" and "--compact" in rest)))
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
