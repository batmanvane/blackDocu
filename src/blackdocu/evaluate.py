"""Leckrate gegen ground_truth messen, kumulativ pro Stufe → report.md + metrics.json.

Metriken je Stufe (1, 1+2, 1+2+3):
- Leckrate direkt: Anteil der direct-Einträge, von denen noch ein Namensteil im Text steht
- Leckrate indirekt: Anteil der indirect-Hinweise, die (nach Abzug direkter Namen) noch
  im Wesentlichen im Text stehen (unscharfer Abgleich, Score >= 85)
- Übermaskierung: Anteil der Wörter, die verändert wurden, obwohl sie zu keinem
  Lösungseintrag gehören
Dazu: Sperrquote (Stufe 4), Trefferquote local_only, Laufzeit.
"""

from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from .config import project_path

from .placeholders import PLACEHOLDER_GEN as PLACEHOLDER  # noqa: E402
WORD = re.compile(r"[\wÄÖÜäöüß.-]+")
STOP = {"frau", "herr", "herrn", "dr.", "dr", "praxis", "kita", "sv", "von", "der", "die", "das",
        "am", "im", "und", "an", "in", "ihre", "sein", "seine", "freundin", "freund", "nachbarin",
        "kinderarzt", "lerntherapeutin", "trainer", "tante", "logopäde", "web", "lindenstraße",
        "weinberg", "jugendclub", "musikschule", "ergotherapie", "grundschule", "schule",
        "verein", "sportverein"}  # Gattungswörter von Einrichtungen sind allein nicht identifizierend


def _name_tokens(entry: str) -> list[str]:
    return [t for t in re.findall(r"[\wÄÖÜäöüß]+", entry) if len(t) >= 3 and t.lower() not in STOP]


def direct_leak(entry: str, text: str) -> bool:
    if re.fullmatch(r"[\d.]+", entry):  # Datum
        return entry in text
    if "@" in entry or re.fullmatch(r"[\d ]+", entry):  # E-Mail, Telefon: Lokal- bzw. Ziffernteil
        key = entry.split("@")[0] if "@" in entry else entry.replace(" ", "")[-6:]
        return key in text.replace(" ", "") if "@" not in entry else key in text
    m = re.match(r"(.+?) (\d+)$", entry)  # Adresse: Straße + Hausnummer
    if m:
        return bool(re.search(rf"{re.escape(m.group(1))}\s*{m.group(2)}\b", text))
    low = text.lower()
    stems = [t[:-1] if t.endswith("s") and len(t) > 4 else t for t in _name_tokens(entry)]
    return any(re.search(rf"(?<![\wÄÖÜäöüß]){re.escape(t.lower())}s?(?![\wÄÖÜäöüß])", low)
               for t in stems)


def indirect_leak(entry: str, text: str, direct: list[str]) -> bool:
    phrase = entry
    for d in direct:
        phrase = phrase.replace(d, "")
    phrase = " ".join(phrase.split())
    clean = " ".join(PLACEHOLDER.sub(" ", text).split())
    if len(phrase) < 6:
        return False
    return fuzz.partial_ratio(phrase.lower(), clean.lower()) >= 85


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95-%-Konfidenzintervall für eine Quote k/n (Review 3.8: kleine Stichproben)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def overmask(orig: str, new: str, gt: dict[str, Any]) -> float:
    a, b = WORD.findall(orig), WORD.findall(new)
    covered = set()
    for e in gt["direct"] + gt["indirect"]:
        covered |= {w.lower() for w in WORD.findall(e["text"])}
    changed = 0
    for op, i1, i2, _, _ in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            changed += sum(1 for w in a[i1:i2] if w.lower() not in covered)
    return changed / max(1, len(a))


