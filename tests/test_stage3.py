from blackdocu.stage3_llm import Stage3, apply_findings

T = "<<SCHUELER_01>> kam nach dem Umzug aus <<LOCATION_1>>. Sie ist das einzige Kind mit Rollstuhl."


def test_span_with_placeholder_is_allowed():
    out, applied, _ = apply_findings(T, [{"span": "nach dem Umzug aus <<LOCATION_1>>",
                                          "replacement": "nach einem Umzug"}])
    assert out.startswith("<<SCHUELER_01>> kam nach einem Umzug.") and applied


def test_replacement_must_not_contain_placeholder():
    _, applied, _ = apply_findings(T, [{"span": "Rollstuhl", "replacement": "<<X_1>>"}])
    assert not applied


def test_fuzzy_span_inflection():
    out, applied, _ = apply_findings(T, [{"span": "einziges Kind mit Rollstuhl",
                                          "replacement": "ein Kind mit besonderem Bedarf"}])
    assert "Rollstuhl" not in out and applied[0]["status"].startswith("angewandt:fuzzy")


def test_unknown_span_is_dropped_but_sensitive_flags():
    _, applied, local_only = apply_findings(T, [{"span": "ADHS", "replacement": "x",
                                                 "category": "GESUNDHEIT"}])
    assert not applied and local_only


def test_stage3_with_fake_llm():
    cfg = {"stage3": {"prompt": "v1"}}
    fake = lambda cfg, system, user: {"findings": [{"span": "Rollstuhl", "replacement": "Hilfsmittel"}]}
    out, _, _, meta = Stage3(cfg, chat=fake).redact(T)
    assert "Hilfsmittel" in out and meta["applied"] == 1


def test_all_occurrences_replaced():
    t = "Nach der Trennung der Eltern kam sie. Auch nach der Trennung der Eltern blieb sie."
    out, _, _ = apply_findings(t, [{"span": "der Trennung der Eltern", "replacement": "einer Veränderung"}])
    assert "Trennung" not in out


def test_allowlist():
    from blackdocu.stage2_noirdoc import allowed
    allow = {"mathe", "bio", "uhr", "raum"}
    assert allowed("Bio und Mathe", allow) and allowed("15 Uhr, Raum", allow)
    assert not allowed("Praxis Dr. Weber", allow)
    assert not allowed("Do 27.11.2026", allow | {"do"})


def test_allowlist_inflection_and_suffix():
    from blackdocu.config import project_path
    from blackdocu.stage2_noirdoc import allowed, load_allowlist
    allow = load_allowlist(project_path("data/allowlist.txt"))
    for ok in ["Vaters", "Damen und Herren", "Sohnes", "Fähigkeit, Theorie", "Inklusion", "Schülers"]:
        assert allowed(ok, allow), ok
    for bad in ["Herr Jung", "Frau Kaiserheit", "Herr Müller", "Syrien", "Waldorfschule", "Lena Schulz", "15. Oktober 2023"]:
        assert not allowed(bad, allow), bad


def test_family_always_local_only_and_noop_replacement_dropped():
    _, applied, lo = apply_findings("nach der Inhaftierung des Vaters kam er",
                                    [{"span": "nach der Inhaftierung des Vaters",
                                      "replacement": "nach einer Veränderung", "category": "FAMILIE",
                                      "sensitive": False}])
    assert lo and applied
    _, applied, _ = apply_findings("wegen ADHS unruhig", [{"span": "ADHS", "replacement": "ADHS"}])
    assert not applied
