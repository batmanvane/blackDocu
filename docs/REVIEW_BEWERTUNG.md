# Bewertung des MiniMax-M3-Reviews (18.11.2026)

Review: `docs/REVIEW_MINIMAX_2026-11-18.md` (opencode, MiniMax-M3, nur Code ohne Testdaten, Lesemodus).
Jeder Befund wurde am Code geprüft. ✅ umgesetzt · 📝 dokumentiert (vor echten Daten) · ❌ abgelehnt

| Nr. | Befund | Urteil | Begründung / Umsetzung |
|---|---|---|---|
| 1.1 | Klartext in Lauf-Protokollen | 📝 | stimmt; nötig für Evaluation mit synthetischen Daten → CLAUDE.md „Vor echten Daten“. Behauptung „gesperrte Texte landen im Freigabeordner“ ist falsch |
| 1.2 | `local_only` ohne Wirkung | ✅ | eigener Ordner `out/local_only`; nur `out/pseudonymized` ist extern freigebbar |
| 1.3 | FAMILIE ohne `sensitive` bleibt extern | ✅ | FAMILIE löst immer `local_only` aus |
| 1.4 | `local_only` auch bei nicht gefundenem Span | ❌ | gewollt: im Zweifel lokal |
| 1.5 | Fehler in Stufe 3 → trotzdem freigegeben | ✅ | Stufe-3-Fehler sperrt den Text |
| 1.6 | Web ohne Anmeldung | 📝 | Demo auf 127.0.0.1 mit synthetischen Daten; vor Echtbetrieb Anmeldung |
| 1.7 | Entwurf-Cache veraltet | ❌ | Cache ist je Lauf getrennt; Demo-Zweck |
| 1.8 | Span mit Platzhalter entfernt Pseudonym | ❌ | gewollt: Verallgemeinerung entfernt den Ort samt Platzhalter |
| 1.9/2.3 | `replace` ersetzt alle Vorkommen | ❌ | gewollt (sonst Leck bei Wiederholung, im Basislauf gemessen); Namen ersetzt Stufe 3 nicht |
| 1.10 | Prüfstufe nur PERSON | ✅ | zusätzlich Regeln für Daten/E-Mail/Telefon und `strict_types` (Kontakt-/Kennnummern) |
| 1.11 | NER in Prüfstufe auf unmaskiertem Text | ❌ | Funde an Platzhaltern werden in `Stage2.detect` verworfen |
| 1.12 | Zuordnung im Projektordner | 📝 | nur für synthetische Daten konfiguriert; Hinweis für Echtbetrieb |
| 1.13 | Klarnamen in DB-Freitext | ✅ | `add_decision(..., people=...)` prüft Freitext gegen Namensliste und Daten; unbekannte Felder abgelehnt |
| 1.14 | Beispielbank kann Namen enthalten | ✅ | Sätze mit Restnamen/Daten werden verworfen; Embedding-Fehler werden gemeldet |
| 1.15 | Optimierer sendet Fehlertexte | ❌ | nur lokales Modell, nur synthetische Daten |
| 1.16 | Tailscale unverschlüsselt | ❌ | falsch: Tailscale verschlüsselt (WireGuard) |
| 1.17 | Host aus Konfiguration ungeprüft | ✅ | `llm.assert_local`: nur Loopback/privat/Tailnet |
| 2.1 | SCHUELERKIND-Präfix | ❌ | nur bei unbekanntem Geschlecht, bewusst neutral |
| 2.2 | Anrede geht verloren | ❌ | kosmetisch, Rückwandlung liefert vollen Namen |
| 2.5 | FAMILIE-Platzhalter mehrdeutig | ❌ | gewollt bei gemeinsamem Nachnamen |
| 2.6 | Genitiv bei Rückwandlung | ❌ | falsch: Test `test_reveal_roundtrip` belegt „Lenas“ |
| 2.7 | Datumsformate fehlen | ✅ | teils richtig („1.8.2014“ wurde schon erkannt): neu 2-stellige Jahre, „1. August“, „3.5.“, „08/2014“ |
| 2.8 | `\w` redundant | ❌ | harmlos |
| 2.9/2.14 | Abbrüche ohne Meldung | ✅ | klare Fehlermeldungen |
| 2.10 | Optimierer überschreibt Läufe | ✅ | Zeitstempel im Laufnamen |
| 2.11 | Herkunft bei `reuse` fehlt | ✅ | in `config.json` unter `_run` |
| 2.13 | Ersetzung = Original | ✅ | wird verworfen |
| 3.1/3.6 | Evaluation ignoriert Sperre | ✅ | neue Tabelle „Nach der Prüfstufe“: nicht gesperrt / extern freigegeben |
| 3.2 | Token-Prüfung zu optimistisch | ❌ | eher zu streng (jeder Namensteil zählt) |
| 3.3/3.5 | Unschärfe der Metriken | 📝 | bekannte Grenze, im Briefing benannt |
| 3.4/3.10 | Testdaten zu einfach | ✅ | neue Bausteine: Personen außerhalb der Liste, E-Mail, Telefon, Adresse; Set `holdout2` |
| 3.8 | keine Konfidenzintervalle | ✅ | Wilson-95-%-Intervalle in der Gate-Tabelle |
| 3.9 | Zielfunktion ohne direkte Lecks | ✅ | J = 2·direkt + indirekt + Übermaskierung + 0,5·übersehene local_only |
| 4.1 | Platzhalter-Regex mehrfach | ✅ | `placeholders.py` |
| 4.2 | widersprüchliche Prompt-Versionen | ✅ | `prompts/stage3/README.md` mit Status |
| 4.3 | Fehler still geschluckt | ✅ (teilw.) | Embeddings melden Fehler |
| 4.4/4.5 | Refactoring Pipeline/Schema | ❌ | später, nicht nötig für Phase 1 |

Fazit: brauchbares Review mit einigen sachlichen Fehlern (Tailscale, Genitiv, „gesperrt landet in Freigabe“).
Wertvollste Punkte: Freigabe-Gate statt nur Kennzeichnung, Evaluation nach dem Gate, realistischere Testdaten.
