from pathlib import Path

import pytest

from blackdocu.config import PROJECT_ROOT, load_config
from blackdocu.decisions_db import add_decision, connect
from blackdocu.generate_synthetic import check_ground_truth
from blackdocu.namelist import load_namelist


def test_config_has_both_hosts():
    cfg = load_config()
    assert set(cfg["llm"]["hosts"]) == {"studio", "desktop"}


def test_namelist_placeholders_and_variants():
    people = load_namelist(PROJECT_ROOT / "data" / "namelist.csv")
    lena = people[0]
    assert lena.placeholder == "<<SCHUELERIN_01>>"
    v = lena.variants()
    assert {"Lena Hoffmann", "Hoffmann, Lena", "Lenas", "Lenchen"} <= set(v)
    assert v[0] == max(v, key=len)
    kr = next(p for p in people if p.nachname == "Krüger")
    assert kr.placeholder == "<<LEHRERIN_01>>" and "Frau Krüger" in kr.variants()


def test_decisions_db_rejects_clear_names(tmp_path: Path):
    con = connect(tmp_path / "d.sqlite")
    rid = add_decision(con, case_id="<<SCHUELER_07>>", decision="Note 2",
                       rationale="Kriterien erfüllt", actor="agent", role="gutachter")
    assert rid == 1
    with pytest.raises(ValueError):
        add_decision(con, case_id="Lena Hoffmann", decision="x", rationale="y", actor="agent")
    with pytest.raises(ValueError):
        add_decision(con, case_id="<<SCHUELER_07>>", decision="x", rationale="y",
                     actor="mensch", status="ueberstimmt")


def test_ground_truth_check():
    gt = {"direct": [{"text": "Lena"}], "indirect": [{"text": "Umzug aus Kiel"}]}
    assert check_ground_truth("Lena kam nach dem Umzug aus Kiel.", gt) == []
    assert check_ground_truth("Lena kam.", gt) == ["Umzug aus Kiel"]


def test_only_local_llm_hosts():
    from blackdocu.llm import assert_local
    for ok in ["http://127.0.0.1:11434", "http://localhost:11434", "http://100.109.37.47:11434",
               "http://192.168.1.5:11434"]:
        assert assert_local(ok) == ok
    for bad in ["https://api.example.com", "http://8.8.8.8:11434"]:
        with pytest.raises(ValueError):
            assert_local(bad)


def test_decisions_db_rejects_names_in_free_text(tmp_path):
    people = load_namelist(PROJECT_ROOT / "data" / "namelist.csv")
    con = connect(tmp_path / "d.sqlite")
    with pytest.raises(ValueError, match="Klarnamen"):
        add_decision(con, case_id="<<SCHUELER_07>>", decision="Note 2 für Lena Hoffmann",
                     rationale="Fortschritte", actor="mensch", people=people)
    assert add_decision(con, case_id="<<SCHUELER_07>>", decision="Note 2",
                        rationale="<<SCHUELERIN_01>>s Fortschritte", actor="mensch", people=people)
