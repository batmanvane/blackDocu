"""Ansatz 2: Beispielbank für Stufe 3 (Retrieval von ähnlichen, geprüften Fällen).

Die Bank liegt in SQLite (Tabelle `examples` in der Entscheidungs-DB) und enthält
nur pseudonymisierte Sätze. Quellen:
- "synthetisch": aus Lösungsdateien des Dev-Sets erzeugt (Phase 1)
- "mensch": später aus Korrekturen/Überstimmungen von Lehrkräften

Suche: Embeddings über Ollama (qwen3-embedding), Fallback rapidfuzz.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ollama
from rapidfuzz import fuzz

from .config import project_path
from .generate_synthetic import INDIREKT

SCHEMA = """
CREATE TABLE IF NOT EXISTS examples (
  id          INTEGER PRIMARY KEY,
  created_at  TEXT NOT NULL,
  source      TEXT NOT NULL,          -- synthetisch | mensch
  doc_id      TEXT,                   -- Herkunftsdokument (zum Ausschließen beim Testen)
  text        TEXT NOT NULL,          -- pseudonymisierter Satz/Absatz
  findings    TEXT NOT NULL,          -- JSON wie Stufe-3-Antwort
  embedding   TEXT                    -- JSON-Liste
);
"""
SENT = re.compile(r"(?<=[.!?])\s+")
GEN = {re.sub(r"\{ort\}.*", "", t): g for t, _, _, g in INDIREKT}


def connect(cfg: dict[str, Any]) -> sqlite3.Connection:
    p = project_path(cfg["paths"]["decisions_db"])
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, check_same_thread=False)
    con.executescript(SCHEMA)
    return con


def embed(cfg: dict[str, Any], texts: list[str]) -> list[list[float]] | None:
    fc = cfg.get("fewshot", {})
    host = fc.get("embed_host", "desktop")
    try:
        c = ollama.Client(host=llm.assert_local(cfg["llm"]["hosts"][host]), timeout=60)
        return c.embed(model=fc.get("embed_model", "qwen3-embedding:0.6b"), input=texts)["embeddings"]
    except ValueError:
        raise
    except Exception as e:  # Review 4.3: nicht still schlucken
        print(f"[Beispielbank] Embeddings nicht verfügbar ({type(e).__name__}: {e}) – nutze Wortähnlichkeit")
        return None


def _generalize(phrase: str) -> str:
    for prefix, g in GEN.items():
        if phrase.startswith(prefix):
            return g
    return "eine allgemeine Formulierung"


def build_bank(cfg: dict[str, Any], run_dir: Path, doc_ids: list[str], negatives: int = 1) -> int:
    """Erzeugt Beispiele aus Lösungsdateien + Stufe-2-Texten eines Laufs."""
    con = connect(cfg)
    con.execute("DELETE FROM examples WHERE source = 'synthetisch'")
    gt_dir = project_path(cfg["paths"]["ground_truth"])
    rows = []
    for d in doc_ids:
        rec = json.loads((run_dir / f"{d}.json").read_text())
        gt = json.loads((gt_dir / f"{d}.json").read_text())
        sents = SENT.split(rec["stages"]["2"])
        used = set()
        for ind in gt["indirect"]:
            phrase = ind["text"]
            for o in [x["text"] for x in gt["direct"]]:
                phrase = phrase.replace(o, "").strip()
            best = max(range(len(sents)), key=lambda i: fuzz.partial_ratio(phrase, sents[i]))
            al = fuzz.partial_ratio_alignment(phrase, sents[best])
            if al.score < 85:
                continue
            span = sents[best][al.dest_start:al.dest_end]
            f = {"span": span, "replacement": ind.get("generalized") or _generalize(ind["text"]),
                 "category": ind["category"], "sensitive": ind["expected"] == "local_only"}
            rows.append((d, sents[best], [f]))
            used.add(best)
        free = [s for i, s in enumerate(sents) if i not in used and len(s) > 60]
        for s in free[:negatives]:
            rows.append((d, s, []))
    # Review 1.14: Sätze mit Restnamen/Daten nie in die Bank (falls Stufe 1/2 etwas übersehen hat)
    from .decisions_db import find_clear_names
    from .namelist import load_namelist

    people = load_namelist(project_path(cfg["namelist"]["path"]))
    before = len(rows)
    rows = [r for r in rows if not find_clear_names({"rationale": r[1]}, people)]
    if len(rows) < before:
        print(f"[Beispielbank] {before - len(rows)} Sätze mit Restnamen/Daten verworfen")
    embs = embed(cfg, [r[1] for r in rows]) or [None] * len(rows)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany(
        "INSERT INTO examples (created_at, source, doc_id, text, findings, embedding) VALUES (?,?,?,?,?,?)",
        [(now, "synthetisch", d, t, json.dumps({"findings": f}, ensure_ascii=False),
          json.dumps(e) if e else None) for (d, t, f), e in zip(rows, embs)])
    con.commit()
    return len(rows)


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


class Retriever:
    """Liefert die k ähnlichsten Beispiele zu einem Text (ohne das eigene Dokument)."""

    def __init__(self, cfg: dict[str, Any], k: int = 4):
        self.cfg, self.k = cfg, k
        con = connect(cfg)
        self.rows = [(d, t, json.loads(f), json.loads(e) if e else None)
                     for d, t, f, e in con.execute("SELECT doc_id, text, findings, embedding FROM examples")]

    def __call__(self, text: str, doc_id: str | None = None) -> list[dict]:
        cand = [r for r in self.rows if r[0] != doc_id]
        if not cand:
            return []
        q = embed(self.cfg, [text]) if cand[0][3] else None
        if q:
            scored = sorted(cand, key=lambda r: -_cos(q[0], r[3]) if r[3] else 0)
        else:
            scored = sorted(cand, key=lambda r: -fuzz.token_set_ratio(text, r[1]))
        # Mischung: überwiegend positive Beispiele, ein negatives gegen Übermaskierung
        pos = [r for r in scored if r[2]["findings"]][: self.k - 1]
        neg = [r for r in scored if not r[2]["findings"]][:1]
        return [{"text": r[1], "antwort": r[2]} for r in pos + neg]
