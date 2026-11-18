# Projekt: Lokale Pseudonymisierung von Schülergutachten

> Projektbeschreibung für den Aufbau auf dem Mac Studio, auch als Vorlage für Claude Code nutzbar (z. B. als `CLAUDE.md` ins Projektverzeichnis legen).

## 1. Ziel

Texte aus dem Schulalltag (Schülergutachten, Zeugnisbemerkungen, Förderpläne, Elternbriefe) werden **vollständig lokal** pseudonymisiert. Danach dürfen KI-Agenten damit arbeiten, auch externe Modelle wie Claude als Manager. Zum Schluss werden die echten Namen **lokal** wieder eingesetzt.

Zusätzlich gilt:
- Jede Entscheidung der Agenten (z. B. Note, Formulierung, Einstufung) wird mit Begründung in einer **Entscheidungs-Datenbank** protokolliert, nach dem Vorbild des Prüfungsausschusses.
- Die Agenten arbeiten mit **rollenabhängigen Skills** (z. B. Gutachtenschreiber, Zweitprüfer, Formalien-Check), deren Version mitprotokolliert wird.

**Phase 1 (dieses Dokument):** Minimalprojekt mit synthetischen Testdaten, einer Pseudonymisierungs-Pipeline und einer Messung, wie viel durchrutscht.
Echte Schülerdaten erst nach Freigabe durch Schulleitung und Datenschutzbeauftragte.

---

## 2. Grundprinzipien

1. **Pseudonymisierung, nicht Anonymisierung.** Die Zuordnung bleibt lokal erhalten, damit die Namen am Ende wieder eingesetzt werden können. Rechtlich bleiben pseudonyme Daten personenbezogen.
2. **Die Zuordnungstabelle verlässt nie den Rechner.**
3. **Mehrstufige Erkennung.** Mehrere Erkennungsstufen laufen hintereinander, dahinter eine unabhängige Prüfstufe (Vier-Augen-Prinzip).
4. **Erkenner schlagen nur Textstellen vor.** Das Ersetzen übernimmt deterministischer Code (nach dem Vorbild von KatherLab/deidentifier).
5. **Sperren statt durchlassen.** Findet die Prüfstufe noch etwas, wird der Text gesperrt und nicht weitergegeben.
6. **Besonders schützenswerte Fälle bleiben lokal.** Texte mit Förderbedarf, Diagnosen oder Familiensituation werden nur lokal verarbeitet, auch nach der Pseudonymisierung.

---

## 3. Architektur

```
Rohtext (lokal)
   │
   ▼
[Stufe 1] Namensliste       → exakte Ersetzung (Schüler, Eltern, Lehrkräfte, Kurzformen, Genitiv)
   │
   ▼
[Stufe 2] noirdoc[full]     → Presidio + Flair + GLiNER (Namen, Orte, Daten, Einrichtungen …)
   │
   ▼
[Stufe 3] Lokales LLM       → indirekte Hinweise verallgemeinern (Umzug, Familie, Diagnosen …)
   │                          via Ollama, z. B. Qwen / Mistral / Gemma (Instruct)
   ▼
[Stufe 4] Prüfstufe         → erneuter Abgleich mit Namensliste + NER-Lauf auf dem Ergebnis
   │                          Treffer → SPERREN, sonst Freigabe
   ▼
Pseudonymisierter Text  ──► Agenten (lokal oder Claude)
   │
   ▼
Rückführung (lokal)         → noirdoc reveal / eigene Zuordnungstabelle
```

---

## 4. Setup auf dem Mac

```bash
# Python 3.12 oder 3.13 (noirdoc-Voraussetzung)
brew install python@3.12 ollama
python3.12 -m venv .venv && source .venv/bin/activate

pip install "noirdoc[full]"     # Presidio + GLiNER + Flair
noirdoc models pull             # ~560 MB Gewichte (spaCy de_core_news_lg, Flair, GLiNER)

pip install pandas rich pyyaml rapidfuzz ollama

ollama pull qwen2.5:14b         # Beispiel; aktuelles deutschfähiges Instruct-Modell wählen
```

Hinweis: noirdoc ist im Alpha-Stadium (0.1.x), deshalb die Version fest pinnen (`noirdoc==0.1.*`).

---

## 5. Projektstruktur

```
schul-pseudo/
├── CLAUDE.md                  # diese Datei
├── data/
│   ├── synthetic/             # erfundene Gutachten (*.txt)
│   ├── ground_truth/          # Lösungsdateien (*.json), eine pro Gutachten
│   └── namelist.csv           # fiktive Klassenliste (Schüler, Eltern, Lehrkräfte)
├── src/
│   ├── generate_synthetic.py  # erzeugt Testgutachten + Lösungsdateien (lokales LLM)
│   ├── stage1_namelist.py     # exakte Ersetzung über Namensliste
│   ├── stage2_noirdoc.py      # Wrapper um noirdoc Redactor
│   ├── stage3_llm.py          # Verallgemeinerung indirekter Hinweise über Ollama
│   ├── stage4_verify.py       # Prüfstufe, sperrt bei Treffern
│   ├── pipeline.py            # verkettet Stufe 1–4
│   ├── evaluate.py            # misst Leckrate gegen ground_truth
│   └── decisions_db.py        # Entscheidungs-Datenbank (SQLite)
├── out/
│   ├── pseudonymized/
│   ├── blocked/
│   └── report.md
└── tests/
```

