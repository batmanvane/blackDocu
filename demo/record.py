"""Nimmt den Demo-Ablauf mit Playwright als Video auf (Chromium, lokal).

Aufruf:  uv run python demo/record.py [--run out/runs/<id>] [--doc doc_007]
Ergebnis: out/demo/video/*.webm + Screenshots out/demo/shots/
Voraussetzung: einmalig `uv run playwright install chromium`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "demo"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(BASE, timeout=2)
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("Demo-Server startet nicht")


def pick_docs(run: Path) -> tuple[str, str | None]:
    """Ein freigegebener, möglichst anschaulicher Text + (falls vorhanden) ein gesperrter."""
    ok, blocked = [], None
    for p in sorted(run.glob("doc_*.json")):
        r = json.loads(p.read_text())
        if r.get("blocked"):
            blocked = blocked or r["id"]
        else:
            n = len([f for f in r["hits"].get("3", []) if isinstance(f, dict)
                     and str(f.get("status", "")).startswith("angewandt")])
            ok.append((n, -len(r["stages"]["0"]), r["id"]))
    return max(ok)[2], blocked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--doc")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--video", action="store_true", help="zusätzlich Video aufnehmen (Default: nur Screenshots)")
    a = ap.parse_args()
    runs = sorted(p for p in (ROOT / "out" / "runs").iterdir() if "_s4_" in p.name)
    run = Path(a.run) if a.run else runs[-1]
    doc, blocked = pick_docs(run)
    doc = a.doc or doc
    (OUT / "shots").mkdir(parents=True, exist_ok=True)

    srv = subprocess.Popen([sys.executable, "-m", "blackdocu.cli", "web", "--run", str(run),
                            "--port", str(PORT)], cwd=ROOT)
    try:
        wait_for_server()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not a.headed)
            vid = {"record_video_dir": str(OUT / "video"),
                   "record_video_size": {"width": 1440, "height": 900}} if a.video else {}
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, **vid)
            page = ctx.new_page()

            def shot(name: str, pause: float = 2.5) -> None:
                page.wait_for_timeout(int(pause * 1000))
                page.screenshot(path=str(OUT / "shots" / f"{name}.png"), full_page=True)

            page.goto(BASE)                                   # 1. Ordnerübersicht
            shot("01_ordner")
            page.goto(f"{BASE}/doc/{doc}?stage=1")            # 2. Stufen nacheinander
            shot("02_stufe1")
            page.click("#tab-2")
            shot("03_stufe2")
            page.click("#tab-3")
            page.locator("#pseudo").scroll_into_view_if_needed()
            shot("04_stufe3", 3.5)
            page.click("#draft-btn", timeout=300_000)         # 3. KI-Entwurf (gecacht)
            page.wait_for_selector("#draft", timeout=180_000)
            shot("05_entwurf", 3.5)
            page.click("#reveal-btn")                         # 4. Rückwandlung
            page.wait_for_selector("#final")
            shot("06_fertig", 4)
            if blocked:                                       # 5. Gesperrter Text
                page.goto(f"{BASE}/doc/{blocked}")
                shot("07_gesperrt", 3)
            page.goto(f"{BASE}/messung")                      # 6. Messwerte
            shot("08_messung", 4)
            page.goto(BASE)
            shot("09_ordner_danach", 2)
            ctx.close()
            browser.close()
        vids = sorted((OUT / "video").glob("*.webm"), key=lambda p: p.stat().st_mtime) if a.video else []
        if vids:  # MP4 für QuickTime/Keynote/PowerPoint
            mp4 = OUT / "blackdocu_demo.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vids[-1]),
                            "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-profile:v", "main",
                            "-level", "4.0", "-crf", "20", "-tag:v", "avc1", "-movflags", "+faststart",
                            "-an", str(mp4)],
                           check=False)
            print(f"Video: {mp4}")
        print(f"Screenshots: {OUT / 'shots'}")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
