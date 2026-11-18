"""Kommandozeile: blackdocu <befehl>."""

from __future__ import annotations

import argparse

from rich import print

from . import evaluate, generate_synthetic, llm, pipeline
from .config import load_config


def main() -> None:
    p = argparse.ArgumentParser(prog="blackdocu")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Ollama-Hosts und Konfiguration prüfen")
    g = sub.add_parser("generate", help="synthetische Gutachten erzeugen")
    g.add_argument("-n", type=int, default=40)
    g.add_argument("--start", type=int, default=1, help="erste Dokumentnummer (für weitere Testdaten)")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--pool", choices=["dev", "holdout", "holdout2"], default="dev")
    r = sub.add_parser("run", help="Pipeline ausführen")
    r.add_argument("--stages", type=int, default=4, choices=[1, 2, 3, 4])
    r.add_argument("--prompt", help="Prompt-Version für Stufe 3, z. B. v2")
    r.add_argument("--only", nargs="*", help="nur diese Dokument-IDs")
    r.add_argument("--fewshot", action="store_true", help="Beispielbank (Ansatz 2) in Stufe 3 nutzen")
    r.add_argument("--tag", default="", help="Zusatz für den Laufnamen, z. B. holdout")
    e = sub.add_parser("evaluate", help="Leckrate messen (Default: letzter Lauf)")
    e.add_argument("run_dir", nargs="?")
    sub.add_parser("compare", help="alle Läufe vergleichen")
    o = sub.add_parser("optimize", help="Prompt für Stufe 3 automatisch verbessern")
    o.add_argument("base_run", help="Lauf, aus dem Stufe 1+2 übernommen werden")
    o.add_argument("--rounds", type=int, default=3)
    o.add_argument("--start", help="Start-Prompt, z. B. v1")
    o.add_argument("--fewshot", action="store_true", help="Beispielbank (Ansatz 2) zuschalten")
    o.add_argument("--only", nargs="*")
    w = sub.add_parser("web", help="lokale Demo-Oberfläche (127.0.0.1)")
    w.add_argument("--run", help="Laufverzeichnis, Default: letzter 4-Stufen-Lauf")
    w.add_argument("--port", type=int, default=8765)
    b = sub.add_parser("bank", help="Beispielbank aus Dev-Lauf aufbauen")
    b.add_argument("run_dir")
    args = p.parse_args()
    cfg = load_config()

    if args.cmd == "check":
        for name, url in cfg["llm"]["hosts"].items():
            ok = llm.host_reachable(url)
            print(f"{name:8} {url:32} {'[green]ok' if ok else '[red]nicht erreichbar'}")
        print("gewählt:", llm.pick_host(cfg), "Modell:", cfg["llm"]["model"])
    elif args.cmd == "generate":
        generate_synthetic.run(cfg, args.n, seed=args.seed, start=args.start, pool=args.pool)
    elif args.cmd == "run":
        if args.prompt:
            cfg.setdefault("stage3", {})["prompt"] = args.prompt
        ex = None
        if args.fewshot:
            from . import fewshot
            ex = fewshot.Retriever(cfg, cfg.get("fewshot", {}).get("k", 4))
        from datetime import datetime
        rid = (datetime.now().strftime("%Y%m%d-%H%M%S") + f"_s{args.stages}_{cfg['stage3']['prompt']}"
               + ("_fs" if ex else "") + (f"_{args.tag}" if args.tag else ""))
        rdir = pipeline.run(cfg, args.stages, run_id=rid, only=args.only, examples=ex)
        evaluate.run(cfg, rdir)
    elif args.cmd == "evaluate":
        from pathlib import Path
        evaluate.run(cfg, Path(args.run_dir) if args.run_dir else None)
    elif args.cmd == "compare":
        print(evaluate.compare())
    elif args.cmd == "optimize":
        from pathlib import Path

        from . import fewshot, optimize
        ex = fewshot.Retriever(cfg, cfg.get("fewshot", {}).get("k", 4)) if args.fewshot else None
        optimize.run(cfg, Path(args.run_dir if hasattr(args, "run_dir") else args.base_run),
                     rounds=args.rounds, only=args.only, start_prompt=args.start, examples=ex)
    elif args.cmd == "web":
        from pathlib import Path

        from . import web
        web.serve(Path(args.run) if args.run else None, args.port)
    elif args.cmd == "bank":
        from pathlib import Path

        from . import fewshot
        rd = Path(args.run_dir)
        ids = sorted(p.stem for p in rd.glob("doc_*.json"))
        print(f"{fewshot.build_bank(cfg, rd, ids)} Beispiele angelegt")


if __name__ == "__main__":
    main()
