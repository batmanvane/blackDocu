import pytest

from blackdocu.config import PROJECT_ROOT
from blackdocu.namelist import load_namelist
from blackdocu.stage1_namelist import redact


@pytest.fixture(scope="module")
def people():
    return load_namelist(PROJECT_ROOT / "data" / "namelist.csv")


def r(text, people):
    return redact(text, people)[0]


def test_full_name_and_genitive(people):
    out = r("Lena Hoffmann ist fleißig. Lenas Heft ist ordentlich.", people)
    assert out == "<<SCHUELERIN_01>> ist fleißig. <<SCHUELERIN_01>>s Heft ist ordentlich."


def test_inverse_and_nickname(people):
    assert r("Hoffmann, Lena; Lenchen lacht.", people) == "<<SCHUELERIN_01>>; <<SCHUELERIN_01>> lacht."
    assert r("Maxi und Maximilians Bruder", people) == "<<SCHUELER_02>> und <<SCHUELER_02>>s Bruder"


def test_lowercase(people):
    assert r("lena hat gut mitgearbeitet.", people) == "<<SCHUELERIN_01>> hat gut mitgearbeitet."


def test_teacher_with_title(people):
    assert r("Frau Krüger (Klassenleitung) berichtet.", people) == "<<LEHRERIN_01>> (Klassenleitung) berichtet."


def test_shared_surname_becomes_family(people):
    out = r("Die Familie Hoffmann zog um.", people)
    assert "Hoffmann" not in out and "<<FAMILIE_" in out


def test_typo_fuzzy(people):
    out = r("Lena Hofmann fehlte oft. Herr Wendlandt kam.", people)
    assert "Hofmann" not in out and "Wendlandt" not in out


def test_no_partial_word_match(people):
    # "Ben" darf nicht in "Benehmen" ersetzt werden, "Jo" nicht in "Jonglieren"
    assert r("Ihr Benehmen beim Jonglieren", people) == "Ihr Benehmen beim Jonglieren"


def test_no_fuzzy_on_common_words(people):
    assert r("Der Brand im Labor", people) == "Der Brand im Labor"


def test_hits_report_offsets(people):
    text = "Ben Yilmaz kam."
    _, hits = redact(text, people)
    assert hits[0]["text"] == "Ben Yilmaz" and hits[0]["start"] == 0
    assert hits[0]["placeholder"] == "<<SCHUELER_03>>"


def test_reveal_roundtrip(people):
    from blackdocu.stage1_namelist import reveal
    out = r("Lenas Mutter sprach mit Frau Krüger.", people)
    assert reveal(out, people) == "Lenas Mutter sprach mit Sabine Krüger."


def test_regex_dates():
    from blackdocu.stage2_noirdoc import regex_dates
    found = [d.text for d in regex_dates("geb. am 20.01.2016, Einschulung 1. August 2022, Stand 2024-05-01, 3. Klasse")]
    assert found == ["20.01.2016", "1. August 2022", "2024-05-01"]
    for t in ["01.08.14", "1. August", "am 3.5. Geburtstag", "seit 08/2014", "1.8.2014", "12. Okt."]:
        assert regex_dates(t), t
    for t in ["Note 2,5", "3. Klasse", "Kapitel 4", "Seite 12.", "2 von 5"]:
        assert not regex_dates(t), t


def test_regex_contacts():
    from blackdocu.stage2_noirdoc import regex_dates
    types = {e.entity_type: e.text for e in regex_dates("Mail: lena.h@example.org, Tel. 0331 1234567")}
    assert types["EMAIL"] == "lena.h@example.org" and types["PHONE"].startswith("0331")


def test_gendered_placeholders_and_titles(people):
    out = r("Frau Hoffmann und Herr Wendland", people)
    assert out == "<<MUTTER_01>> und <<LEHRER_02>>"
    # "Herr Hoffmann" passt zu keiner männlichen Person -> nur Nachname, also Familien-Platzhalter
    assert "<<MUTTER_01>>" not in r("Herr Hoffmann", people)
