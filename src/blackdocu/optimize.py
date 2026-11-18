"""Ansatz 1+3: Prompt-Optimierung für Stufe 3 anhand gemessener Fehler (OPRO/APE-Muster).

Schleife:
1. Stufe 3 mit Prompt vN auf dem Dev-Set laufen lassen (Stufe 1+2 aus Basislauf übernommen)
2. messen: Ziel J = Leck indirekt + Übermaskierung(Stufe 3 - Stufe 2) + 0.5 * übersehene local_only-Quote
3. Fehlerliste (Lecks, unnötige Ersetzungen, Grammatikbrüche) + Prompt an das lokale LLM
   → Vorschlag vN+1, gespeichert unter prompts/stage3/
4. bester Prompt gewinnt; Verlauf in out/optimize.jsonl

Nur lokales Modell, nur synthetische Daten.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rich import print

from . import evaluate, llm, pipeline
from .config import project_path

META = """Du verbesserst einen System-Prompt für ein lokales Sprachmodell. Das Modell soll in
pseudonymisierten Schultexten indirekte Hinweise auf Personen finden und verallgemeinern
(Antwortformat JSON mit span/replacement/category/sensitive).

Messwerte des aktuellen Prompts (niedriger ist besser):
{metrics}

Typische Fehler aus der Messung:
{errors}

Aktueller Prompt:
<<<
{prompt}
>>>

Schreibe einen verbesserten, vollständigen Prompt auf Deutsch. Regeln:
- Antwortformat und Kategorien unverändert lassen
- konkrete, prüfbare Anweisungen statt allgemeiner Appelle
- Fehlerursachen gezielt adressieren (z. B. Span muss Artikel/Präposition mitnehmen, damit die
  Ersetzung grammatisch passt; Leistungsbeschreibungen nicht anfassen)
- keine echten oder erfundenen Personennamen
Antworte nur mit JSON: {{"prompt": "...", "changes": ["..."]}}"""


def objective(m: dict[str, Any]) -> float:
    """J = 2·Leck direkt + Leck indirekt + Übermaskierung durch Stufe 3 + 0,5·übersehene local_only.

    Review 3.9: direkte Lecks zählen mit (doppelt), damit kein Prompt gewinnt, der Namen durchlässt.
    """
    s = m["stages"]
    last = s[list(s)[-1]]
    om = max(0.0, last["overmask"] - s.get("2", last)["overmask"])
    lo = m["local_only"]
    fn_rate = lo["fn"] / max(1, lo["fn"] + lo["tp"])
    return round(2 * last["direct_leak"] + last["indirect_leak"] + om + 0.5 * fn_rate, 4)


def collect_errors(rdir: Path, gt_dir: Path, limit: int = 12) -> list[str]:
    errs = []
    for p in sorted(rdir.glob("doc_*.json")):
        r = json.loads(p.read_text())
        gt = json.loads((gt_dir / p.name).read_text())
        directs = [d["text"] for d in gt["direct"]]
        for ind in gt["indirect"]:
            if evaluate.indirect_leak(ind["text"], r["stages"]["3"], directs):
                errs.append(f"ÜBERSEHEN ({ind['category']}): „{ind['text']}“")
        gt_words = " ".join(d["text"] for d in gt["indirect"]).lower()
        for f in r["hits"].get("3", []):
            if not isinstance(f, dict):
                continue
            span = str(f.get("span", ""))
            if f.get("status", "").startswith("angewandt") and span.lower()[:12] not in gt_words:
                errs.append(f"UNNÖTIG ersetzt: „{span}“ → „{f.get('replacement')}“")
            if f.get("status") == "verworfen":
                errs.append(f"SPAN NICHT WÖRTLICH: „{span}“")
        for m in re.finditer(r"\b(der|die|das|dem|den|des|ein|eine|einer)\s+(ein|eine|einer|der|die)\b",
                             r["stages"]["3"]):
            errs.append(f"GRAMMATIK: „…{r['stages']['3'][max(0, m.start() - 20):m.end() + 30]}…“")
    seen, out = set(), []
    for e in errs:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:limit]


def _next_version() -> str:
    nums = [int(p.stem[1:]) for p in project_path("prompts/stage3").glob("v*.md") if p.stem[1:].isdigit()]
    return f"v{max(nums) + 1}"


def run(cfg: dict[str, Any], base_run: Path, rounds: int = 3, only: list[str] | None = None,
        start_prompt: str | None = None, examples=None) -> str:
    gt_dir = project_path(cfg["paths"]["ground_truth"])
    log = project_path("out/optimize.jsonl")
    cur = start_prompt or cfg.get("stage3", {}).get("prompt", "v1")
    best = (None, cur)
    for i in range(rounds + 1):
        cfg.setdefault("stage3", {})["prompt"] = cur
        rdir = pipeline.run(cfg, stages=3, reuse=base_run, only=only, examples=examples,
                            run_id=datetime.now().strftime("%Y%m%d-%H%M%S") + f"_opt_{cur}"
                            + ("_fs" if examples else ""))  # Review 2.10: nie überschreiben
        m = evaluate.run(cfg, rdir)
        j = objective(m)
        errs = collect_errors(rdir, gt_dir)
        with log.open("a") as f:
            f.write(json.dumps({"prompt": cur, "J": j, "run": rdir.name,
                                "fewshot": bool(examples), "errors": errs}, ensure_ascii=False) + "\n")
        print(f"[bold]{cur}: J = {j}[/bold]")
        if best[0] is None or j < best[0]:
            best = (j, cur)
        if i == rounds:
            break
        prompt_text = project_path(f"prompts/stage3/{best[1]}.md").read_text()
        meta = META.format(metrics=json.dumps({"J": best[0], **m["stages"][list(m["stages"])[-1]],
                                                "local_only": m["local_only"]}, ensure_ascii=False),
                           errors="\n".join(f"- {e}" for e in errs) or "- keine", prompt=prompt_text)
        resp = llm.chat_json(cfg, "Du bist ein sorgfältiger Prompt-Ingenieur.", meta)
        new = str(resp.get("prompt", "")).strip()
        if len(new) < 200 or '"findings"' not in new:
            print("[yellow]Vorschlag unbrauchbar, Runde übersprungen")
            continue
        cur = _next_version()
        header = f"<!-- erzeugt von optimize aus {best[1]} (J={best[0]}); Änderungen: {resp.get('changes')} -->\n"
        project_path(f"prompts/stage3/{cur}.md").write_text(header + new + "\n", encoding="utf-8")
    print(f"[green]Bester Prompt: {best[1]} (J = {best[0]})")
    return best[1]
