"""Stufe 4: Prüfstufe (Vier-Augen-Prinzip). Findet sie noch etwas, wird gesperrt.

1. Namensliste erneut, exakt und unscharf, auf dem Text ohne Platzhalter
2. Regeln für Daten, E-Mail, Telefon (immer sperren)
3. NER (noirdoc-Ensemble) erneut:
   - PERSON nur von den Quellen in verify.sources (Presidio-PERSON lieferte Fehlalarme)
   - verify.strict_types (Kontakt- und Kennnummern) von jeder Quelle
"""

from __future__ import annotations

from typing import Any

from .namelist import Person
from .stage1_namelist import build_index, find_spans

from .placeholders import mask as _mask_placeholders


def verify(text: str, people: list[Person], cfg: dict[str, Any], stage2=None) -> list[dict]:
    """Gibt die Funde außerhalb von Platzhaltern zurück (leer = Freigabe)."""
    vc = cfg.get("verify", {})
    masked = _mask_placeholders(text)
    found = [{"text": h["text"], "start": h["start"], "check": "namensliste", "method": h["method"]}
             for h in find_spans(masked, build_index(people), vc.get("fuzzy_threshold", 85))]
    from .stage2_noirdoc import regex_dates
    found += [{"text": e.text, "start": e.start, "check": e.entity_type.lower()} for e in regex_dates(masked)]
    if stage2 is not None:
        block = set(vc.get("block_types", ["PERSON"]))
        min_score = vc.get("min_score", 0.6)
        sources = set(vc.get("sources", ["flair", "gliner"]))
        strict = set(vc.get("strict_types", []))
        for e in stage2.detect(text):
            hit_block = e.entity_type in block and e.score >= min_score and e.source in sources
            hit_strict = e.entity_type in strict and e.source != "regex"  # Regeln oben schon geprüft
            if hit_block or hit_strict:
                found.append({"text": e.text, "start": e.start, "check": "ner",
                              "type": e.entity_type, "score": round(e.score, 3), "source": e.source})
    return found