def evaluate_run(rdir: Path, gt_dir: Path) -> dict[str, Any]:
    recs = [json.loads(p.read_text()) for p in sorted(rdir.glob("*.json")) if p.name not in
            ("config.json", "metrics.json")]
    levels = sorted({k for r in recs for k in r["stages"] if k != "0"})
    m: dict[str, Any] = {"run": rdir.name, "docs": len(recs), "stages": {}, "leaks": [],
                         "per_category": defaultdict(lambda: defaultdict(lambda: [0, 0]))}
    for lv in levels:
        dl = dn = il = inn = 0
        om = []
        for r in recs:
            gt = json.loads((gt_dir / f"{r['id']}.json").read_text())
            text = r["stages"][lv]
            directs = [d["text"] for d in gt["direct"]]
            for d in gt["direct"]:
                leak = direct_leak(d["text"], text)
                dl += leak
                dn += 1
                pc = m["per_category"][lv][d["category"]]
                pc[0] += leak
                pc[1] += 1
                if leak and lv == levels[-1]:
                    m["leaks"].append({"doc": r["id"], "kind": "direkt", "text": d["text"],
                                       "category": d["category"]})
            for d in gt["indirect"]:
                leak = indirect_leak(d["text"], text, directs)
                il += leak
                inn += 1
                pc = m["per_category"][lv][d["category"]]
                pc[0] += leak
                pc[1] += 1
                if leak and lv == levels[-1]:
                    m["leaks"].append({"doc": r["id"], "kind": "indirekt", "text": d["text"],
                                       "category": d["category"]})
            om.append(overmask(r["stages"]["0"], text, gt))
        m["stages"][lv] = {"direct_leak": dl / max(1, dn), "direct_n": dn, "direct_k": dl, "indirect_k": il,
                           "indirect_leak": il / max(1, inn), "indirect_n": inn,
                           "overmask": sum(om) / max(1, len(om))}
    # Review 3.1/3.6: was verlässt nach der Prüfstufe tatsächlich das Gate?
    last = levels[-1]
    gate: dict[str, dict[str, int]] = {}
    for scope, ok in (("nicht_gesperrt", lambda r: not r.get("blocked")),
                      ("extern_freigegeben", lambda r: not r.get("blocked") and not r.get("local_only"))):
        g = {"docs": 0, "direct_k": 0, "direct_n": 0, "indirect_k": 0, "indirect_n": 0}
        for r in recs:
            if not ok(r):
                continue
            gt = json.loads((gt_dir / f"{r['id']}.json").read_text())
            directs = [d["text"] for d in gt["direct"]]
            g["docs"] += 1
            for d in gt["direct"]:
                g["direct_k"] += direct_leak(d["text"], r["stages"][last])
                g["direct_n"] += 1
            for d in gt["indirect"]:
                g["indirect_k"] += indirect_leak(d["text"], r["stages"][last], directs)
                g["indirect_n"] += 1
        gate[scope] = g
    m["gate"] = gate
    blocked_leaky = 0
    for r in recs:
        if r.get("blocked"):
            gt = json.loads((gt_dir / f"{r['id']}.json").read_text())
            blocked_leaky += any(direct_leak(d["text"], r["stages"][last]) for d in gt["direct"])
    m["blocked_with_leak"] = blocked_leaky  # zu Recht gesperrt
    # Sperrquote, local_only, Laufzeit
    m["blocked"] = sum(1 for r in recs if r.get("blocked"))
    tp = fp = fn = tn = 0
    for r in recs:
        gt = json.loads((gt_dir / f"{r['id']}.json").read_text())
        exp = any(d["expected"] == "local_only" for d in gt["indirect"])
        got = bool(r.get("local_only"))
        tp += exp and got
        fp += got and not exp
        fn += exp and not got
        tn += not exp and not got
    m["local_only"] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn}
    secs = defaultdict(list)
    for r in recs:
        for k, v in r.get("seconds", {}).items():
            if v is not None:
                secs[k].append(v)
    m["seconds_mean"] = {k: round(sum(v) / len(v), 2) for k, v in secs.items()}
    m["per_category"] = {lv: {c: v for c, v in d.items()} for lv, d in m["per_category"].items()}
    return m


