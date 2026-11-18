from blackdocu.evaluate import direct_leak, indirect_leak, overmask


def test_direct_leak_partial_name():
    assert direct_leak("Anton Reimann", "<<SCHUELER_23>> Reimann kam.")
    assert not direct_leak("Anton Reimann", "<<SCHUELER_23>> kam.")
    assert direct_leak("Antons", "Anton kam")  # Stamm reicht
    assert not direct_leak("Frau Matthes", "Frau <<LEHRKRAFT_02>>")


def test_indirect_leak_ignores_replaced_city():
    e = "seit dem Umzug aus Kiel"
    assert indirect_leak(e, "Sie ist seit dem Umzug aus <<LOCATION_1>> still.", ["Kiel"])
    assert not indirect_leak(e, "Sie ist seit einem Wohnortwechsel still.", ["Kiel"])


def test_overmask():
    gt = {"direct": [{"text": "Lena"}], "indirect": []}
    assert overmask("Lena rechnet gut", "<<S_1>> rechnet gut", gt) == 0
    assert overmask("Lena rechnet gut", "<<S_1>> <<X_1>> gut", gt) > 0.3


def test_wilson():
    from blackdocu.evaluate import wilson
    lo, hi = wilson(2, 43)
    assert 0.01 < lo < 0.02 and 0.15 < hi < 0.16
    assert wilson(0, 0) == (0.0, 0.0)


def test_direct_leak_contacts():
    assert direct_leak("lena.hoffmann@web.de", "Mail an lena.hoffmann@web.de")
    assert not direct_leak("lena.hoffmann@web.de", "Mail an <<EMAIL_1>>")
    assert direct_leak("0331 4567890", "Tel. 0331-4567890")
    assert not direct_leak("0331 4567890", "Tel. <<PHONE_1>>")
    assert direct_leak("Lindenstraße 12", "wohnt Lindenstraße 12")
    assert not direct_leak("Lindenstraße 12", "wohnt <<LOCATION_3>>")
    assert direct_leak("ihre Freundin Jule Martens", "ihre Freundin Jule")


def test_generic_institution_word_is_no_leak():
    assert not direct_leak("Jugendclub Kiste", "im Jugendclub <<ORGANIZATION_7>>")
    assert direct_leak("Jugendclub Kiste", "im Jugendclub Kiste")
