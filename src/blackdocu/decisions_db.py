"""Entscheidungs-Datenbank (SQLite). Enthält nur Pseudonyme, nie Klarnamen."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id              INTEGER PRIMARY KEY,
  created_at      TEXT NOT NULL,
  case_id         TEXT NOT NULL,
  document        TEXT,
  decision        TEXT NOT NULL,
  rationale       TEXT NOT NULL,
  criterion_ref   TEXT,
  actor           TEXT NOT NULL CHECK (actor IN ('agent', 'mensch')),
  role            TEXT,
  model           TEXT,
  skill_version   TEXT,
  status          TEXT NOT NULL CHECK (status IN ('vorgeschlagen', 'bestaetigt', 'ueberstimmt')),
  override_reason TEXT
);
"""

PSEUDONYM = re.compile(r"^<<[A-Z_]+_\d+>>$")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


FREE_TEXT = ("document", "decision", "rationale", "criterion_ref", "override_reason")


def find_clear_names(fields: dict[str, str | None], people) -> list[str]:
    """Sucht Klarnamen (Namensliste) und Daten in Freitextfeldern – Review 1.13."""
    from .stage1_namelist import build_index, find_spans
    from .stage2_noirdoc import regex_dates
    from .placeholders import mask

    idx = build_index(people)
    hits = []
    for k, v in fields.items():
        if k in FREE_TEXT and v:
            m = mask(v)
            hits += [f"{k}: {h['text']}" for h in find_spans(m, idx)]
            hits += [f"{k}: {e.text}" for e in regex_dates(m)]
    return hits


def add_decision(con: sqlite3.Connection, *, case_id: str, decision: str, rationale: str,
                 actor: str, status: str = "vorgeschlagen", people=None, **extra: str | None) -> int:
    """people: Namensliste – wenn angegeben, werden Freitextfelder auf Klarnamen geprüft."""
    if not PSEUDONYM.match(case_id):
        raise ValueError(f"case_id muss ein Pseudonym wie <<SCHUELER_07>> sein, nicht {case_id!r}")
    if people is not None:
        leaks = find_clear_names({"decision": decision, "rationale": rationale, **extra}, people)
        if leaks:
            raise ValueError(f"Klarnamen/Daten in Freitext, nicht gespeichert: {leaks}")
    unknown = set(extra) - {"document", "criterion_ref", "role", "model", "skill_version", "override_reason"}
    if unknown:
        raise ValueError(f"Unbekannte Felder: {sorted(unknown)}")
    if status == "ueberstimmt" and not extra.get("override_reason"):
        raise ValueError("Überstimmung braucht override_reason")
    cols = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_id": case_id, "decision": decision, "rationale": rationale,
        "actor": actor, "status": status, **extra,
    }
    sql = f"INSERT INTO decisions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    with con:
        return con.execute(sql, list(cols.values())).lastrowid