def report(m: dict[str, Any]) -> str:
    L = [f"# Evaluation {m['run']}", "", f"{m['docs']} Texte, gesperrt: {m['blocked']}", "",
         "| Stufen | Leck direkt | Leck indirekt | Übermaskierung |", "|---|---|---|---|"]
    names = {"1": "1", "2": "1+2", "3": "1+2+3"}
    for lv, s in m["stages"].items():
        L.append(f"| {names.get(lv, lv)} | {s['direct_leak']:.1%} (n={s['direct_n']}) | "
                 f"{s['indirect_leak']:.1%} (n={s['indirect_n']}) | {s['overmask']:.1%} |")
    L += ["", "## Nach der Prüfstufe (was das Gate passiert)", "",
          "| Bereich | Texte | Lecks direkt | Lecks indirekt |", "|---|---|---|---|"]
    for scope, g in m.get("gate", {}).items():
        dlo, dhi = wilson(g["direct_k"], g["direct_n"])
        ilo, ihi = wilson(g["indirect_k"], g["indirect_n"])
        L.append(f"| {scope.replace('_', ' ')} | {g['docs']} | {g['direct_k']}/{g['direct_n']} "
                 f"(95 %-KI {dlo:.1%}–{dhi:.1%}) | {g['indirect_k']}/{g['indirect_n']} "
                 f"(95 %-KI {ilo:.1%}–{ihi:.1%}) |")
    L.append(f"\nGesperrt: {m['blocked']}, davon mit echtem Leck (zu Recht): {m.get('blocked_with_leak', 0)}")
    lo = m["local_only"]
    L += ["", f"local_only: richtig erkannt {lo['tp']}, übersehen {lo['fn']}, "
              f"unnötig {lo['fp']}, korrekt nicht {lo['tn']}",
          f"Laufzeit je Text (s): {m['seconds_mean']}", "", "## Leckrate je Kategorie (letzte Stufe)", "",
          "| Kategorie | Lecks | n |", "|---|---|---|"]
    last = list(m["per_category"])[-1]
    for c, (k, n) in sorted(m["per_category"][last].items()):
        L.append(f"| {c} | {k} ({k / n:.0%}) | {n} |")
    L += ["", "## Lecks (letzte Stufe)", ""]
    L += [f"- {x['doc']} · {x['kind']} · {x['category']}: „{x['text']}“" for x in m["leaks"]] or ["keine"]
    return "\n".join(L) + "\n"


def run(cfg: dict[str, Any], rdir: Path | None = None) -> dict[str, Any]:
    runs_dir = project_path("out/runs")
    runs = sorted(runs_dir.iterdir()) if runs_dir.exists() else []
    if rdir is None and not runs:
        raise SystemExit("Noch kein Lauf vorhanden – erst `blackdocu run` ausführen.")
    rdir = rdir or runs[-1]
    m = evaluate_run(rdir, project_path(cfg["paths"]["ground_truth"]))
    (rdir / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2))
    md = report(m)
    (rdir / "report.md").write_text(md)
    project_path(cfg["paths"]["report"]).write_text(md)
    print(md)
    return m


def compare() -> str:
    """Tabelle aller Läufe – Grundlage fürs Tuning."""
    L = ["| Lauf | Leck direkt | Leck indirekt | Übermask. | gesperrt | local_only übersehen | s/Text St.3 |",
         "|---|---|---|---|---|---|---|"]
    for d in sorted(project_path("out/runs").iterdir()):
        p = d / "metrics.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text())
        if not m.get("stages"):
            continue
        s = m["stages"][list(m["stages"])[-1]]
        L.append(f"| {m['run']} | {s['direct_leak']:.1%} | {s['indirect_leak']:.1%} | "
                 f"{s['overmask']:.1%} | {m['blocked']}/{m['docs']} | {m['local_only']['fn']} | "
                 f"{m['seconds_mean'].get('3', '-')} |")
    return "\n".join(L)
