"""Erzeugt erfundene Schultexte + Lösungsdateien.

Prinzip: Python wählt die Fakten (Namen, Schreibvarianten, Orte, Daten, indirekte
Hinweise) und gibt sie dem LLM als Pflicht-Bausteine vor. Das LLM schreibt nur den
Text drumherum. Lösungsdatei = alle Bausteine, die wörtlich im Text gelandet sind.
So ist die Ground Truth verlässlich, auch wenn das LLM einzelne Bausteine auslässt.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from itertools import cycle
from pathlib import Path
from typing import Any

from rich import print

from . import llm
from .config import project_path
from .namelist import Person, load_namelist

TYPES = {
    "schuelergutachten": "ein Schülergutachten (z. B. zum Übergang in die weiterführende Schule), 250–400 Wörter",
    "zeugnisbemerkung": "eine Zeugnisbemerkung zum Arbeits- und Sozialverhalten, 120–200 Wörter",
    "foerderplan": "einen Auszug aus einem Förderplan mit Ausgangslage und Zielen, 200–350 Wörter",
    "elternbrief": "einen Brief der Klassenleitung an die Eltern, 150–250 Wörter",
    "projektbericht": "eine Bewertung eines Schülerprojektberichts mit Begründung der Note, 200–300 Wörter",
}

ORTE = ["Kiel", "Cottbus", "Rostock", "Erfurt", "Gera", "Brandenburg an der Havel", "Neuruppin",
        "Frankfurt (Oder)", "Wittenberge", "Bad Belzig", "Eberswalde", "Hamburg"]
EINRICHTUNGEN = ["Praxis Dr. Weber", "Kita Sonnenblume", "SV Grün-Weiß Werder", "Musikschule Fröhlich",
                 "Grundschule am Weinberg", "Ergotherapie Lindenhof", "Jugendclub Kiste"]
# (Hinweis, Kategorie, erwartet, Verallgemeinerung) – Pool "dev": zum Tunen
INDIREKT = [
    ("seit dem Umzug aus {ort}", "BIOGRAFIE", "generalize", "seit einem Umzug"),
    ("nach der Trennung der Eltern", "FAMILIE", "local_only", "nach einer familiären Veränderung"),
    ("seit dem Tod der Großmutter", "FAMILIE", "local_only", "seit einem belastenden Ereignis in der Familie"),
    ("die festgestellte Lese-Rechtschreib-Schwäche", "GESUNDHEIT", "local_only", "der Förderbedarf im Lesen und Schreiben"),
    ("wegen der ADHS-Diagnose", "GESUNDHEIT", "local_only", "wegen eines festgestellten Förderbedarfs"),
    ("das einzige Kind mit Rollstuhl in der Jahrgangsstufe", "MERKMAL", "local_only", "ein Kind mit besonderem Unterstützungsbedarf"),
    ("seit der Geburt der Zwillingsschwestern", "FAMILIE", "generalize", "seit einer Veränderung in der Familie"),
    ("die Landesmeisterin im Schach", "MERKMAL", "generalize", "sehr erfolgreich in einem Hobby"),
    ("der Vater ist seit dem Frühjahr arbeitslos", "FAMILIE", "local_only", "die Familie ist derzeit belastet"),
    ("die Familie spricht zu Hause Arabisch", "HERKUNFT", "local_only", "die Familie ist mehrsprachig"),
    ("nimmt wegen ihres Glaubens nicht am Schwimmunterricht teil", "HERKUNFT", "local_only", "nimmt nicht am Schwimmunterricht teil"),
    ("wohnt seit dem Sommer in einer Wohngruppe", "FAMILIE", "local_only", "lebt in einer veränderten Wohnsituation"),
    ("ist im Herbst aus der Ukraine zu uns gekommen", "HERKUNFT", "local_only", "ist neu an unsere Schule gekommen"),
]
# Pool "holdout": andere Muster, nur für die Endkontrolle – nie zum Tunen verwenden
INDIREKT_HOLDOUT = [
    ("nach dem Wechsel von der Waldorfschule in {ort}", "BIOGRAFIE", "generalize", "nach einem Schulwechsel"),
    ("seit der schweren Erkrankung der Mutter", "FAMILIE", "local_only", "seit einer belastenden Situation in der Familie"),
    ("wegen ihrer Diabetes-Erkrankung", "GESUNDHEIT", "local_only", "aus gesundheitlichen Gründen"),
    ("der einzige Junge mit Hörgerät an unserer Schule", "MERKMAL", "local_only", "ein Kind mit besonderem Unterstützungsbedarf"),
    ("seit die Familie im Frauenhaus lebt", "FAMILIE", "local_only", "seit einer veränderten Wohnsituation"),
    ("die Eltern stammen aus Syrien", "HERKUNFT", "local_only", "die Familie hat Migrationsgeschichte"),
    ("Bundessiegerin bei Jugend forscht", "MERKMAL", "generalize", "sehr erfolgreich bei einem Wettbewerb"),
    ("mit diagnostiziertem Asperger-Syndrom", "GESUNDHEIT", "local_only", "mit besonderem Förderbedarf"),
    ("seit der Inhaftierung des Vaters", "FAMILIE", "local_only", "seit einer belastenden Situation in der Familie"),
    ("als Pflegekind bei den Großeltern", "FAMILIE", "local_only", "in einer besonderen Familiensituation"),
]

# Review 3.10: Personen und Kontakte, die auf KEINER Liste stehen – das reale Leckrisiko
FREMDE = ["ihre Freundin Jule Martens", "sein Freund Ole Petersen", "die Nachbarin Frau Kowalczyk",
          "der Kinderarzt Dr. Haberland", "die Lerntherapeutin Frau Sommerfeld", "Trainer Marco Rinaldi",
          "die Tante Gisela Brenner", "der Logopäde Herr Okafor"]
KONTAKTE = [("{v}.{n}@web.de", "KONTAKT_EMAIL"), ("0331 {t}", "KONTAKT_TELEFON"),
            ("0176 {t}", "KONTAKT_TELEFON"), ("Lindenstraße {h}", "ADRESSE"), ("Am Weinberg {h}", "ADRESSE")]

SYSTEM = """Du schreibst realistische, aber vollständig erfundene Texte aus dem Schulalltag in Deutschland.
Du bekommst Pflicht-Bausteine. Jeden Baustein musst du WÖRTLICH und unverändert (gleiche Schreibweise,
gleiche Groß-/Kleinschreibung, gleiche Endung) in den Text einbauen. Erfinde KEINE weiteren Personennamen,
Orte, Einrichtungen oder Daten. Antworte nur mit JSON: {"text": "..."}"""


def _variant(p: Person, rng: random.Random) -> list[tuple[str, str]]:
    """Wählt 2–4 Schreibweisen einer Person, inkl. schwieriger Fälle."""
    forms = [f"{p.vorname} {p.nachname}", p.vorname, p.vorname + "s"]
    if p.kurzformen:
        forms.append(rng.choice(p.kurzformen))
    hard = rng.random()
    if hard < 0.2:
        forms.append(f"{p.nachname}, {p.vorname}")
    elif hard < 0.35:
        forms.append(p.vorname.lower())
    elif hard < 0.5 and len(p.nachname) >= 6:  # Tippfehler: ein Buchstabe doppelt/fehlt
        n = p.nachname
        i = rng.randrange(1, len(n) - 1)
        forms.append(f"{p.vorname} {n[:i] + n[i + 1:] if rng.random() < .5 else n[:i] + n[i] + n[i:]}")
    picked = [forms[0]] + rng.sample(forms[1:], k=min(len(forms) - 1, rng.randint(1, 3)))
    return [(f, "PERSON_SCHUELER") for f in picked]


def make_spec(i: int, people: list[Person], rng: random.Random, pool: str = "dev") -> dict[str, Any]:
    typ = list(TYPES)[i % len(TYPES)]
    schueler = rng.choice([p for p in people if p.rolle == "schueler"])
    lehr = rng.choice([p for p in people if p.rolle == "lehrkraft"])
    bausteine = _variant(schueler, rng)
    anrede = {"w": "Frau", "m": "Herr"}.get(lehr.geschlecht) or rng.choice(["Frau", "Herr"])
    bausteine.append((f"{anrede} {lehr.nachname}", "PERSON_LEHRKRAFT"))
    fam = [p for p in people if p.nachname == schueler.nachname and p is not schueler]
    for f in fam[:1]:
        cat = "PERSON_ELTERN" if f.rolle == "eltern" else "PERSON_GESCHWISTER"
        bausteine.append((f.vorname if f.rolle == "geschwister" else f"{f.vorname} {f.nachname}", cat))
    if rng.random() < 0.6:
        bausteine.append((f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.{rng.randint(2010, 2016)}",
                          "DATUM_GEBURT"))
    if pool != "dev" or rng.random() < 0.5:  # Holdout immer mit "fremden" Angaben
        bausteine.append((rng.choice(FREMDE), "PERSON_DRITTE"))
        tpl, cat = rng.choice(KONTAKTE)
        bausteine.append((tpl.format(v=schueler.vorname.lower(), n=schueler.nachname.lower(),
                                     t=rng.randint(1000000, 9999999), h=rng.randint(1, 120)), cat))
    ort = rng.choice(ORTE)
    if rng.random() < 0.5:
        bausteine.append((rng.choice(EINRICHTUNGEN), "EINRICHTUNG"))
    indirect = []
    hints = INDIREKT_HOLDOUT if pool.startswith("holdout") else INDIREKT
    for tpl, cat, exp, gen in rng.sample(hints, k=rng.randint(1, 3)):
        txt = tpl.format(ort=ort)
        indirect.append({"text": txt, "category": cat, "expected": exp, "generalized": gen})
        if "{ort}" in tpl:
            bausteine.append((ort, "ORT"))
    return {"id": f"doc_{i:03d}", "type": typ, "pool": pool, "person": schueler.placeholder,
            "direct": [{"text": t, "category": c} for t, c in bausteine], "indirect": indirect}


def _prompt(spec: dict[str, Any]) -> str:
    items = [d["text"] for d in spec["direct"]] + [d["text"] for d in spec["indirect"]]
    return (f"Schreibe {TYPES[spec['type']]}.\nPflicht-Bausteine (wörtlich verwenden):\n"
            + "\n".join(f"- {t}" for t in items))


def check_ground_truth(text: str, gt: dict[str, Any]) -> list[str]:
    """Gibt alle Einträge zurück, die NICHT im Text vorkommen (leer = konsistent)."""
    entries = gt.get("direct", []) + gt.get("indirect", [])
    return [e["text"] for e in entries if e["text"] not in text]


def _one(cfg: dict[str, Any], spec: dict[str, Any], host: str, out_txt: Path, out_gt: Path) -> str:
    resp = llm.chat_json(cfg, SYSTEM, _prompt(spec), host=host)
    text = str(resp.get("text", "")).strip()
    missing = set(check_ground_truth(text, spec))
    gt = {**spec,
          "direct": [d for d in spec["direct"] if d["text"] not in missing],
          "indirect": [d for d in spec["indirect"] if d["text"] not in missing],
          "dropped": sorted(missing), "host": host, "model": cfg["llm"]["model"]}
    gt["sensitive_level"] = "hoch" if any(d["expected"] == "local_only" for d in gt["indirect"]) else "mittel"
    out_txt.write_text(text + "\n", encoding="utf-8")
    out_gt.write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"{spec['id']} ({host}) {len(text.split())} Wörter, fehlend: {len(missing)}"


def run(cfg: dict[str, Any], n: int = 40, seed: int = 7, start: int = 1, pool: str = "dev") -> None:
    people = load_namelist(project_path(cfg["namelist"]["path"]))
    rng = random.Random(seed + start)
    syn, gtd = project_path(cfg["paths"]["synthetic"]), project_path(cfg["paths"]["ground_truth"])
    hosts = llm.available_hosts(cfg)
    if not hosts:
        raise SystemExit("Kein Ollama-Host erreichbar (studio/desktop).")
    print(f"Hosts: {hosts}")
    specs = [make_spec(i, people, rng, pool) for i in range(start, start + n)]
    jobs = [(s, h) for s, h in zip(specs, cycle(hosts))]
    with ThreadPoolExecutor(max_workers=len(hosts)) as ex:
        futs = [ex.submit(_one, cfg, s, h, syn / f"{s['id']}.txt", gtd / f"{s['id']}.json")
                for s, h in jobs]
        for f in futs:
            try:
                print(f.result())
            except Exception as e:  # ein kaputter Text soll den Lauf nicht abbrechen
                print(f"[red]Fehler: {e}")
