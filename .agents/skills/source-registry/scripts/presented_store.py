#!/usr/bin/env python3
"""Persistent JSON ledger tracking candidate presentation, promotion, and dismissal.

Prevents repeated presentations of already surfaced signals across different sessions,
maintaining a clean, fresh stream of topic candidates for @realchendahuang without
requiring any external database.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
LEDGER_FILENAME = "presented_ledger.json"


def get_ledger_path(repo: Path) -> Path:
    history_dir = repo / "workspace" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / LEDGER_FILENAME


def load_ledger(repo: Path) -> dict[str, Any]:
    path = get_ledger_path(repo)
    if not path.is_file():
        return {
            "version": 1,
            "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "records": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "records" in data:
            return data
    except Exception:
        pass
    return {
        "version": 1,
        "updated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "records": {},
    }


def save_ledger(repo: Path, ledger: dict[str, Any]) -> None:
    path = get_ledger_path(repo)
    ledger["updated_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_topic_candidate_ids(repo: Path) -> set[str]:
    """Extract all candidate IDs that have already been converted to topics in workspace/topics/."""
    topics_dir = repo / "workspace" / "topics"
    cids: set[str] = set()
    if not topics_dir.is_dir():
        return cids

    if not topics_dir.is_dir():
        return cids
    for path in topics_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for word in text.split():
            w = word.strip("(),.：;:'\"")
            if w.startswith("candidate-"):
                cids.add(w)
    return cids


def is_seen(candidate_id: str, ledger: dict[str, Any], topic_cids: set[str]) -> bool:
    """True if candidate has been presented to user, dismissed, or already in topics."""
    if candidate_id in topic_cids:
        return True
    records = ledger.get("records", {})
    return candidate_id in records


def mark_presented(
    repo: Path,
    candidate_ids: list[str],
    title_map: dict[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    now_dt = now or datetime.now(SHANGHAI)
    iso_now = now_dt.isoformat(timespec="seconds")
    ledger = load_ledger(repo)
    records = ledger.setdefault("records", {})

    for cid in candidate_ids:
        title = (title_map or {}).get(cid, "")
        if cid not in records:
            records[cid] = {
                "title": title,
                "first_presented_at": iso_now,
                "last_presented_at": iso_now,
                "status": "presented",
                "presented_count": 1,
            }
        else:
            rec = records[cid]
            rec["last_presented_at"] = iso_now
            rec["presented_count"] = rec.get("presented_count", 1) + 1
            if title and not rec.get("title"):
                rec["title"] = title

    save_ledger(repo, ledger)


def mark_promoted(
    repo: Path,
    candidate_id: str,
    title: str | None = None,
    now: datetime | None = None,
) -> None:
    now_dt = now or datetime.now(SHANGHAI)
    iso_now = now_dt.isoformat(timespec="seconds")
    ledger = load_ledger(repo)
    records = ledger.setdefault("records", {})

    rec = records.get(candidate_id, {})
    rec["title"] = title or rec.get("title", "")
    rec["status"] = "promoted"
    rec["promoted_at"] = iso_now
    records[candidate_id] = rec
    save_ledger(repo, ledger)


def mark_dismissed(
    repo: Path,
    candidate_ids: list[str],
    reason: str | None = None,
    now: datetime | None = None,
) -> None:
    now_dt = now or datetime.now(SHANGHAI)
    iso_now = now_dt.isoformat(timespec="seconds")
    ledger = load_ledger(repo)
    records = ledger.setdefault("records", {})

    for cid in candidate_ids:
        rec = records.get(cid, {})
        rec["status"] = "dismissed"
        rec["dismissed_at"] = iso_now
        if reason:
            rec["dismiss_reason"] = reason
        records[cid] = rec

    save_ledger(repo, ledger)
