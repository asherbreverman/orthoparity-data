"""Review rule D (common-sense rules set 2026-11-17). Synthetic text only."""
from predicate_chain.parser import parse_predicates
from tests.conftest import identity_from

IDS = identity_from({
    "K111111": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
    "K222222": ("Beta Ortho LLC", "BETA PEDICLE SCREW SYSTEM"),
})


def test_rule_3_mentioned_number_becomes_predicate():
    pages = ["Predicate Device:\nAlpha Interbody System (K111111) Alpha Spine\nDevice Description: cage\n"
             "Performance Data: tested per method used for Beta system K222222."]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    nums = {e.predicate_number: e for e in res.edges}
    assert set(nums) == {"K111111", "K222222"}
    assert nums["K111111"].role == "primary" and nums["K111111"].confidence == "HIGH"
    assert nums["K222222"].role == "reference" and nums["K222222"].confidence == "MEDIUM"
    assert "rule D" in nums["K222222"].role_basis
    assert res.parse_status == "CLEAN"


def test_rule_3_mention_in_dead_end_document_is_primary():
    pages = ["510(k) Summary\nThe device is safe.\nPerformance Data: tested like the Beta system K222222."]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    assert [e.predicate_number for e in res.edges] == ["K222222"]
    assert res.edges[0].role == "primary"
    assert res.parse_status == "CLEAN"


def test_rule_3_skips_own_number_and_one_character_slip():
    pages = ["510(k) Summary K999999\nPage header K999998\nPredicate Device:\nAlpha Interbody System (K111111)\n"
             "Device Description: cage"]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    assert [e.predicate_number for e in res.edges] == ["K111111"]


def test_rule_2_name_mismatch_defers_to_number():
    pages = ["Predicate Device:\nCompletely Different Hip Stem (K222222) Zeta Corp\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    assert res.edges[0].confidence == "HIGH"
    assert res.parse_status == "CLEAN"


def test_rule_2_ocr_read_number_with_no_match_goes_to_review():
    pages = ["Predicate Device:\nCompletely Different Hip Stem (K222222) Zeta Corp\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D", machine_read_pages={1})
    assert res.edges[0].confidence == "LOW"
    assert any(f.flag_type == "possible OCR misread" for f in res.flags)
    assert res.parse_status == "AMBIGUOUS"


def test_rule_1_name_only_predicate_is_ignored():
    pages = ["510(k) Summary\nPredicate Device:\nThe Gamma Bone Plate made by Gamma Corp.\nDevice Description: plate"]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    assert all(e.predicate_number is None for e in res.edges)
    assert all(e.confidence == "NO NUMBER" for e in res.edges)
    assert res.parse_status == "CLEAN"


def test_rule_d_keeps_misread_numbers_in_review():
    pages = ["Predicate Device:\nAlpha Interbody System (K111112) Alpha Spine\nDevice Description: cage"]
    res = parse_predicates(pages, "K999999", IDS, review_rule="D")
    assert any(f.flag_type == "probable misread number" for f in res.flags)
    assert res.parse_status == "AMBIGUOUS"


IDS2 = identity_from({
    "K999999": ("Alpha Spine, Inc.", "ALPHA NEW CAGE"),
    "K111111": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
    "K222222": ("Beta Ortho LLC", "BETA PEDICLE SCREW SYSTEM"),
})


def test_rule_d_ocr_number_accepted_when_same_company_as_subject():
    pages = ["Predicate Device:\nThe earlier mesh cage (K111111)\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS2, review_rule="D", machine_read_pages={1})
    assert res.edges[0].confidence == "HIGH"
    assert res.parse_status == "CLEAN"


def test_rule_d_own_number_slip_is_dropped():
    pages = ["K 988999 510(k) Summary\nPredicate Device:\nAlpha Interbody System (K111111)\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS2, review_rule="D", machine_read_pages={1})
    assert [e.predicate_number for e in res.edges] == ["K111111"]
    assert any(f.flag_type == "own number misread" for f in res.flags)
    assert res.parse_status == "CLEAN"

