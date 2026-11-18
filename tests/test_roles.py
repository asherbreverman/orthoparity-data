from predicate_chain.parser import parse_predicates
from tests.conftest import identity_from

IDS = identity_from({
    "K111111": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
    "K222222": ("Beta Ortho LLC", "BETA PEDICLE SCREW SYSTEM"),
    "K333333": ("Gamma Medical", "GAMMA PLATE"),
    "K444444": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
})


def roles(res):
    return {e.predicate_number: e.role for e in res.edges}


def test_single_predicate_is_primary():
    pages = ["510(k) Summary\nPredicate Device:\nAlpha Interbody System (K111111) - Alpha Spine, Inc.\n"
             "Device Description:\nThe device is a cage."]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K111111": "primary"}
    assert res.edges[0].role_basis == "only predicate listed"


def test_labeled_primary_wins_over_order():
    pages = ["Predicate Devices:\nAdditional predicate: Beta Pedicle Screw System (K222222), Beta Ortho\n"
             "Primary predicate: Alpha Interbody System (K111111), Alpha Spine\n"
             "Device Description: text"]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K222222": "reference", "K111111": "primary"}
    assert res.edges[1].role_basis == "labeled primary in PDF"


def test_none_labeled_first_listed_is_primary():
    pages = ["Legally Marketed Predicate Devices:\nBeta Pedicle Screw System (K222222) Beta Ortho\n"
             "Gamma Plate (K333333) Gamma Medical\nIndications for Use: text"]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K222222": "primary", "K333333": "reference"}
    assert res.edges[0].role_basis == "first listed, none labeled primary"


def test_including_family_inherits_primary():
    pages = ["Predicate Device(s):\nPrimary predicate: Alpha Interbody System (K111111), including K444444, "
             "Alpha Spine, Inc.\nAdditional predicate: Gamma Plate (K333333), Gamma Medical\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    r = {e.predicate_number: (e.role, e.family_of) for e in res.edges}
    assert r["K111111"] == ("primary", None)
    assert r["K444444"] == ("primary", "K111111")
    assert r["K333333"] == ("reference", None)


def test_parenthetical_group_is_family():
    pages = ["Predicate Devices:\nAlpha Interbody System (K111111, K444444) by Alpha Spine\n"
             "Gamma Plate (K333333) by Gamma Medical\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    r = {e.predicate_number: (e.role, e.family_of) for e in res.edges}
    assert r["K444444"] == ("primary", "K111111")
    assert r["K333333"] == ("reference", None)


def test_reference_device_section_is_reference():
    pages = ["Predicate Device:\nAlpha Interbody System (K111111) Alpha Spine\n"
             "Reference Device:\nGamma Plate (K333333) Gamma Medical\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K111111": "primary", "K333333": "reference"}


def test_subject_number_is_not_a_predicate():
    pages = ["510(k) Number: K999999\nPredicate Device:\nAlpha Interbody System (K111111) Alpha Spine\n"
             "Device Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    assert [e.predicate_number for e in res.edges] == ["K111111"]
    assert res.pdf_own_knumber == "K999999"


def test_table_row_trailing_role_word():
    pages = ["Predicate Devices\n510k # Trade Name Manufacturer Product Code Predicate Type\n"
             "K222222 Beta Pedicle Screw System Beta Ortho MAX Additional\n"
             "K111111 Alpha Interbody System Alpha Spine MAX, OVD Primary\nPERFORMANCE DATA\ntext"]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K222222": "reference", "K111111": "primary"}


def test_estar_listed_first_header_is_not_a_label():
    pages = ["Legally Marketed Predicate Devices 21 CFR 807.92(a)(3)\n"
             "Predicate # Predicate Trade Name (Primary Predicate is listed first) Product Code\n"
             "K222222 Beta Pedicle Screw System MAX\nK111111 Alpha Interbody System MAX\n"
             "Device Description Summary 21 CFR 807.92(a)(4)\ntext"]
    res = parse_predicates(pages, "K999999", IDS)
    assert roles(res) == {"K222222": "primary", "K111111": "reference"}
    assert res.edges[0].role_basis == "first listed, none labeled primary"
