# Prompt-Versionen für Stufe 3

Gemessen auf dem Dev-Set (doc_001–040, Stufe 1+2 aus Basislauf), Zielwert J (kleiner = besser).
Endkontrolle auf dem Holdout-Set (doc_101–140, andere Hinweis-Muster).

| Version | Herkunft | J (Dev) | Status |
|---|---|---|---|
| v1 | von Hand, Ausgangspunkt | 0,077 | Referenz |
| v2 | `optimize` aus v1 | 0,151 | verworfen: zu vorsichtig, mehr Lecks |
| v3 | `optimize` aus v1 | 0,175 | verworfen; verbietet Platzhalter im Span (widerspricht Code) |
| v4 | `optimize` aus v1 | 0,246 | verworfen; enthält unbenutztes `{text}` |
| **v5** | von Hand aus v1 (Grammatik, Einrichtungen, „im Zweifel melden“) | 0,071 | **in Gebrauch**, mit Beispielbank 0,041 |

v2–v4 bleiben nur als Nachweis des Optimierungsversuchs erhalten. Neue Versionen: Datei `vN.md`,
Kopfzeile mit Herkunft, Messung mit `blackdocu optimize <basislauf> --rounds 0 --start vN [--fewshot]`.
