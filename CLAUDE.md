# blackDocu – lokale Pseudonymisierung von Schülertexten

Vollständige Projektbeschreibung: `docs/PROJEKT.md` (Ziel, Architektur, Evaluation, Entscheidungs-DB).

## Harte Regeln
- **Keine echten Schülerdaten** in diesem Repo, solange Phase 1 läuft. Nur synthetische Daten unter `data/synthetic/`.
- **Zuordnungstabellen verlassen nie den Rechner** und kommen nie ins Git (`~/.noirdoc/namespaces/`, `data/namelist*.csv` mit echten Namen, `*.sqlite`).
- Erkenner (NER, LLM) **schlagen nur Textstellen vor**. Ersetzt wird ausschließlich deterministisch in Python, und nur wenn die Stelle exakt im Text vorkommt.
- Die Prüfstufe findet etwas → Dokument nach `out/blocked/`, nie weitergeben.
- Pseudonymisierte Texte gehen in Phase 1 **nicht** an externe Modelle. Alle LLM-Aufrufe laufen über lokales Ollama.

## Umgebung (Mac Studio)
- Python 3.13 über `uv` (`uv sync`, `uv run pytest`). noirdoc verlangt 3.12/3.13 und ist auf `0.2.*` gepinnt (Alpha, API ändert sich).
- Ollama ist schon vorhanden, **nicht** per brew installieren:
  - `studio`: `http://127.0.0.1:11434` (LaunchDaemon `com.robert.ollama`)
  - `desktop`: `http://100.109.37.47:11434` (RTX 4060 Ti, über Tailscale)
  - Auswahl in `config.yaml` (`llm.host`), Fallback auf den anderen Host, wenn einer nicht erreichbar ist.
- Modellgewichte liegen auf `/Volumes/Models` (`HF_HOME`, `FLAIR_CACHE_ROOT`). `config.yaml` → `models` setzt beide beim Start; `.envrc.example` für die Shell.

## Struktur
- `src/blackdocu/` – Paket: `config`, `llm`, `namelist`, `stage1_namelist` … `stage4_verify`, `pipeline`, `evaluate`, `decisions_db`, `generate_synthetic`
- `data/` – synthetische Texte, Lösungsdateien, fiktive `namelist.csv`
- `out/` – Ergebnisse (nicht im Git)
- `tests/` – pytest

## Vor echten Daten zu klären (aus dem Code-Review)
- `out/runs/*/doc_*.json` enthält den **Originaltext** (Stufe 0) für die Evaluation. Für echte Daten einen Betriebsmodus ohne Lauf-Protokolle bauen oder diese verschlüsselt ablegen und nach Frist löschen.
- Die Web-Oberfläche hat **keine Anmeldung** (nur 127.0.0.1). Vor echtem Einsatz: Anmeldung, Löschen der Entwürfe (`out/demo/drafts`), keine Screenshots echter Texte.
- Zuordnungstabellen: `noirdoc.namespace_root` für echte Daten auf `~/.noirdoc` (verschlüsseltes Volume, Backup-Konzept), nie im Projektordner.
- Nur `out/pseudonymized` darf jemals an externe Modelle; `out/local_only` und `out/blocked` nie.
- LLM-Hosts sind im Code auf Loopback/privat/Tailnet beschränkt (`llm.assert_local`).
