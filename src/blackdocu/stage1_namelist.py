"""Stufe 1: exakte und unscharfe Ersetzung über die Namensliste.

Ablauf:
1. Alle Schreibvarianten aller Personen in einen Regex (längste zuerst, Wortgrenzen,
   Groß-/Kleinschreibung egal).
2. Übrige großgeschriebene Wörter ab 6 Buchstaben unscharf (rapidfuzz) gegen
   Varianten ab 6 Buchstaben prüfen – fängt Tippfehler wie "Hofmann".
3. Ersetzen in einem Durchgang über die gesammelten, nicht überlappenden Spans.

Varianten, die mehreren Personen gehören (z. B. Nachname einer Familie),
bekommen einen gemeinsamen Platzhalter <<FAMILIE_nn>> bzw. <<MEHRDEUTIG_nn>>.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .namelist import Person

WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'-]*")
FUZZY_MIN_LEN = 6


@dataclass
class Index:
    exact: re.Pattern
    lookup: dict[str, str]  # Variante (klein) -> Platzhalter
    fuzzy_targets: dict[str, str]  # Variante (klein, ein Wort, >= 6 Zeichen) -> Platzhalter
    reverse: dict[str, str]  # Platzhalter -> Klartext für die Rückwandlung


def build_index(people: list[Person]) -> Index:
    owners: dict[str, set[str]] = {}
    surname_of: dict[str, str] = {}
    for p in people:
        for v in p.variants():
            owners.setdefault(v.lower(), set()).add(p.placeholder)
        surname_of[p.placeholder] = p.nachname

    shared: dict[str, str] = {}
    counters: dict[str, int] = {}
    lookup: dict[str, str] = {}
    for v, phs in sorted(owners.items()):
        if len(phs) == 1:
            lookup[v] = next(iter(phs))
            continue
        surnames = {surname_of[ph] for ph in phs}
        kind = "FAMILIE" if len(surnames) == 1 else "MEHRDEUTIG"
        key = f"{kind}:{next(iter(surnames)) if kind == 'FAMILIE' else v}"
        if key not in shared:
            counters[kind] = counters.get(kind, 0) + 1
            shared[key] = f"<<{kind}_{counters[kind]:02d}>>"
        lookup[v] = shared[key]

    reverse: dict[str, str] = {}
    for p in people:
        reverse[p.placeholder] = p.vorname if p.rolle in ("schueler", "geschwister") \
            else f"{p.vorname} {p.nachname}"
    for key, ph in shared.items():
        reverse[ph] = key.split(":", 1)[1] if key.startswith("FAMILIE") else key.split(":", 1)[1]

    variants = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\wÄÖÜäöüß])(" + "|".join(re.escape(v) for v in variants) + r")(?![\wÄÖÜäöüß])",
        re.IGNORECASE,
    )
    fuzzy_targets = {
        v: ph for v, ph in lookup.items()
        if " " not in v and "," not in v and len(v) >= FUZZY_MIN_LEN
    }
    return Index(pattern, lookup, fuzzy_targets, reverse)


def find_spans(text: str, index: Index, fuzzy_threshold: int = 90) -> list[dict]:
    hits: list[dict] = []
    taken = [False] * len(text)
    for m in index.exact.finditer(text):
        low = m.group(0).lower()
        ph, suffix = index.lookup[low], ""
        # Genitiv erhalten: "Lenas" -> "<<SCHUELER_01>>s", damit der Satz lesbar bleibt
        if low[-1] in "s'" and index.lookup.get(low[:-1]) == ph:
            suffix = m.group(0)[-1]
        hits.append({"start": m.start(), "end": m.end(), "text": m.group(0),
                     "placeholder": ph, "suffix": suffix, "method": "exact"})
        taken[m.start():m.end()] = [True] * (m.end() - m.start())

    for m in WORD.finditer(text):
        tok = m.group(0)
        if len(tok) < FUZZY_MIN_LEN or not tok[0].isupper() or tok.isupper():
            continue  # kurze Wörter, Kleinschreibung, Abkürzungen/Platzhalter
        if any(taken[m.start():m.end()]):
            continue
        best, score = None, 0.0
        for cand in {tok.lower(), tok.lower().rstrip("s")}:
            for v, ph in index.fuzzy_targets.items():
                s = fuzz.ratio(cand, v)
                if s > score:
                    best, score = ph, s
        if best and score >= fuzzy_threshold:
            hits.append({"start": m.start(), "end": m.end(), "text": tok,
                         "placeholder": best, "method": f"fuzzy:{score:.0f}"})
    return sorted(hits, key=lambda h: h["start"])


def apply_spans(text: str, hits: list[dict]) -> str:
    out, pos = [], 0
    for h in hits:
        out.append(text[pos:h["start"]])
        out.append(h["placeholder"] + h.get("suffix", ""))
        pos = h["end"]
    out.append(text[pos:])
    return "".join(out)


def redact(text: str, people: list[Person], fuzzy_threshold: int = 90) -> tuple[str, list[dict]]:
    """Ersetzt alle Namensvarianten durch Platzhalter. Gibt (Text, Treffer) zurück."""
    hits = find_spans(text, build_index(people), fuzzy_threshold)
    return apply_spans(text, hits), hits


from .placeholders import PLACEHOLDER  # noqa: E402


def reveal(text: str, people: list[Person]) -> str:
    """Setzt Stufe-1-Platzhalter wieder in Klartext um (nur lokal verwenden)."""
    rev = build_index(people).reverse
    return PLACEHOLDER.sub(lambda m: rev.get(m.group(0), m.group(0)), text)
