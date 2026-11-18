"""Stufe 2: noirdoc-Erkenner (Presidio, GLiNER, Flair) mit persistentem Namespace.

Hinweis: noirdocs `Redactor` nimmt Flair nicht in den Verbund auf (Stand 0.2.1),
obwohl die README das andeutet. Deshalb bauen wir den EnsembleDetector selbst
und nutzen noirdocs Mapper/Namespace (verschlüsselt mit Fernet-Schlüssel) für die
Rückführung.

Platzhalter aus Stufe 1 (<<...>>) werden geschützt: Funde, die einen Platzhalter
berühren, werden verworfen.
"""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import Any

from noirdoc.detection.base import DetectedEntity
from noirdoc.namespace import Namespace
from noirdoc.pseudonymization.engine import PseudonymizationEngine
from noirdoc.reidentification.engine import ReidentificationEngine

from .config import project_path

from .placeholders import PLACEHOLDER_GEN as PLACEHOLDER
MONATE = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
MON = rf"(?:{MONATE}|Jan|Feb|Mär|Apr|Jun|Jul|Aug|Sep|Sept|Okt|Nov|Dez)\.?"
# Review 2.7: auch zweistellige Jahre, Tag+Monat ohne Jahr (Geburtstage!), Monat/Jahr
DATE_RE = re.compile(
    r"(?<![\w.])(?:"
    r"\d{1,2}\.\s?\d{1,2}\.\s?(?:(?:19|20)\d{2}|\d{2})(?![\d])"     # 01.08.2014, 1.8.14
    rf"|\d{{1,2}}\.\s?{MON}(?:\s+(?:19|20)\d{{2}})?"                   # 1. August (2014)
    r"|\d{1,2}\.\d{1,2}\.(?=\s|$|[,;)])"                              # 3.5. (Tag+Monat)
    r"|(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}"                              # 08/2014
    r"|(?:19|20)\d{2}-\d{2}-\d{2}"                                    # 2014-08-01
    r")")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE_RE = re.compile(r"(?<![\w])(?:\+49[\s/-]?|0)\d{2,5}[\s/-]?\d{3,}(?:[\s-]?\d{2,})*")


def regex_dates(text: str) -> list[DetectedEntity]:
    """Deterministische Erkennung von Daten, E-Mail-Adressen und Telefonnummern.

    GLiNER übersah Daten zu oft (Basislauf: 30 % Leck); Kontakte sind per Regel sicherer.
    """
    out = []
    for typ, rx in (("DATE", DATE_RE), ("EMAIL", EMAIL_RE), ("PHONE", PHONE_RE)):
        out += [DetectedEntity(entity_type=typ, text=m.group(0).strip(), start=m.start(),
                               end=m.start() + len(m.group(0).rstrip()), score=1.0, source="regex")
                for m in rx.finditer(text)]
    return out


@lru_cache(maxsize=4)
def _ensemble(detectors: tuple[str, ...], threshold: float):
    from noirdoc.detection.ensemble import EnsembleDetector
    from noirdoc.detection.model_manager import ensure_spacy_models

    dets = []
    if "presidio" in detectors:
        from noirdoc.detection.presidio_detector import PresidioDetector

        ensure_spacy_models(["de"])
        dets.append(PresidioDetector(languages=["de"]))
    if "gliner" in detectors:
        from noirdoc.detection.gliner_detector import GlinerDetector

        dets.append(GlinerDetector())
    if "flair" in detectors:
        from noirdoc.detection.flair_detector import FlairDetector

        dets.append(FlairDetector())
    return EnsembleDetector(dets, score_threshold=threshold)


ALLOW_TYPES = {"PERSON", "ORGANIZATION", "LOCATION", "NRP"}  # nie für Daten, Nummern, Kontakte
FILL = {"und", "oder", "der", "die", "das", "im", "in", "am", "an", "zu", "mit", "von", "&"}


def load_allowlist(path) -> set[str]:
    words: set[str] = set()
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                words |= {w.lower() for w in line.split()}
    return words


# typische Endungen deutscher Sachwörter – Personennamen enden praktisch nie so
NOUN_SUFFIX = re.compile(r"(keit|heit|ung|ungen|schaft|tion|ität|nis|nisse|spanne|plan|alltag|einheiten)$")


def _known(tok: str, allow: set[str]) -> bool:
    """Wort steht (ggf. gebeugt: Vaters, Sohnes, Schülers) auf der Liste oder ist ein Sachwort."""
    t = tok.lower()
    if t in allow or (len(t) >= 7 and NOUN_SUFFIX.search(t)):  # "Jung", "Heit" bleiben Namen
        return True
    return any(t.endswith(e) and t[: -len(e)] in allow for e in ("s", "es", "n", "en", "e"))


def allowed(text: str, allow: set[str]) -> bool:
    """True, wenn ein Fund nur aus erlaubten Schul-/Familienwörtern, Sachwörtern, Zahlen und Füllwörtern besteht."""
    toks = re.findall(r"[\wÄÖÜäöüß-]+", text)
    if not any(_known(t, allow) for t in toks) or re.search(r"\d[.\-/]\d", text):
        return False  # mindestens ein bekanntes Wort, und nichts, was wie ein Datum aussieht
    return all(_known(t, allow) or t.lower() in FILL or t.isdigit() for t in toks)


class Stage2:
    def __init__(self, cfg: dict[str, Any]):
        nc = cfg["noirdoc"]
        self.detectors = tuple(nc.get("detectors", ["presidio", "gliner", "flair"]))
        self.threshold = float(nc.get("score_threshold", 0.5))
        self.ignore_types = set(nc.get("ignore_types", []))
        self.allow = load_allowlist(project_path(nc.get("allowlist", "data/allowlist.txt")))
        root = nc.get("namespace_root")
        self.ns = Namespace(nc["namespace"], root=project_path(root) if root else None)
        self.mapper = self.ns.load()

    def detect(self, text: str) -> list[DetectedEntity]:
        ents = asyncio.run(_ensemble(self.detectors, self.threshold).detect(text, "de"))
        dates = [d for d in regex_dates(text)
                 if not any(e.start < d.end and e.end > d.start for e in ents)]
        ents = sorted(ents + dates, key=lambda e: e.start)
        protected = [(m.start(), m.end()) for m in PLACEHOLDER.finditer(text)]
        return [
            e for e in ents
            if e.entity_type not in self.ignore_types
            and not (e.entity_type in ALLOW_TYPES and allowed(e.text, self.allow))
            and not any(e.start < b and e.end > a for a, b in protected)
        ]

    def redact(self, text: str) -> tuple[str, list[dict]]:
        ents = self.detect(text)
        out = PseudonymizationEngine().pseudonymize(text, ents, self.mapper)
        if self.mapper.entity_count:
            self.ns.save(self.mapper)
        hits = [{"start": e.start, "end": e.end, "text": e.text, "type": e.entity_type,
                 "score": round(e.score, 3), "source": e.source} for e in ents]
        return out, hits

    def reveal(self, text: str) -> str:
        return ReidentificationEngine().reidentify(text, self.mapper)
