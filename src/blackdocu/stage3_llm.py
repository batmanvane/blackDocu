"""Stufe 3: indirekte Hinweise über lokales LLM (Ollama) verallgemeinern.

Das LLM schlägt nur vor. Ersetzt wird deterministisch und nur, wenn der Span
exakt im Text steht und keinen Platzhalter berührt. Prompts liegen versioniert
unter prompts/stage3/<version>.md, damit Tuning-Läufe vergleichbar bleiben.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from rapidfuzz import fuzz

from . import llm
from .config import project_path

from .placeholders import PLACEHOLDER
# Kategorien, die immer "nur lokal" auslösen – unabhängig vom sensitive-Flag des LLM (Review 1.3)
SENSITIVE_CATEGORIES = {"GESUNDHEIT", "HERKUNFT", "FAMILIE"}


def load_prompt(version: str) -> str:
    text = project_path(f"prompts/stage3/{version}.md").read_text(encoding="utf-8")
    return re.sub(r"^<!--.*?-->\n", "", text, flags=re.S)  # Kopfzeile mit Herkunft entfernen


def locate(text: str, span: str, min_score: float = 90.0) -> tuple[int, int, str] | None:
    """Findet den Span im Text: exakt, sonst unscharf (LLMs zitieren nicht immer wörtlich).

    Gibt (start, end, Methode) zurück oder None.
    """
    i = text.find(span)
    if i >= 0:
        return i, i + len(span), "exact"
    al = fuzz.partial_ratio_alignment(span, text)
    if al and al.score >= min_score and abs((al.dest_end - al.dest_start) - len(span)) <= 3:
        return al.dest_start, al.dest_end, f"fuzzy:{al.score:.0f}"
    return None


def apply_findings(text: str, findings: list[dict]) -> tuple[str, list[dict], bool]:
    """Wendet LLM-Vorschläge an. Gibt (Text, angewandte, local_only) zurück.

    Ein Span darf Platzhalter enthalten (dann verschwindet der Hinweis mitsamt Platzhalter),
    die Ersetzung darf keine enthalten.
    """
    applied, local_only = [], False
    for f in findings:
        if not isinstance(f, dict):
            continue
        span, repl = str(f.get("span", "")).strip(), str(f.get("replacement", "")).strip()
        if f.get("sensitive") or f.get("category") in SENSITIVE_CATEGORIES:
            local_only = True
        pos = locate(text, span) if span and len(span) >= 3 else None
        same = repl.strip().lower() == span.strip().lower()  # "Ersetzung" ohne Änderung (Review 2.13)
        if pos is None or same or PLACEHOLDER.search(repl):
            f["status"] = "verworfen"
            continue
        a, b, how = pos
        found = text[a:b]
        text = text.replace(found, repl)  # alle Vorkommen, nicht nur das erste
        f["status"] = f"angewandt:{how}"
        applied.append(f)
    return text, applied, local_only


class Stage3:
    def __init__(self, cfg: dict[str, Any], chat: Callable[..., Any] | None = None,
                 examples: Callable[..., list[dict]] | None = None):
        self.cfg = cfg
        s3 = cfg.get("stage3", {})
        self.version = s3.get("prompt", "v1")
        self.system = load_prompt(self.version)
        self.chat = chat or llm.chat_json
        self.examples = examples  # Ansatz 2: ähnliche Fälle als Beispiele (später)

    def redact(self, text: str, doc_id: str | None = None) -> tuple[str, list[dict], bool, dict]:
        user = text
        shots = []
        if self.examples:
            shots = self.examples(text, doc_id)
            if shots:
                user = ("Beispiele früherer, geprüfter Fälle:\n"
                        + "\n".join(json.dumps(s, ensure_ascii=False) for s in shots)
                        + "\n\nText:\n" + text)
        t0 = time.time()
        resp = self.chat(self.cfg, self.system, user)
        findings = resp.get("findings", []) if isinstance(resp, dict) else []
        out, applied, local_only = apply_findings(text, findings)
        meta = {"prompt": self.version, "seconds": round(time.time() - t0, 1),
                "proposed": len(findings), "applied": len(applied), "shots": len(shots)}
        return out, findings, local_only, meta
