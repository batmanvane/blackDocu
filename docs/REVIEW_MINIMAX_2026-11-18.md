# Review der Codebasis

Geprüft wurden `CLAUDE.md`, `docs/PROJEKT.md`, `config.yaml` sowie alle Dateien unter `src/`, `tests/`, `prompts/` und `demo/`. Es wurden keine Dateien verändert.

**Prüfgrenze:** `data/namelist.csv`, `data/allowlist.txt`, synthetische Texte, Ground Truth und `out/` sind in dieser Arbeitskopie nicht vorhanden. Die folgenden Befunde stützen sich deshalb auf den Code, die Tests und die Konfiguration.

## 1. Datenschutz- und Sicherheitslücken

### 1.1 Gesperrte Dokumente werden dennoch als Freigabetext geschrieben
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/pipeline.py:105-112`

Die Prüfstufe markiert ein Dokument zwar mit `r["blocked"]`, der finale Text wird danach aber unabhängig davon in `out/pseudonymized/<id>.txt` **oder** `out/blocked/<id>.txt` geschrieben. Die Zielauswahl verhindert nicht, dass gesperrte Inhalte in einem Verzeichnis landen, das später als freigegebene Ausgabe verwendet wird.

Zusätzlich enthält jeder Lauf-Datensatz `stages["0"]` im Klartext (`pipeline.py:75`, `112`). Gesperrte Originaltexte, Stufe-1-Treffer und Stufe-3-Fundstellen landen unverschlüsselt in `out/runs/<run_id>/*.json`. Damit existieren mehrere Kopien trotz „gesperrt“.

**Konkreter Weg:** `out/runs/.../doc_x.json` → `stages["0"]` enthält den vollständigen Originaltext; `out/blocked/doc_x.txt` enthält denselben Text nach der Pipeline. Eine pauschale Weitergabe des gesamten `out/`-Verzeichnisses gibt Klarnamen weiter.

---

### 1.2 `local_only` ist nur ein Hinweis, aber kein Schutzmechanismus
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/pipeline.py:109-111`, `src/blackdocu/web.py:158-166`

Ein als `local_only` erkanntes Dokument wird in `out/pseudonymized/` geschrieben. Die Weboberfläche zeigt lediglich ein Badge und erlaubt anschließend den KI-Entwurf. Es gibt keine technische Sperre des Weitergabepfads.

**Beispiel:** Ein Text mit `sensitive=true` oder Kategorie `GESUNDHEIT` wird nicht blockiert und liegt in `out/pseudonymized/doc_007.txt`. Die Aussage in `docs/PROJEKT.md:25`, besonders schützenswerte Texte würden „nur lokal verarbeitet“, ist im Code nicht als Zugriffskontrolle umgesetzt.

---

### 1.3 Das LLM darf sensitive Fundstellen löschen, ohne dass `local_only` korrekt gesetzt wird
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/stage3_llm.py:54-65`

`local_only` wird nur gesetzt, wenn der LLM-Befund selbst `sensitive` trägt oder eine Kategorie aus `{"GESUNDHEIT", "HERKUNFT"}` hat. Das Python prüft nicht, ob die Kategorie inhaltlich sensibel ist. Zudem ignorieren die Prompts Widersprüche zwischen `category` und `sensitive`; beispielsweise verlangen `prompts/stage3/v5.md:25-26` die Kategorie `FAMILIE`, setzen aber nur bei „Familienkrisen“ `sensitive=true`.

**Beispiel:**  
```json
{
  "span": "nach der Inhaftierung des Vaters",
  "replacement": "nach einer familiären Veränderung",
  "category": "FAMILIE",
  "sensitive": false
}
```
Der Fund wird vollständig angewandt, `local_only` bleibt `false`. Die hochsensible Information ist generalisiert, aber der Schutzstatus ist falsch.

---

### 1.4 Falscher oder verworfener Span kann trotzdem ein Dokument schützen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage3_llm.py:54-59`

Ein Befund mit `sensitive=true` oder `GESUNDHEIT`/`HERKUNFT` setzt `local_only` auch dann, wenn der Span nicht im Text gefunden wurde. Dadurch können LLM-Halluzinationen sensible Dokumente markieren, aber nicht erkannte echte Gesundheitsdaten können gleichzeitig unmarkiert bleiben. Der Schutzstatus ist nicht an eine verifizierbare Textstelle gekoppelt.

**Beispiel:** Das LLM meldet `span="ADHS"` für einen Text, der stattdessen nur „ADHS-Diagnose“ enthält. Der exakte Match scheitert, die unscharfe Lokalisierung kann ebenfalls scheitern; das Dokument bleibt dennoch `local_only`. Umgekehrt ist ein nicht gemeldeter realer Span nicht geschützt.

---

### 1.5 `local_only` kann bei einem LLM-Fehler nur zufällig entstehen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/pipeline.py:39-44`

Bei einer Exception in Stufe 3 wird der unveränderte Stufe-2-Text übernommen und `local_only=True` gesetzt. Das wirkt konservativ, ist aber inkonsistent: Der unveränderte Text kann sensitive indirekte Hinweise enthalten, weil gerade Stufe 3 sie hätte erkennen sollen. Zugleich wird kein erneuter LLM-Versuch durchgeführt.

**Konkreter Fall:** Ollama bricht nach 600 Sekunden ab. Das Dokument behält z. B. „die festgestellte Lese-Rechtschreib-Schwäche“ und wird nur aufgrund des Fehlerfallbacks als `local_only` markiert.

---

### 1.6 Die Demo-Oberfläche zeigt Klarnamen ohne Zugriffsschutz
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/web.py:144-172`, `196-209`

`/doc/{doc}?view=original` ignoriert den Parameter `view` vollständig und zeigt immer Stufe 1 plus Originaltext im Diff. `/doc/{doc}/fertig` zeigt zurückgewandelte Klarnamen. Es gibt weder Authentifizierung noch eine Rollenprüfung.

Der Server bindet zwar nur an `127.0.0.1`, aber:
- jeder lokale Prozess oder Benutzer mit Zugriff auf den Port kann alle Dokumente abrufen;
- der zurückgewandelte Text kann über den Browsercache, Screenshots, Browserverlauf oder automatisierte Aufnahmen persistieren;
- `demo/record.py:75-98` erzeugt per Default Screenshots und optional Video, einschließlich der Ansicht „Fertig“ mit echten Namen.

**Konkreter Weg:** `GET http://127.0.0.1:8765/doc/doc_007/fertig` liefert den vollständigen Text mit Klarnamen; anschließend landet er in `out/demo/shots/06_fertig.png`.

---

### 1.7 Entwürfe werden dauerhaft im Klartext des pseudonymisierten Textes zwischengespeichert
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/web.py:174-183`

Entwürfe werden unter `out/demo/drafts/<run>/<doc>.txt` gespeichert. Sie enthalten zwar keine bewusst zurückgewandelten Namen, aber weiterhin sensible indirekte Hinweise, sofern Stufe 3 diese nicht entfernt hat. Sie werden außerdem nach dem ersten Aufruf blind wiederverwendet, selbst wenn zwischenzeitlich die Pipeline geändert wurde.

**Beispiel:** Ein alter Entwurf mit „ADHS-Diagnose“ bleibt nach einer neuen Stufe-3-Konfiguration unter `out/demo/drafts/...` erhalten und wird erneut ausgeliefert.

---

### 1.8 Stufe 2 schützt Platzhalter, aber Stage 3 darf an ihnen ansetzen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage2_noirdoc.py:110-116`, `src/blackdocu/stage3_llm.py:43-65`, `prompts/stage3/v5.md:15-17`

Stufe 2 verwirft Funde, die Platzhalter berühren. Stufe 3 erlaubt dagegen ausdrücklich Spans mit Platzhaltern und prüft nur, dass die **Ersetzung** keinen Platzhalter enthält. Dadurch kann ein geschützter Personentoken durch einen allgemeinen Span ersetzt werden.

**Beispiel:**
```text
nach dem Umzug aus <<LOCATION_1>>
```
mit
```json
{"span":"nach dem Umzug aus <<LOCATION_1>>","replacement":"nach einem Umzug"}
```
wird zu `nach einem Umzug`. Damit verschwindet nicht nur der Ort, sondern auch dessen stabiler Pseudonymbezug. Bei Stufe 4 kann dieser Token dann nicht mehr rückgeführt werden.

---

### 1.9 Stufe 3 kann durch unscharfe Ersetzung beliebige, zusammengehörende Zeichen löschen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage3_llm.py:29-40`

`partial_ratio_alignment` darf einen nur ungefähr ähnlichen Span auswählen. Es gibt keine Prüfung, dass dieser Span tatsächlich die behauptete semantische Stelle bezeichnet. Anschließend ersetzt `text.replace` **alle** identischen Vorkommen.

**Beispiel:** Das LLM meldet `span="Mutter erkrankt"`; der Text enthält an anderer Stelle denselben Wortlaut über eine andere Person. Beide Vorkommen werden ersetzt. Noch problematischer ist, dass ein knapper, nur `fuzz`-ähnlicher Span wie „ADHS“ auf ein längeres Wort aligniert und dessen Orthografie verändert.

---

### 1.10 Die Prüfstufe ignoriert sensible Kategorien außer `PERSON`
**Schweregrad: mittel**  
**Fundstelle:** `config.yaml:30-34`, `src/blackdocu/stage4_verify.py:30-37`

Stufe 4 blockiert NER-Treffer nur für `PERSON`. Orte, Einrichtungen, Datumsangaben außerhalb des strikten Datumsformats und andere sensible Entitäten können das Dokument passieren. Das widerspricht der Sicherheitsstrategie „Sperren statt durchlassen“.

**Beispiel:** Ein nicht als `PERSON` klassifiziertes „Praxis Dr. Weber“, eine Telefonnummer, eine E-Mail-Adresse oder eine Klassenbezeichnung `9a` kann unverändert freigegeben werden.

---

### 1.11 Die Prüfstufe kann durch Weglassen des Platzhalters die Offsetprüfung umgehen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage4_verify.py:18-29`

Die Prüfstufe maskiert Platzhalter durch Leerzeichen. Die NER-Prüfung läuft anschließend jedoch gegen den **ursprünglichen** Text. Je nach noirdoc-Implementierung kann ein Fund, der einen Platzhalter berührt, dort erkannt und als Blockierungsgrund verarbeitet werden. Umgekehrt kann ein wegen Überlappung verworfener Fund entstehen, während der entsprechende Name oder Ort außerhalb der NER-Erkennung bleibt.

Die Logik ist zwischen Namensliste/Datum und NER inkonsistent: einmal wird maskiert, einmal nicht.

---

### 1.12 Die Zuordnungstabelle wird im Projektverzeichnis gespeichert
**Schweregrad: mittel für echte Daten**  
**Fundstelle:** `config.yaml:13-15`, `src/blackdocu/stage2_noirdoc.py:101-103`

`namespace_root: out/noirdoc_ns` bedeutet, dass der noirdoc-Namespace im Projektverzeichnis liegt. `.gitignore` verhindert zwar den Git-Commit, aber nicht:
- Backup des Projektordners,
- Cloud-Synchronisation des übergeordneten Verzeichnisses,
- Weitergabe des Projektordners,
- Zugriff durch andere lokale Benutzer.

`CLAUDE.md:7` verlangt für echte Daten `~/.noirdoc/namespaces/`. Die zentrale Konfiguration enthält diese Sicherheitsgrenze nicht.

---

### 1.13 `decisions_db` prüft nur `case_id`, nicht die übrigen Freitextfelder
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/decisions_db.py:39-52`

Die Datenbank kann Klarnamen in `document`, `decision`, `rationale`, `criterion_ref`, `role`, `override_reason` oder sogar als zusätzlicher Spaltenname speichern. Die Behauptung „Enthält nur Pseudonyme, nie Klarnamen“ (`decisions_db.py:1`) ist damit nicht garantiert.

**Beispiel:**
```python
add_decision(
    con,
    case_id="<<SCHUELER_07>>",
    decision="Note 2 für Lena Hoffmann",
    rationale="Lena zeigte deutliche Fortschritte",
    actor="mensch",
)
```
wird ohne Beanstandung gespeichert.

---

### 1.14 Die Beispielbank kann Klarnamen speichern und an ein Embedding-Modell schicken
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/fewshot.py:68-100`

Die Beispielbank übernennt Stufe-2-Texte. Bei fehlerhafter Stufe 1 oder wenn Stufe 2 Namen nicht erkennt, können diese unverändert gespeichert werden. Anschließend wird der gesamte Text an das Embedding-Modell geschickt. Das betrifft auch den lokalen Ollama-Host, aber bei späterem Wechsel auf einen externen Host wäre die Übertragung nicht ausgeschlossen.

Zusätzlich enthält die Tabelle `doc_id`, `text` und Findings und ist nicht nach `source='mensch'` oder anderweitigen Kriterien gegen Klarnamen geprüft.

---

### 1.15 Prompt-Optimierung kann reale Texte und Befunde an das Modell senden
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/optimize.py:58-78`, `92-124`

Die Fehlerliste enthält wörtliche Textstellen und Fundstellen aus den verarbeiteten Dokumenten. Bei Umstellung auf echte Daten werden diese an das konfigurierte Ollama-Modell gesendet. Der Code setzt keine synthetische-Daten-Sperre voraus, obwohl die Modulbeschreibung ausdrücklich „Nur synthetische Daten“ behauptet.

Zusätzlich werden generierte Prompts unter `prompts/stage3/` gespeichert. `optimize.py:123-124` schreibt in ein versioniertes Quellverzeichnis; Fehlerlisten werden dabei nicht unbedingt persistiert, aber `out/optimize.jsonl` enthält die Fehlertexte im Klartext.

---

### 1.16 Der Tailscale-Host ist nicht als Gerätgrenze ausreichend abgesichert
**Schweregrad: niedrig bis mittel**  
**Fundstelle:** `config.yaml:9-11`, `src/blackdocu/llm.py:51-66`

`http://100.109.37.47:11434` ist unverschlüsselt und nicht authentifiziert. Der Code prüft nicht, ob der Ollama-Dienst auf einem fremden Tailnet-Gerät läuft. Jedes erreichbare Gerät im Tailnet könnte den Text abfangen oder einen Ollama-Dienst unter dieser Adresse betreiben.

Es gibt auch keine Prüfung, dass die antwortende Ollama-Instanz das erwartete Modell oder die erwartete Laufzeitumgebung ist.

---

### 1.17 Keine Schutzmaßnahme gegen Manipulation der Laufkonfiguration
**Schweregrad: niedrig bis mittel**  
**Fundstelle:** `src/blackdocu/pipeline.py:47-62`

Die Laufkonfiguration wird unkritisch aus `config.yaml` übernommen. Ein geänderter `llm.host`, `stage3_hosts` oder `noirdoc.namespace_root` kann die Daten an andere Ziele schicken oder die Zuordnung in einem anderen Verzeichnis speichern. Die Pipeline verifiziert weder, dass Hosts im erlaubten Set liegen, noch dass `stage3_hosts` leer ist beziehungsweise auf `studio`/`desktop` beschränkt bleibt.

---

## 2. Korrektheitsfehler

### 2.1 Stage 1 erzeugt aus einem Jungen ein geschlechtsneutrales „Kind“
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/namelist.py:16-21`, `src/blackdocu/stage1_namelist.py:58-63`

`prefix_for` verwendet für die Rolle `schueler` bei jedem unbekannten Geschlecht den Präfix `SCHUELERKIND`. Für die Rückführung wird `reverse` aber mit dem bloßen Vornamen befüllt. Das ergibt:

```text
<<SCHUELERKIND_01>> kam.
```
→ `Maxi kam.`

Der Platzhalter behauptet „Kind“, obwohl der Datensatz eine Person mit Vornamen ist. Geschlechtsneutralität ist hier semantisch irreführend und kann außerdem die Verwendung in Texten mit grammatikalisch passendem Genus verhindern.

---

### 2.2 Der Titel wird verschluckt
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/namelist.py:43-47`

„Frau Krüger“ ist eine vollständige Variante und wird als Ganzes ersetzt. Der Titel geht dabei verloren. Für die Rückführung wird aus `<<LEHRERIN_01>>` lediglich `Sabine Krüger`, nicht `Frau Sabine Krüger`. Das ist zwar im Test so festgeschrieben, verändert aber den Text gegenüber dem Original und kann den Anredekontext verlieren.

**Beispiel:**
```text
Frau Krüger berichtet.
```
→
```text
<<LEHRERIN_01>> berichtet.
```
→
```text
Sabine Krüger berichtet.
```

---

### 2.3 Stage 3 ersetzt alle identischen Vorkommen, auch an semantisch anderer Stelle
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage3_llm.py:60-64`

`text.replace(found, repl)` wirkt global. Der Befund kann aber nur für eine Stelle erstellt worden sein.

**Beispiel:**
```text
Lena und ihr Bruder Ben gingen zum Sport.
Ben wirkte glücklich.
```
Ein Befund `span="Ben"` mit `replacement="der Schüler"` ersetzt beide Vorkommen. Der Test in `tests/test_stage3.py:36-39` dokumentiert dieses Verhalten sogar als gewünscht, obwohl es kein positionsgenaues Ersetzen ist.

---

### 2.4 Stufe 2 kann Namen in `PRESIDIO`-Entitäten wieder sichtbar machen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage2_noirdoc.py:105-125`

Funde, die einen Stufe-1-Platzhalter berühren, werden verworfen. Das ist korrekt, wenn der Fund den gesamten Namen enthält. Wenn der Fund nur am Rand des Platzhalters liegt oder der noirdoc-Text-Spans inkonsistent sind, kann der ursprüngliche Klartext wieder Bestandteil der Ersetzung werden. Zudem wird keine Invariante geprüft: Nach Stufe 2 dürfen keine aus der Namensliste bekannten Namen mehr enthalten sein.

---

### 2.5 Stufe 1 verwechselt Nachnamen mit einem Familien-/Mehrdeutigkeitsplatzhalter
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage1_namelist.py:35-56`

Wenn mehrere Personen denselben Nachnamen haben, wird bereits der einfache Nachname durch `<<FAMILIE_nn>>` ersetzt. Die Dokumentation in `CLAUDE.md:8` verspricht jedoch stabile Platzhalter je Person. Der Platzhalter kann in der Rückführung nicht mehr sagen, welche Person gemeint war; `reverse` bildet lediglich den Nachnamen ab.

**Beispiel:**
```text
Hoffmann kam später.
```
→
```text
<<FAMILIE_01>> kam später.
```
Das kann sowohl ein Schüler als auch ein Elternteil bezeichnen.

---

### 2.6 Die Rückführung ist bei Stufe-1-Platzhaltern mit Genitiv nicht symmetrisch
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/stage1_namelist.py:81-87`, `124-130`

Die Ersetzung erhält das Genitiv-`s`, die Rückführung setzt es aber nicht wieder zusammen:

```text
<<SCHUELERIN_01>>s Heft
```
→
```text
Lena Heft
```
statt `Lenas Heft`. Damit ist der dokumentierte Roundtrip nicht texttreu.

---

### 2.7 `DATE_RE` erkennt einige Datumsschreibweisen nicht
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/stage2_noirdoc.py:27-36`

Nicht erkannt werden unter anderem:
- `1.8.2014`,
- `01.08.14`,
- `1. August` ohne Jahr,
- `08/2014`,
- `01.08.2014` mit engem/no-break space.

Der Test `tests/test_stage1.py:67-70` deckt nur wenige Formate ab. Solche Daten können Stage 2 und Stage 4 passieren, sofern kein anderer Detektor sie findet.

---

### 2.8 Falscher Unicode-/Wortgrenzenbereich
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/stage1_namelist.py:23`, `66-69`

`\w` umfasst in Python bereits Unicode-Buchstaben. Der zusätzliche Ausdruck `[\wÄÖÜäöüß]` ist daher redundant; zugleich fehlen andere deutsche/alphabetische Zeichen, die Python `\w` zwar abdeckt, die aber durch die zusätzliche Einschränkung in eigenen Zeichenklassen problematisch werden können. Der Code sollte nur `\w` verwenden.

---

### 2.9 `evaluate.run` kann bei fehlendem `out/runs` mit `FileNotFoundError` abbrechen
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/evaluate.py:146-149`

```python
runs = sorted(project_path("out/runs").iterdir())
rdir = rdir or runs[-1]
```

Ohne existierendes `out/runs` oder mit leerem Verzeichnis gibt es keine verständliche CLI-Fehlermeldung und keinen Indexfehler.

---

### 2.10 `optimize` schreibt bei gleicher Prompt-Version in dasselbe Verzeichnis
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/optimize.py:92-124`

Der Run-Name ist nur `opt_<prompt>[_fs]`, unabhängig von Seed, Datensatz, `only` oder Optimierungsrunde. Ein wiederholter Optimierungsaufruf überschreibt die vorherigen Ergebnisdateien desselben Prompts.

**Beispiel:** Zwei Optimierungen mit `v1` und `--only doc_001` verwenden beide `out/runs/opt_v1`; die zweite Messung überschreibt die erste.

---

### 2.11 `reuse` übernimmt keine Herkunft der Stage-2-Ergebnisse
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/pipeline.py:64-70`

Beim Wiederverwenden werden nur die Texte und Treffer der Stufen 1 und 2 kopiert. Prompt-, Namelisten- oder Konfigurationsänderungen seit dem Basislauf werden nicht geprüft. Die Kennzeichnung des Laufs kann somit eine inkompatiblere Stufe 1+2 messen.

**Beispiel:** Nach einer Änderung an `namelist.csv` oder `config.yaml` wird weiterhin der alte Stufe-1-Output eines früheren Laufs verwendet.

---

### 2.12 `reuse` mit `stages < 3` referenziert nicht vorhandene Stufe 3
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/pipeline.py:65-70`, `89-99`

Die Reuse-Routine setzt `"local_only": False`, übernimmt aber keine alten Stufe-3-Treffer oder Metadaten. Bei einem Lauf mit `stages=1` oder `stages=2` und `reuse` existiert `stages["3"]` nicht; die `last`-Auswahl bleibt zwar bei 1/2, die Reuse-Metrik ist aber semantisch falsch und zukünftige Erweiterungen können darauf aufbauen.

---

### 2.13 Das lokale Flag kann aus dem LLM-JSON ohnehin verloren gehen
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/stage3_llm.py:88-92`, `prompts/stage3/v1.md:19`

`resp.get("findings", [])` akzeptiert jede Liste. Bei einem Response wie
```json
{"findings": [{"span":"ADHS","replacement":"ADHS","category":"GESUNDHEIT"}]}
```
wird zwar `local_only` gesetzt, die identische sensible Angabe bleibt aber im Text. Es gibt keine Schutzregel gegen Ersetzungen, die semantisch gleichwertig oder sogar identisch zum Original sind.

---

### 2.14 `generate_synthetic` kann bei leerer Hostliste einen Laufzeitfehler verursachen
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/generate_synthetic.py:148-153`

Wenn kein Ollama-Host erreichbar ist, ist `hosts=[]`. Anschließend verwendet `cycle(hosts)` ohne Host und `ThreadPoolExecutor(max_workers=0)` ist ungültig. Der Nutzer erhält keine klare Meldung wie beim Pipeline-Lauf.

---

### 2.15 Die Weboberfläche wählt den „letzten“ Lauf nur lexikografisch
**Schweregrad: niedrig**  
**Fundstelle:** `src/blackdocu/web.py:99-101`

Die Sortierung ist alphabetisch. Bei IDs mit unterschiedlichem Präfix oder Zeitformat kann nicht der neueste Lauf gewählt werden. Besser wäre eine Sortierung nach Erzeugungszeit.

---

## 3. Schwächen der Evaluation

### 3.1 Gesperrte Dokumente zählen nicht als „kein Leck“
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/evaluate.py:73-103`

Die Evaluation untersucht nur `r["stages"][lv]`, nicht den tatsächlichen Freigabepfad. Ein Dokument mit 100 % direkten Lecks, das von Stufe 4 gesperrt wird, erscheint in der Leckrate genauso wie ein vollständig sauberes Dokument.

Die vorgeschriebenen Ziele sind:
- direkte Leckrate: 0 %,
- bei Prüffund: Text sperren.

Die Metrik sollte getrennt ausweisen:
1. Lecks in freigegebenen Texten,
2. korrekt gesperrte Dokumente,
3. Lecks in gesperrten Dokumenten,
4. unerkannte Lecks in freigegebenen Texten.

Die aktuelle Ausgabe kann eine Sicherheitslücke als Erfolg darstellen.

---

### 3.2 Die direkte Leckrate prüft nur einzelne Name-Token
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/evaluate.py:35-41`

`direct_leak` gibt `True` zurück, wenn **irgendein** Token des Eintrags noch vorkommt. Das erzeugt sowohl Falschpositive als auch eine zu optimistische Interpretation:

- `direct_leak("Frau Matthes", "Frau <<LEHRKRAFT_02>>")` ist `False`, obwohl der Titel erhalten blieb.
- Ein Leck nur des Nachnamens wird als Leck des vollständigen Eintrags gezählt.
- Bei zusammengesetzten Namen wird kein vollständiger Begriff verlangt.
- Ein Vorname, der zufällig als gewöhnliches Wort vorkommt, gilt als Leck.

Die Ground Truth sollte konkrete kanonische Varianten und konkrete unerlaubte Resttexte definieren, statt heuristisch Name-Token zu prüfen.

---

### 3.3 Die indirekte Leckrate ist empfindlich gegenüber Formulierungsunterschieden
**Schweregrad: hoch**  
**Fundstelle:** `src/blackdocu/evaluate.py:44-52`

`fuzz.partial_ratio >= 85` kann einen semantisch gleichwertigen, aber bewusst generalisierten Hinweis als Leck bewerten. Umgekehrt kann ein noch identifizierender, aber umformulierter Hinweis unter 85 fallen und als sauber gelten.

**Beispiel:**  
Ground Truth: `seit dem Umzug aus Kiel`  
Ergebnis: `seit dem Umzug aus einem Ort in Norddeutschland`  
Der Ort ist noch identifizierend, aber der Test kann dies je nach Score als nicht leakend einstufen.

Außerdem wird nur die Existenz eines ähnlichen Substrings geprüft, nicht, ob der Hinweis semantisch erhalten oder generalisiert wurde.

---

### 3.4 `local_only` wird gegen ein Ground-Truth-Orakel bewertet, das aus derselben Stichprobe stammt
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:105-115`, `src/blackdocu/generate_synthetic.py:37-64`

Die erwartete Klassifikation entsteht aus `expected == "local_only"` in den Generator-Templates. Die realen LLM-Ergebnisse werden gegen dieses Orakel geprüft, aber der Generator verwendet einen kleinen, festen Pool von 13 Dev- und 10 Holdout-Formulierungen. Das misst weitgehend Prompt-/Modellverhalten auf bekannten Phrasen, nicht die Erkennung beliebiger sensibler Hinweise.

Zudem wird ein Erfolg nur dann anerkannt, wenn `local_only` gesetzt wurde. Ob der Text tatsächlich noch sensible Angaben enthält, wird bei `local_only=true` nicht zusätzlich geprüft.

---

### 3.5 Die Übermaskierung misst Tokenverlust, nicht Semantik
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:55-64`

`SequenceMatcher` zählt jedes ersetzte Originaltoken als unnötig, sofern es nicht in einem Ground-Truth-String vorkommt. Dadurch werden unter anderem folgende Fälle gleich bewertet:
- sachlich richtige Generalisierung eines nicht gelisteten Indikators,
- Fehler in einem echten PII-Span,
- sprachlich unnötige Ersetzung,
- Ersatz eines ganzen Satzteils durch einen kurzen Platzhalter.

Zudem werden insertions im neuen Text nicht berücksichtigt. Die Metrik misst eher Token-Differenz als Lesbarkeit.

---

### 3.6 Die Auswertung kennt nur die letzte Stufe; Stufe 4 ist keine kumulative Messstufe
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:70-103`

Die Stufen 1 bis 3 werden getrennt gemessen, Stufe 4 aber nur als Zahl blockierter Dokumente. Es fehlt:
- die Leckrate nach der Sperrlogik,
- Recall/Specificity der Sperrstufe,
- eine kumulative Darstellung „1+2+3+4“.

Dadurch lässt sich nicht beantworten, ob Stufe 4 die verbliebenen Lecks tatsächlich verhindert.

---

### 3.7 Fehlende oder unvollständige Ground Truth wird stillschweigend geschluckt
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:76-79`

`gt["direct"]` und `gt["indirect"]` werden ohne `.get(...)` verwendet. Fehlende Dateien oder Keys verursachen einen Abbruch. Umgekehrt enthält `generate_synthetic.py:133-137` die Information `dropped`; diese wird nicht als fehlende Abdeckung ausgewiesen. Das kann zu irreführend niedrigen oder hohen Raten führen.

---

### 3.8 Zufällige und systematische Fehler werden nicht getrennt berichtet
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:101-103`

Es gibt nur aggregierte Raten. Bei 40 Dokumenten und wenigen Ground-Truth-Einträgen kann ein einziger Fehler die Rate stark verändern. Es fehlen:
- Konfidenzintervalle,
- Leckanzahl und Anzahl betroffener Dokumente,
- getrennte Auswertung nach Dokumenttyp und Sensitivitätsstufe,
- eine explizite Holdout-Auswertung.

Die Dev- und Holdout-Pools werden in den Metriken nicht getrennt ausgewiesen.

---

### 3.9 Die Optimierungs-Zielfunktion bevorzugt Untererkennung
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/optimize.py:49-55`

```python
return last["indirect_leak"] + om + 0.5 * fn_rate
```

Direkte Lecks, falsch als `local_only` markierte Dokumente, gesperrte Dokumente und die Sicherheitswirkung von Stufe 4 fließen nicht in die Zielfunktion ein. Ein Prompt kann deshalb gewinnen, obwohl er mehr direkte Personenbezüge erzeugt, weil nur indirekte Lecks und `local_only`-Recall berücksichtigt werden.

---

### 3.10 Die erzeugten Testdaten sind strukturell leichter als reale Texte
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/generate_synthetic.py:66-69`, `90-115`

Das LLM wird angewiesen, exakt vorgegebene Bausteine einzubauen und keine weiteren Orte, Einrichtungen oder Daten zu erfinden. Damit fehlen genau die realistischen Leckpfade:
- unerwartete weitere Namen,
- Adressen, Telefonnummern, E-Mail-Adressen,
- Klassen-/Jahrgangsangaben,
- Initials, Spitznamen,
- Geburtsdaten in uneinheitlichen Formaten,
- verschiedene Satzanordnungen und Grammatikalien.

Die gemessene Leckrate ist deshalb eher eine Leistungsmessung auf kontrollierten Bausteinen als auf realistischen Schülertexten.

---

### 3.11 Es gibt keinen Negativtest gegen semantisch neutrale Textpassagen
**Schweregrad: mittel**  
**Fundstelle:** `src/blackdocu/evaluate.py:55-64`

„Übermaskierung“ wird nur durch nicht gelistete Wörter approximiert. Ein Testfall wie „sie ist zuverlässig“ oder „nimmt am Schwimmunterricht nicht teil“ wäre nötig, um zu prüfen, ob Stage 3 pädagogisch neutrale Passagen tatsächlich unverändert lässt.

---

## 4. Wartbarkeit und Vereinfachung

### 4.1 Drei unterschiedliche Regeln für Platzhalter
**Fundstelle:** `src/blackdocu/stage1_namelist.py:124`, `src/blackdocu/stage2_noirdoc.py:26`, `src/blackdocu/stage3_llm.py:20`, `src/blackdocu/stage4_verify.py:15`, `src/blackdocu/web.py:26`

Jedes Modul definiert eine eigene Regex. `stage2_noirdoc` und `stage4_verify` erlauben kein Genitiv-`s`, `evaluate.py` schon. Eine zentrale Platzhalterdefinition und zentrale Maskierungs-/Reveal-Funktionen würden sowohl Korrektheits- als auch Sicherheitsfehler vermeiden.

---

### 4.2 Mehrere, nicht synchronisierte Prompt-Versionen
**Fundstelle:** `prompts/stage3/v1.md` bis `v5.md`

`v2` bis `v4` sind von `optimize` erzeugte Varianten mit widersprüchlichen Regeln:

- `v1.md:12` sagt: exakter Span.
- `v3.md:5` verbietet Platzhalter im Span.
- `v5.md:16` erlaubt Platzhalter ausdrücklich.
- `v2.md:7` erlaubt bei LRS eine Beibehaltung, `v5.md:10` verlangt eine Ersetzung.
- `v4.md:34` enthält die literale Zeile `{text}`, obwohl der Prompt in `stage3_llm.py:88` ohne Formatierung als Systemnachricht verwendet wird.

Die Versionen sollten als Kandidaten mit Messwerten registriert und nicht als frei schwebende Promptdateien geführt werden.

---

### 4.3 Fehlerbehandlung ist uneinheitlich
**Fundstelle:** `src/blackdocu/pipeline.py:39-44`, `src/blackdocu/generate_synthetic.py:153-159`, `src/blackdocu/fewshot.py:51-58`, `src/blackdocu/stage3_llm.py:29-40`

Manche Fehler bedeuten „Dokument sicher sperren“, andere „Fehler ignorieren“, wieder andere „Fallback suchen“. Es fehlt ein einheitliches Ergebnisobjekt mit klaren Zuständen wie `success`, `failed_safe`, `failed_open`.

Insbesondere behandelt `fewshot.embed` jeden Fehler als „keine Embeddings“, ohne den Fehler zu protokollieren.

---

### 4.4 `pipeline.py` koppelt Ausführung, Persistenz und Statusmodell
**Fundstelle:** `src/blackdocu/pipeline.py:47-115`

Die Funktion liest, transformiert, parallelisiert, verifiziert und schreibt in zwei Ausgabeverzeichnisse. Für die Nutzung mit echten Daten wäre eine klarere Trennung hilfreich:

1. reiner Transformation-Lauf ohne Nebenwirkungen,
2. explizite Verifikation,
3. Freigabe/Sperrung,
4. persistentes Ergebnis.

Aktuell entstehen Nebenprodukte in Run-Dateien, `out/pseudonymized/`, `out/blocked/` und der Namespace-Datei.

---

### 4.5 `evaluate.py` liest und schreibt dieselbe Run-Struktur ohne Schema
**Fundstelle:** `src/blackdocu/evaluate.py:67-123`, `src/blackdocu/pipeline.py:75-112`

Es gibt keine versionierte Definition der JSON-Struktur. Änderungen an `stages`, `hits` oder `seconds` führen still zu `KeyError` oder falschen Auswertungen. Ein Pydantic-Modell oder zumindest ein zentraler Dataclass-Vertrag wäre robuster.

---

### 4.6 `fewshot.py` verwendet eine ungenaue, globale Generalisierungstabelle
**Fundstelle:** `src/blackdocu/fewshot.py:40`, `61-65`

```python
GEN = {re.sub(r"\{ort\}.*", "", t): g for t, _, _, g in INDIREKT}
```

Alle Ort-Varianten werden auf denselben Präfix reduziert; `startswith` erzeugt potenziell mehrere Präfix-Matches. Die Beispiele sollten direkt aus der jeweiligen Ground Truth mit explizitem `generalized`-Wert gebaut werden, statt die Formulierung aus einer globalen Liste zu erraten.

---

## Kurzfazit

Die Codebasis enthält gute deterministische Grundlagen: Stufe 1 und Stage 3 schlagen keine unkontrollierten Ersetzungen vor, Platzhalter werden geschützt, und der noirdoc-Namespace ist grundsätzlich für Rückführung gedacht.

Die größten verbleibenden Risiken sind jedoch:

1. **Die Evaluation misst die Vorstufen, nicht das Sicherheitsverhalten des gesamten Freigabepfads.**
2. **Sperren und `local_only` sind keine belastbaren Zugriffskontrollen.**
3. **Klartextkopien liegen unverschlüsselt in Run-Dateien, Entwürfen, Screenshots und potenziell in der Beispielbank.**
4. **Die Weboberfläche kann Originale und zurückgewandelte Namen ohne Authentifizierung anzeigen.**
5. **Die Ground Truth deckt realistische PII-Fehler nur eingeschränkt ab und kann Lecks falsch als Erfolg darstellen.**

Für den Produktivbetrieb mit echten Schülertexten sollten vor allem Freigabe-Gate, Verschlüsselung und Löschkonzept der Artefakte, Zugriffsschutz der Weboberfläche sowie eine freigabeorientierte Evaluation umgesetzt werden.
