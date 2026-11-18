"""Verkettet Stufe 1–4 für alle Dateien in data/synthetic.

Jeder Lauf bekommt ein eigenes Verzeichnis out/runs/<run_id>/ mit:
- config.json  (Konfiguration + Prompt-Version: macht Tuning-Läufe vergleichbar)
- <doc>.json   (Text nach jeder Stufe, Treffer, Sperrgründe, Laufzeiten)
Freigabe-Gate (Review 1.2/1.5):
- gesperrt (Prüfstufe hat etwas gefunden oder Stufe 3 ist fehlgeschlagen) → out/blocked
- nur lokal (Gesundheit, Familie, Herkunft …)                         → out/local_only
- sonst                                                                → out/pseudonymized
Nur out/pseudonymized darf später an externe Modelle gehen.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import cycle
from pathlib import Path
from typing import Any

from rich import print

from . import llm
from .config import project_path
from .namelist import load_namelist
from .stage1_namelist import redact as stage1
from .stage3_llm import Stage3
from .stage4_verify import verify


def _stage3_all(cfg, docs: dict[str, str], examples=None) -> dict[str, tuple]:
    """Stufe 3 parallel auf allen erreichbaren Ollama-Hosts."""
    hosts = [h for h in cfg["llm"].get("stage3_hosts") or llm.available_hosts(cfg)
             if llm.host_reachable(cfg["llm"]["hosts"][h])]
    s3 = {h: Stage3(cfg, chat=lambda c, s, u, h=h: llm.chat_json(c, s, u, host=h), examples=examples)
          for h in hosts}
    with ThreadPoolExecutor(max_workers=len(hosts)) as ex:
        futs = {d: (h, ex.submit(s3[h].redact, t, d)) for (d, t), h in zip(docs.items(), cycle(hosts))}
        out = {}
        for d, (h, f) in futs.items():
            try:
                out[d] = f.result()
                out[d][3]["host"] = h
            except Exception as e:
                out[d] = (docs[d], [], True, {"error": str(e)})  # Fehler: wird unten gesperrt
        return out


def run(cfg: dict[str, Any], stages: int = 4, run_id: str | None = None,
        only: list[str] | None = None, examples=None, reuse: Path | None = None,
        verify_ner: bool = True) -> Path:
    """reuse: Stufe 1+2 aus einem früheren Lauf übernehmen (spart Zeit beim Tunen von Stufe 3)."""
    people = load_namelist(project_path(cfg["namelist"]["path"]))
    src = project_path(cfg["paths"]["synthetic"])
    files = sorted(src.glob("*.txt"))
    if only:
        only = [x for o in only for x in o.split()]  # auch "doc_1 doc_2" als ein Argument
        files = [f for f in files if f.stem in only]
    if not files:
        raise SystemExit(f"Keine Texte gefunden (only={only!r}) – Lauf abgebrochen.")
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + f"_s{stages}_{cfg.get('stage3', {}).get('prompt', 'v1')}"
    rdir = project_path("out/runs") / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    meta = {**cfg, "_run": {"reuse_base": reuse.name if reuse else None, "stages": stages,
                            "fewshot": examples is not None, "only": only}}  # Review 2.11
    (rdir / "config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str))

    recs: dict[str, dict] = {}
    if reuse is not None:
        for f in files:
            old = json.loads((reuse / f"{f.stem}.json").read_text())
            recs[f.stem] = {"id": f.stem, "stages": {k: old["stages"][k] for k in ("0", "1", "2")},
                            "hits": {k: old["hits"][k] for k in ("1", "2")},
                            "seconds": {k: old["seconds"][k] for k in ("1", "2")}, "local_only": False}
    for f in ([] if reuse is not None else files):
        raw = f.read_text(encoding="utf-8")
        t0 = time.time()
        t1, h1 = stage1(raw, people, cfg["namelist"].get("fuzzy_threshold", 90))
        recs[f.stem] = {"id": f.stem, "stages": {"0": raw, "1": t1}, "hits": {"1": h1},
                        "seconds": {"1": round(time.time() - t0, 2)}, "local_only": False}

    s2 = None
    if stages >= 2 and reuse is None:
        from .stage2_noirdoc import Stage2
        s2 = Stage2(cfg)
        for r in recs.values():
            t0 = time.time()
            t2, h2 = s2.redact(r["stages"]["1"])
            r["stages"]["2"], r["hits"]["2"] = t2, h2
            r["seconds"]["2"] = round(time.time() - t0, 2)
        print(f"Stufe 2 fertig ({len(recs)} Texte)")

    if stages >= 3:
        res = _stage3_all(cfg, {d: r["stages"]["2"] for d, r in recs.items()}, examples)
        for d, (t3, f3, lo, meta) in res.items():
            recs[d]["stages"]["3"], recs[d]["hits"]["3"] = t3, f3
            recs[d]["local_only"], recs[d]["seconds"]["3"] = lo, meta.get("seconds")
            recs[d]["stage3_meta"] = meta
        print("Stufe 3 fertig")

    last = str(min(stages, 3))
    for d, r in recs.items():
        final = r["stages"][last]
        if stages >= 4:
            t0 = time.time()
            if s2 is None and verify_ner:
                from .stage2_noirdoc import Stage2
                s2 = Stage2(cfg)
            r["blocked"] = verify(final, people, cfg, s2 if verify_ner else None)
            r["seconds"]["4"] = round(time.time() - t0, 2)
        else:
            r["blocked"] = []
        if r.get("stage3_meta", {}).get("error"):  # ohne Stufe 3 keine Freigabe
            r["blocked"].append({"text": "", "check": "stufe3_fehler", "detail": r["stage3_meta"]["error"][:200]})
        target = "blocked" if r["blocked"] else "local_only" if r.get("local_only") else "pseudonymized"
        r["target"] = target
        out_dir = project_path(cfg["paths"].get(target, f"out/{target}"))
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{d}.txt"
        p.write_text(final, encoding="utf-8")
        (rdir / f"{d}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
    n_block = sum(1 for r in recs.values() if r["blocked"])
    print(f"Lauf {run_id}: {len(recs)} Texte, {n_block} gesperrt → {rdir}")
    return rdir
