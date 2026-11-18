"""Zentrale Definition der Platzhalter – eine Regel für alle Stufen (Review-Befund 4.1)."""

from __future__ import annotations

import re

# <<SCHUELERIN_01>>, <<DATE_3>>, <<FAMILIE_02>>; optional Genitiv-s/Apostroph direkt dahinter
PLACEHOLDER = re.compile(r"<<[A-Z_]+_\d+>>")
PLACEHOLDER_GEN = re.compile(r"<<[A-Z_]+_\d+>>['s]?")


def mask(text: str) -> str:
    """Ersetzt Platzhalter (inkl. Genitiv) durch gleich lange Leerzeichen – Offsets bleiben gültig."""
    return PLACEHOLDER_GEN.sub(lambda m: " " * len(m.group(0)), text)


def touches(start: int, end: int, text: str) -> bool:
    """True, wenn der Bereich [start, end) einen Platzhalter berührt."""
    return any(start < m.end() and end > m.start() for m in PLACEHOLDER_GEN.finditer(text))