---

## 6. Synthetische Testdaten

### 6.1 Umfang
- 30–50 erfundene Gutachten, jeweils 150–400 Wörter
- Mischung der Textsorten: Schülergutachten, Zeugnisbemerkung, Förderplan-Auszug, Elternbrief
- Fiktive Klassenliste mit ~25 Schülern, Eltern und 6 Lehrkräften in `namelist.csv`

### 6.2 Schwierigkeiten, die gezielt eingebaut werden
| Kategorie | Beispiel |
|---|---|
| Direkte Namen | „Lena Hoffmann“, „Frau Krüger (Klassenleitung)“ |
| Kurzformen / Spitznamen | „Lenchen“, „Maxi“, „der kleine Ben“ |
| Flexion | „Maximilians Heft“, „Lenas Mutter“ |
| Kleinschreibung / Tippfehler | „lena hat …“, „Hofmann“ statt „Hoffmann“ |
| Inverse Namen | „Hoffmann, Lena“ |
| Orte / Einrichtungen | Wohnort, Vorschule, Praxis „Dr. Weber“, Sportverein |
| Daten | Geburtsdatum, Einschulungsdatum |
| Geschwister / Familie | „wie schon ihr Bruder Tim in der 9a“ |
| Indirekte Hinweise | „seit dem Umzug aus Kiel“, „nach der Trennung der Eltern“, „einziges Kind mit Rollstuhl in der Jahrgangsstufe“ |
| Besonders schützenswert | Förderbedarf, Diagnosen (z. B. LRS, ADHS), Herkunft, Religion |

Alle Namen und Details sind frei erfunden. Keine echten Personen und keine echten Schulen.

### 6.3 Format der Lösungsdatei (`ground_truth/<id>.json`)
```json
{
  "id": "gutachten_007",
  "type": "schuelergutachten",
  "sensitive_level": "hoch",
  "direct": [
    {"text": "Lena Hoffmann", "category": "PERSON_SCHUELER"},
    {"text": "Lenas",         "category": "PERSON_SCHUELER"},
    {"text": "Frau Krüger",   "category": "PERSON_LEHRKRAFT"},
    {"text": "Tim",           "category": "PERSON_GESCHWISTER"},
    {"text": "12.03.2014",    "category": "DATUM_GEBURT"},
    {"text": "Kiel",          "category": "ORT"}
  ],
  "indirect": [
    {"text": "seit dem Umzug aus Kiel", "category": "BIOGRAFIE", "expected": "generalize"},
    {"text": "LRS-Diagnose",            "category": "GESUNDHEIT", "expected": "local_only"}
  ]
}
```

`generate_synthetic.py` erzeugt Text und Lösungsdatei gemeinsam mit dem lokalen LLM und prüft danach automatisch, dass jeder `text`-Eintrag wirklich im Gutachten vorkommt.

---

## 7. Pipeline-Details

### Stufe 1: Namensliste
- `namelist.csv`: `vorname, nachname, rolle, kurzformen` (Kurzformen durch `|` getrennt)
- Varianten automatisch erzeugen: Genitiv-s, „Nachname, Vorname“, nur Vorname, nur Nachname
- Unscharfer Abgleich mit `rapidfuzz` (Schwelle ~90) für Tippfehler
- Ersetzung durch stabile Platzhalter `<<SCHUELER_07>>`, `<<LEHRKRAFT_02>>`

### Stufe 2: noirdoc
```python
from noirdoc import Redactor
r = Redactor(namespace="klasse_7b")
clean = r.redact_text(text)        # API laut aktueller noirdoc-Doku prüfen
```
- Ein Namespace pro Klasse oder Schuljahr: Gleiche Personen bekommen über alle Dokumente denselben Platzhalter.
- Mapping liegt unter `~/.noirdoc/namespaces/`. Dieses Verzeichnis gehört in Backup und Verschlüsselung (FileVault).

### Stufe 3: Lokales LLM (Ollama)
Prompt-Vorgabe (sinngemäß):
> Du erhältst einen bereits teilweise pseudonymisierten Text. Platzhalter wie <<…>> nicht verändern.
> Finde Textstellen, die eine Person indirekt identifizierbar machen (Herkunftsort, Umzug, Familienereignisse, seltene Merkmale, Diagnosen, Herkunft, Religion).
> Gib NUR eine JSON-Liste zurück: [{"span": "...", "replacement": "...", "reason": "..."}]

- Das LLM schlägt nur vor. Das Ersetzen übernimmt Python, und nur dann, wenn `span` exakt im Text vorkommt.
- Gesundheit oder Förderbedarf erkannt → Dokument als `local_only` markieren.

