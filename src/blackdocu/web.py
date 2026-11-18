"""Lokale Demo-Oberfläche (nur 127.0.0.1) über einem Pipeline-Lauf.

Zeigt den Ordner-Workflow: Eingang → Bereit / Gesperrt → KI-Entwurf → Rückwandlung → Fertig.
Für die Präsentation mit Playwright (demo/record.py). Nur synthetische Daten.

Start: uv run blackdocu web [--run out/runs/<id>]
"""

from __future__ import annotations

import difflib
import html
import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import evaluate, llm
from .config import load_config, project_path
from .namelist import load_namelist
from .stage1_namelist import reveal as reveal_stage1

TOKEN = re.compile(r"<<[A-Z_]+_\d+>>|\w+|\W", re.UNICODE)

DRAFT_PROMPT = """Du bist Lehrkraft. Schreibe auf Basis des folgenden Textes eine Zeugnisbemerkung
(4–6 Sätze, sachlich, wertschätzend, ohne Diagnosen oder Familiendetails).
Platzhalter wie <<SCHUELER_01>> unverändert übernehmen, keine Namen erfinden.
Antworte nur mit JSON: {"text": "..."}"""

CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1f1f1f;--muted:#6b6b6b;--line:#e3e1dc;--acc:#2f5d8a;
--ok:#2e7d4f;--warn:#b26a00;--bad:#b3261e;--del:#fde7e5;--ins:#e3f0fb}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#1f2a36;color:#fff;padding:14px 28px;display:flex;gap:24px;align-items:center}
header b{font-size:17px}header a{color:#cfd8e3;text-decoration:none}header a:hover{color:#fff}
main{padding:24px 28px;max-width:1280px;margin:auto}
.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.col{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.col h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 10px}
.item{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:8px;
color:var(--ink);text-decoration:none;background:#fcfcfb}.item:hover{border-color:var(--acc)}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;margin-left:6px;border:1px solid}
.b-local{color:var(--warn);border-color:var(--warn)}.b-block{color:var(--bad);border-color:var(--bad)}
.b-ok{color:var(--ok);border-color:var(--ok)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.pane{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;white-space:pre-wrap}
.pane h3{margin:0 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;white-space:normal}
del{background:var(--del);text-decoration:none;border-radius:3px}
ins{background:var(--ins);text-decoration:none;border-radius:3px}
.ph{background:#e8e4f7;color:#3d2c8d;border-radius:4px;padding:0 3px;font-family:ui-monospace,monospace;font-size:13px}
.btn{display:inline-block;background:var(--acc);color:#fff;border:0;border-radius:8px;padding:9px 16px;
font-size:14px;text-decoration:none;cursor:pointer;margin:14px 8px 14px 0}
.btn.sec{background:#fff;color:var(--acc);border:1px solid var(--acc)}
table{border-collapse:collapse;background:var(--card);width:100%}td,th{border:1px solid var(--line);padding:7px 10px;text-align:left}
th{background:#f1efea}.note{color:var(--muted);font-size:13px}
ul.find{padding-left:18px}ul.find li{margin:3px 0}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header><b>blackDocu</b><a href="/">Ordner</a><a href="/messung">Messung</a>
<span class="note" style="color:#9fb0c2;margin-left:auto">lokal · nur synthetische Daten</span></header>
<main>{body}</main></body></html>""")


PH_ESC = re.compile(r"&lt;&lt;([A-Z_]+_\d+)&gt;&gt;")


def _ph(escaped: str) -> str:
    """Hebt Platzhalter in bereits HTML-escaptem Text hervor."""
    return PH_ESC.sub(lambda m: f'<span class="ph">&lt;&lt;{m.group(1)}&gt;&gt;</span>', escaped)


def diff_html(a: str, b: str) -> tuple[str, str]:
    """Wort-Diff: links Entferntes rot, rechts Eingesetztes blau, Platzhalter hervorgehoben."""
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    left, right = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ta, b=tb, autojunk=False).get_opcodes():
        sa, sb = html.escape("".join(ta[i1:i2])), html.escape("".join(tb[j1:j2]))
        if op == "equal":
            left.append(sa)
            right.append(sb)
        else:
            if sa:
                left.append(f"<del>{sa}</del>")
            if sb:
                right.append(f"<ins>{sb}</ins>")
    return "".join(left), _ph("".join(right))


def create_app(run_dir: Path | None = None) -> FastAPI:
    cfg = load_config()
    runs = sorted(p for p in project_path("out/runs").iterdir() if "_s4_" in p.name)
    rdir = run_dir or runs[-1]
    people = load_namelist(project_path(cfg["namelist"]["path"]))
    drafts = project_path("out/demo/drafts") / rdir.name
    drafts.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    stage2 = {"obj": None}

    def rec(doc: str) -> dict[str, Any]:
        p = rdir / f"{doc}.json"
        if not p.exists():
            raise HTTPException(404)
        return json.loads(p.read_text())

    def reveal(text: str) -> str:
        if stage2["obj"] is None:  # lädt nur den Namespace, keine Modelle
            from .stage2_noirdoc import Stage2
            stage2["obj"] = Stage2(cfg)
        return reveal_stage1(stage2["obj"].reveal(text), people)

    def final(r: dict) -> str:
        return r["stages"][max(k for k in r["stages"] if k != "0")]

    @app.get("/", response_class=HTMLResponse)
    def index():
        docs = [json.loads(p.read_text()) for p in sorted(rdir.glob("doc_*.json"))]
        cols = {"Eingang": [], "Bereit": [], "Gesperrt": [], "Fertig": []}
        for r in docs:
            label = r["id"].replace("doc_", "Text ")
            cols["Eingang"].append(f'<a class="item" href="/doc/{r["id"]}?stage=1">{label}</a>')
            if r.get("blocked"):
                cols["Gesperrt"].append(f'<a class="item" id="blk-{r["id"]}" href="/doc/{r["id"]}">{label}'
                                        f'<span class="badge b-block">gesperrt</span></a>')
            else:
                b = '<span class="badge b-local">nur lokal</span>' if r.get("local_only") else ""
                cols["Bereit"].append(f'<a class="item" id="rdy-{r["id"]}" href="/doc/{r["id"]}">{label}{b}</a>')
            if (drafts / f"{r['id']}.txt").exists():
                cols["Fertig"].append(f'<a class="item" href="/doc/{r["id"]}/fertig">{label}'
                                      f'<span class="badge b-ok">zurückgewandelt</span></a>')
        body = (f'<p class="note">Lauf {html.escape(rdir.name)} · {len(docs)} Texte</p><div class="cols">'
                + "".join(f'<div class="col"><h2>{k} ({len(v)})</h2>{"".join(v[:14])}'
                          + (f'<p class="note">… {len(v) - 14} weitere</p>' if len(v) > 14 else "")
                          + "</div>" for k, v in cols.items()) + "</div>")
        return _page("Ordner", body)

    @app.get("/doc/{doc}", response_class=HTMLResponse)
    def doc(doc: str, stage: str | None = None):
        r = rec(doc)
        st = stage or max(k for k in r["stages"] if k != "0")
        left, right = diff_html(r["stages"]["0"], r["stages"][st])
        names = {"1": "Stufe 1: Namensliste", "2": "Stufe 1+2: + Erkennungsmodelle", "3": "Stufe 1–3: + lokales LLM"}
        tabs = "".join(f'<a class="btn sec" id="tab-{k}" href="/doc/{doc}?stage={k}">{names[k]}</a>'
                       for k in r["stages"] if k != "0")
        status = ""
        if r.get("blocked"):
            items = "".join(f"<li>„{html.escape(b['text'])}“ ({b['check']})</li>" for b in r["blocked"])
            status = (f'<div class="pane" style="border-color:var(--bad)"><h3>Gesperrt durch die Prüfstufe</h3>'
                      f'<ul class="find">{items}</ul><span class="note">Text wird nicht weitergegeben, '
                      f'bis eine Lehrkraft ihn geprüft hat.</span></div><br>')
        elif r.get("local_only"):
            status = ('<p><span class="badge b-local">nur lokal</span> <span class="note">enthält sensible '
                      'Angaben (Gesundheit, Familie, Herkunft) – Bearbeitung nur mit dem lokalen Modell.</span></p>')
        f3 = [f for f in r["hits"].get("3", []) if isinstance(f, dict) and str(f.get("status", "")).startswith("angewandt")]
        llm_list = "".join(f"<li>„{html.escape(str(f['span']))}“ → „{html.escape(str(f['replacement']))}“ "
                           f"<span class='note'>({html.escape(str(f.get('category', '')))})</span></li>" for f in f3)
        action = "" if r.get("blocked") else (
            f'<form method="post" action="/doc/{doc}/entwurf" style="display:inline">'
            f'<button class="btn" id="draft-btn">KI-Entwurf: Zeugnisbemerkung</button></form>')
        body = (f'<h1 style="font-size:22px">{doc.replace("doc_", "Text ")}</h1>{status}<div>{tabs}</div>'
                f'<div class="pair"><div class="pane"><h3>Original (bleibt auf dem Schulrechner)</h3>{left}</div>'
                f'<div class="pane" id="pseudo"><h3>Pseudonymisiert (darf weiter)</h3>{right}</div></div>'
                + (f'<h3>Vom lokalen LLM verallgemeinert</h3><ul class="find">{llm_list}</ul>' if llm_list else "")
                + action)
        return _page(doc, body)

    @app.post("/doc/{doc}/entwurf")
    def entwurf(doc: str):
        r = rec(doc)
        if r.get("blocked"):
            raise HTTPException(403, "gesperrt")
        p = drafts / f"{doc}.txt"
        if not p.exists():  # Cache: Aufnahme soll nicht auf das Modell warten
            resp = llm.chat_json(cfg, DRAFT_PROMPT, final(r))
            p.write_text(str(resp.get("text", "")).strip(), encoding="utf-8")
        return RedirectResponse(f"/doc/{doc}/entwurf", status_code=303)

    @app.get("/doc/{doc}/entwurf", response_class=HTMLResponse)
    def entwurf_view(doc: str):
        p = drafts / f"{doc}.txt"
        if not p.exists():
            return RedirectResponse(f"/doc/{doc}")
        body = (f'<h1 style="font-size:22px">KI-Entwurf zu {doc.replace("doc_", "Text ")}</h1>'
                f'<p class="note">Das Modell hat nur Platzhalter gesehen. Echte Namen kennt es nicht.</p>'
                f'<div class="pane" id="draft">{_ph(html.escape(p.read_text()))}</div>'
                f'<a class="btn" id="reveal-btn" href="/doc/{doc}/fertig">Lokal zurückwandeln</a>')
        return _page("Entwurf", body)

    @app.get("/doc/{doc}/fertig", response_class=HTMLResponse)
    def fertig(doc: str):
        p = drafts / f"{doc}.txt"
        if not p.exists():
            return RedirectResponse(f"/doc/{doc}")
        draft = p.read_text()
        left, right = diff_html(draft, reveal(draft))
        right = right.replace('<span class="ph">', "").replace("</span>", "")
        body = (f'<h1 style="font-size:22px">Zurückgewandelt: {doc.replace("doc_", "Text ")}</h1>'
                f'<p class="note">Die Zuordnungstabelle hat den Rechner nie verlassen. '
                f'Die Lehrkraft prüft und unterschreibt.</p>'
                f'<div class="pair"><div class="pane"><h3>Entwurf mit Platzhaltern</h3>{_ph(left)}</div>'
                f'<div class="pane" id="final"><h3>Mit echten Namen (nur lokal)</h3>{right}</div></div>')
        return _page("Fertig", body)

    @app.get("/messung", response_class=HTMLResponse)
    def messung():
        mp = rdir / "metrics.json"
        if not mp.exists():
            return _page("Messung", "<p>Noch keine Messung für diesen Lauf.</p>")
        m = json.loads(mp.read_text())
        names = {"1": "Namensliste", "2": "+ Erkennungsmodelle", "3": "+ lokales LLM"}
        rows = "".join(f"<tr><td>{names.get(k, k)}</td><td>{s['direct_leak']:.1%}</td>"
                       f"<td>{s['indirect_leak']:.1%}</td><td>{s['overmask']:.1%}</td></tr>"
                       for k, s in m["stages"].items())
        lo = m["local_only"]
        body = (f'<h1 style="font-size:22px">Wie viel rutscht durch?</h1>'
                f'<p class="note">{m["docs"]} erfundene Texte · Lauf {html.escape(m["run"])}</p>'
                f'<table id="metrics"><tr><th>Stufen (kumulativ)</th><th>Leck Namen/Daten</th>'
                f'<th>Leck indirekte Hinweise</th><th>unnötig ersetzt</th></tr>{rows}</table>'
                f'<p>Gesperrt durch Prüfstufe: <b>{m["blocked"]}</b> von {m["docs"]} · '
                f'sensible Texte erkannt: <b>{lo["tp"]}</b>, übersehen: <b>{lo["fn"]}</b></p>'
                f'<h3>Alle Läufe</h3><div class="note" style="white-space:pre;font-family:ui-monospace,monospace;'
                f'font-size:12px">{html.escape(evaluate.compare())}</div>')
        return _page("Messung", body)

    return app


def serve(run_dir: Path | None = None, port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(run_dir), host="127.0.0.1", port=port, log_level="warning")
