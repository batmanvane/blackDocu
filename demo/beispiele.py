import json
from blackdocu.config import load_config, project_path
from blackdocu.namelist import load_namelist
from blackdocu.stage1_namelist import redact as s1, reveal as r1
from blackdocu.stage2_noirdoc import Stage2
from blackdocu.stage3_llm import Stage3
from blackdocu import llm

cfg = load_config(); cfg["stage3"]["prompt"] = "v5"; cfg["noirdoc"]["namespace"] = "beispiele_briefing"
people = load_namelist(project_path(cfg["namelist"]["path"]))
st2, st3 = Stage2(cfg), Stage3(cfg)

CASES = [
 ("Elternmail aus Stichpunkten",
  "Schreibe aus diesen Stichpunkten eine freundliche, sachliche E-Mail der Klassenleitung an die Eltern (6-8 Sätze, Anrede und Gruß).",
  "Mail an Andrea Hoffmann wg. Lena\n- Lena fehlt seit 3 Wochen oft montags\n- seit der Trennung der Eltern sehr still\n- Hausaufgaben Mathe fehlen 5x\n- Gesprächstermin anbieten: Do 27.11.2026, 15 Uhr, Raum 204\n- Frau Krüger (Schulsozialarbeit) könnte dazukommen"),
 ("Zeugnisbemerkung aus Stichpunkten",
  "Formuliere aus diesen Stichpunkten eine Zeugnisbemerkung zum Arbeits- und Sozialverhalten (4-5 Sätze, wertschätzend, ohne Diagnosen oder Familiendetails).",
  "Maximilian Brandt, 7b\n- Maxi arbeitet in Bio und Mathe sehr engagiert\n- wegen der ADHS-Diagnose oft unruhig in langen Stillarbeitsphasen\n- hilft Ben Yilmaz regelmäßig beim Lesen\n- Streitschlichter seit Februar\n- Heftführung unordentlich"),
 ("Projektbewertung aus Notizen",
  "Schreibe aus diesen Notizen eine kurze, begründete Bewertung eines Projektberichts mit Notenvorschlag (5-6 Sätze).",
  "Projektbericht 'Wasserqualität der Havel' – Amira Haddad & Jonas Kowalski\n- Messreihe sauber, 12 Proben, Fotos gut\n- Amira: Auswertung und Diagramme, sehr selbstständig\n- Jonas: Literaturteil dünn, Quellen fehlen\n- Präsentation am 14.11.2026 überzeugend\n- Amira ist die Landesmeisterin im Schach – hat Projekt trotz Turnieren pünktlich abgegeben"),
]
SYS = "Du bist Lehrkraft. Platzhalter wie <<SCHUELER_01>> oder <<DATE_1>> unverändert übernehmen, keine Namen erfinden. Antworte nur mit JSON: {\"text\": \"...\"}"
out = []
for title, task, raw in CASES:
    t1, _ = s1(raw, people)
    t2, _ = st2.redact(t1)
    t3, f3, lo, _ = st3.redact(t2)
    draft = llm.chat_json(cfg, SYS + "\n" + task, t3, host="studio")["text"]
    final = r1(st2.reveal(draft), people)
    out.append({"title": title, "raw": raw, "pseudo": t3, "draft": draft, "final": final, "local_only": lo,
                "llm": [(f.get("span"), f.get("replacement")) for f in f3 if str(f.get("status","")).startswith("angewandt")]})
    print(json.dumps(out[-1], ensure_ascii=False, indent=1))
json.dump(out, open(project_path("out/demo/beispiele.json"), "w"), ensure_ascii=False, indent=1)