### Stufe 4: Prüfstufe
- Ergebnistext erneut gegen die komplette Namensliste prüfen (exakt und unscharf)
- noirdoc / GLiNER erneut auf dem Ergebnis laufen lassen
- Treffer außerhalb von Platzhaltern → Datei nach `out/blocked/` mit Begründung

---

## 8. Evaluation (`evaluate.py`)

Für jedes Gutachten:
- **Leckrate direkt:** Anteil der `direct`-Einträge, die im Ergebnis noch vorkommen (Ziel: 0 %)
- **Leckrate indirekt:** Anteil der `indirect`-Einträge, die unverändert geblieben sind
- **Übermaskierung:** Anteil des Textes, der unnötig ersetzt wurde (Lesbarkeit des Gutachtens)
- **Sperrquote:** Wie viele Dokumente hat Stufe 4 gesperrt?
- Auswertung **pro Stufe kumulativ** (nur 1, 1+2, 1+2+3, alle), um den Beitrag jeder Stufe zu sehen

Ausgabe: `out/report.md` mit Tabelle je Kategorie und Liste aller Lecks mit Fundstelle.

---

## 9. Entscheidungs-Datenbank (`decisions_db.py`, SQLite)

```sql
CREATE TABLE decisions (
  id             INTEGER PRIMARY KEY,
  created_at     TEXT NOT NULL,
  case_id        TEXT NOT NULL,      -- Pseudonym, z. B. <<SCHUELER_07>>
  document       TEXT,               -- Dokument / Abschnitt
  decision       TEXT NOT NULL,      -- was entschieden wurde (z. B. "Note 2")
  rationale      TEXT NOT NULL,      -- warum
  criterion_ref  TEXT,               -- Verweis auf Bewertungsmaßstab / Kriterium
  actor          TEXT NOT NULL,      -- "agent" | "mensch"
  role           TEXT,               -- z. B. gutachter, zweitpruefer
  model          TEXT,               -- Modell + Version
  skill_version  TEXT,               -- Version des Rollen-Skills
  status         TEXT NOT NULL,      -- vorgeschlagen | bestaetigt | ueberstimmt
  override_reason TEXT               -- Begründung bei Überstimmung
);
```

- In der Datenbank stehen **nur Pseudonyme**, nie Klarnamen.
- Überstimmte Fälle werden regelmäßig ausgewertet, um die Rollen-Skills nachzuschärfen.
- Später optional: Vektorsuche über `rationale`, um ähnliche Fälle zu finden (Gleichbehandlung).

---

## 10. Rollen-Skills (Ausblick Phase 2)

```
skills/
├── gutachter/        SKILL.md  (v1.0)
├── zweitpruefer/     SKILL.md  (v1.0)
└── formalien/        SKILL.md  (v1.0)
```
- Ein Orchestrator wählt die Skills nach Rolle und Aufgabentyp aus.
- Jede Skill-Änderung bekommt eine neue Version und einen Eintrag im Änderungsprotokoll.
- `skill_version` wird bei jeder Entscheidung gespeichert.

---

## 11. Aufgabenliste Phase 1

- [ ] Setup (Python 3.12, noirdoc[full], Ollama, Modell)
- [ ] `namelist.csv` mit fiktiver Klasse anlegen
- [ ] `generate_synthetic.py`: 40 Gutachten + Lösungsdateien erzeugen und auf Konsistenz prüfen
- [ ] Stufe 1–4 implementieren, `pipeline.py` verketten
- [ ] `evaluate.py` + `out/report.md`
- [ ] Schwachstellen analysieren, Erkenner nachschärfen, erneut messen
- [ ] `decisions_db.py` mit Beispiel-Einträgen
- [ ] Ergebnis-Report als Grundlage für das Gespräch mit Schulleitung und Datenschutzbeauftragten

---

## 12. Offene Punkte (Datenschutz / Organisation)

- Abstimmung mit Schulleitung und Datenschutzbeauftragten der Schule
- Eintrag ins Verzeichnis der Verarbeitungstätigkeiten, ggf. Datenschutz-Folgenabschätzung
- Rahmen durch das Schulgesetz des Landes prüfen
- Klären, ob pseudonymisierte Texte an externe Modelle gehen dürfen (Auftragsverarbeitungsvertrag?) oder alles lokal bleibt
- Speicherort und Verschlüsselung der Zuordnungstabellen, Lösch- und Aufbewahrungsfristen

---

## Referenzen

- noirdoc: https://github.com/nextaim-de/noirdoc
- KatherLab deidentifier (Architektur-Vorbild, Prüfstufe): https://github.com/KatherLab/deidentifier
- PrivaParse (lokales Gateway mit Rückführung): https://pypi.org/project/privaparse/
- Presidio + GLiNER: https://microsoft.github.io/presidio/samples/python/gliner
- Synthetische PII-Daten (allgemein, mehrsprachig): ai4privacy
- GraSCCo / MultiGraSCCo (deutscher synthetischer Freitext): https://arxiv.org/pdf/2603.08879
