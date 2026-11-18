"""Fiktive Klassenliste laden und Schreibvarianten der Namen erzeugen.

Spalten: vorname, nachname, rolle, geschlecht (w|m|d, optional), kurzformen (mit | getrennt)

Platzhalter tragen das grammatische Geschlecht (<<SCHUELERIN_01>>, <<VATER_03>>), damit
KI-Texte grammatisch stimmen ("ihre Tochter" statt "seines Sohnes"). Nummeriert wird je Rolle,
die Nummer bleibt also stabil, auch wenn sich das Geschlecht in der Liste ändert.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# Rolle -> Präfix je Geschlecht (w, m, sonst)
ROLE_PREFIX = {
    "schueler": ("SCHUELERIN", "SCHUELER", "SCHUELERKIND"),
    "eltern": ("MUTTER", "VATER", "ELTERNTEIL"),
    "lehrkraft": ("LEHRERIN", "LEHRER", "LEHRKRAFT"),
    "geschwister": ("SCHWESTER", "BRUDER", "GESCHWISTER"),
}


def prefix_for(rolle: str, geschlecht: str) -> str:
    w, m, d = ROLE_PREFIX.get(rolle, ("PERSON", "PERSON", "PERSON"))
    return {"w": w, "m": m}.get(geschlecht, d)


@dataclass
class Person:
    vorname: str
    nachname: str
    rolle: str
    kurzformen: list[str] = field(default_factory=list)
    placeholder: str = ""
    geschlecht: str = ""

    def variants(self) -> list[str]:
        """Alle Schreibweisen, längste zuerst (damit 'Lena Hoffmann' vor 'Lena' ersetzt wird)."""
        v, n = self.vorname, self.nachname
        base = {f"{v} {n}", f"{n}, {v}", v, n, *self.kurzformen}
        if self.rolle in ("lehrkraft", "eltern"):
            if self.geschlecht != "m":
                base.add(f"Frau {n}")
            if self.geschlecht != "w":
                base |= {f"Herr {n}", f"Herrn {n}"}
        out = set()
        for b in base:
            if not b:
                continue
            out.add(b)
            out.add(b + "s" if not b.endswith(("s", "x", "z", "ß")) else b + "'")
        return sorted(out, key=len, reverse=True)


def load_namelist(path: Path) -> list[Person]:
    people: list[Person] = []
    counters: dict[str, int] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rolle = row["rolle"].strip()
            g = (row.get("geschlecht") or "").strip().lower()
            counters[rolle] = counters.get(rolle, 0) + 1
            kurz = [k.strip() for k in (row.get("kurzformen") or "").split("|") if k.strip()]
            people.append(
                Person(
                    vorname=row["vorname"].strip(),
                    nachname=row["nachname"].strip(),
                    rolle=rolle,
                    kurzformen=kurz,
                    geschlecht=g,
                    placeholder=f"<<{prefix_for(rolle, g)}_{counters[rolle]:02d}>>",
                )
            )
    return people
