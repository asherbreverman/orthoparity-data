from predicate_chain.parser import parse_predicates
from tests.conftest import identity_from

IDS = identity_from({
    "K111111": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
    "K222222": ("Beta Ortho LLC", "BETA PEDICLE SCREW SYSTEM"),
})


def test_high_confidence_and_clean():
    pages = ["510(k) Summary of K999999\nPredicate Device:\nAlpha Interbody System (K111111), Alpha Spine, Inc.\n"
             "Device Description: cage"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.edges[0].confidence == "HIGH"
    assert res.parse_status == "CLEAN"


def test_high_allowed_without_printed_company():
    pages = ["Predicate Device:\nAlpha Interbody System (K111111)\nDevice Description: cage"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.edges[0].confidence == "HIGH"


def test_mentioned_not_classified_flag_rule_c_and_strict():
    pages = ["Predicate Device:\nAlpha Interbody System (K111111) Alpha Spine\nDevice Description: cage\n"
             "Performance Data: tested per method used for Beta system K222222."]
    res = parse_predicates(pages, "K999999", IDS)  # rule C: anchored by a HIGH labeled predicate
    assert ("mentioned, not classified", "K222222") in {(f.flag_type, f.number) for f in res.flags}
    assert res.parse_status == "CLEAN"
    assert parse_predicates(pages, "K999999", IDS, review_rule="strict").parse_status == "AMBIGUOUS"


def test_mention_in_dead_end_document_stays_ambiguous():
    pages = ["510(k) Summary\nThe device is safe.\nPerformance Data: tested like the Beta system K222222."]
    res = parse_predicates(pages, "K999999", IDS)
    assert not res.edges and res.parse_status == "AMBIGUOUS"


def test_pma_flag_is_informational_under_rule_c():
    pages = ["Predicate Device:\nAlpha Interbody System (K111111) Alpha Spine\nLT-CAGE (P970015)\n"
             "Device Description: x"]
    from predicate_chain.parser import blocking_flags
    res = parse_predicates(pages, "K999999", IDS)
    assert any(f.flag_type == "PMA predicate" for f in res.flags)
    assert not any(f.flag_type == "PMA predicate" for f in blocking_flags(res))


def test_probable_misread_number():
    pages = ["Predicate Device:\nAlpha Interbody System (K111112) Alpha Spine\nDevice Description: cage"]
    res = parse_predicates(pages, "K999999", IDS)
    assert any(f.flag_type == "probable misread number" for f in res.flags)
    assert res.edges[0].confidence == "MEDIUM"


def test_name_mismatch_flag_and_low():
    pages = ["Predicate Device:\nCompletely Different Hip Stem (K222222) Zeta Corp\nDevice Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.edges[0].confidence == "LOW"
    assert any(f.flag_type == "name mismatch" for f in res.flags)


def test_wrong_file_flag():
    pages = ["Re: K555555\nDear Sir:\n510(k) Summary\nPredicate Device:\nAlpha Interbody System (K111111)\n"
             "Device Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.pdf_own_knumber == "K555555"
    assert any(f.flag_type == "wrong file" for f in res.flags)


def test_unnumbered_predicate_edge():
    pages = ["Predicate Device:\nThe Smith hip prosthesis, a preamendment device marketed before 1976.\n"
             "Device Description: x"]
    res = parse_predicates(pages, "K999999", IDS)
    assert len(res.edges) == 1
    assert res.edges[0].predicate_number is None
    assert res.edges[0].confidence == "LOW"


def test_fallback_without_labeled_section():
    pages = ["The device is substantially equivalent to the Alpha Interbody System (K111111) by Alpha Spine."]
    res = parse_predicates(pages, "K999999", IDS)
    assert [e.predicate_number for e in res.edges] == ["K111111"]
    assert res.edges[0].in_predicate_section in (0, 1)


def test_long_fda_name_segments_and_squashed_company():
    ids = identity_from({"K203714": ("Nu Vasive, Incorporated",
                                     "NuVasive Thoracolumbar Interbody Systems: NuVasive CoRoent Thoracolumbar System, "
                                     "NuVasive CoRoent XL Interfixated System")})
    pages = ["Predicate Devices\nK203714 NuVasive CoRoent Thoracolumbar System NuVasive MAX Additional\n"
             "Performance Data\ntext"]
    res = parse_predicates(pages, "K999999", ids)
    assert res.edges[0].company_match == 1
    assert res.edges[0].confidence == "HIGH"


# ---- patterns seen in scanned 1990s summaries (synthetic text) -------------------------
def test_ocr_bullet_heading():
    pages = ["Trade Name: Widget\n. Predicate Devices:\n* Alpha Interbody System, K111111\n\nDevice Description:\nx"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.used_tier == 1 and [e.predicate_number for e in res.edges] == ["K111111"]


def test_fda_letter_boilerplate_is_not_a_predicate_section():
    letter = ("Dear Ms. Smith:\nWe have reviewed your Section 510(k) notification.\n"
              "legally marketed predicate device results in a classification for your device.\nK222222")
    summary = "510(k) Summary\nThe device is safe.\n"
    res = parse_predicates([summary, letter], "K999999", IDS)
    assert res.edges == []


def test_numbers_in_substantial_equivalence_sentence():
    pages = ["The substantial equivalence of the Cup is based on design to Alpha's Alpha Interbody System\n"
             "(K111111) and Beta's Beta Pedicle Screw System (K222222).\n"]
    res = parse_predicates(pages, "K999999", IDS)
    assert [(e.predicate_number, e.role, e.confidence) for e in res.edges] == [
        ("K111111", "primary", "HIGH"), ("K222222", "reference", "HIGH")]


def test_numbers_listed_under_one_named_device_are_family():
    pages = ["Substantially Equivalent Devices(s);\n1. Alpha Interbody System\nAlpha Spine\nK111111, K444444,\n"
             "2. Beta Pedicle Screw System\nBeta Ortho\nK222222\nDevice Description:\nx"]
    ids = identity_from({"K111111": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
                         "K444444": ("Alpha Spine, Inc.", "ALPHA INTERBODY SYSTEM"),
                         "K222222": ("Beta Ortho LLC", "BETA PEDICLE SCREW SYSTEM")})
    res = parse_predicates(pages, "K999999", ids)
    r = {e.predicate_number: (e.role, e.family_of) for e in res.edges}
    assert r == {"K111111": ("primary", None), "K444444": ("primary", "K111111"), "K222222": ("reference", None)}


def test_bare_number_list_is_not_family():
    pages = ["Predicate Devices:\nK111111, K222222\nDevice Description:\nx"]
    res = parse_predicates(pages, "K999999", IDS)
    assert [(e.predicate_number, e.family_of) for e in res.edges] == [("K111111", None), ("K222222", None)]


def test_named_predicate_without_number_in_sentence():
    pages = ["510(k) Summary\nThe Hip Stem is substantially equivalent to the OMNIFIT Femoral Stem (Osteonics Corp.) "
             "and the PFC Total Hip System (Johnson & Johnson).\n"]
    res = parse_predicates(pages, "K999999", IDS)
    assert len(res.edges) == 1 and res.edges[0].predicate_number is None


def test_generic_equivalence_claim_is_not_a_predicate():
    pages = ["The System was declared to be substantially equivalent to other commercially available devices.\n"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.edges == []


def test_wrapped_lowercase_line_is_not_a_heading():
    pages = ["Predicate Devices:\nAlpha Interbody System (K111111)\n"
             "indications and contraindications to the Beta system are the same as the predicate\n"]
    res = parse_predicates(pages, "K999999", IDS)
    assert res.edges[0].predicate_number == "K111111"


def test_wrong_file_ignores_predicate_table_number_column():
    pages = ["Re: KI 11572\nDear Mr. Webb:\n",
             "Substantial equivalence claimed to predicate devices\nThe Cup is substantially equivalent to the "
             "Alpha Interbody System (K111111).\n510(k) number K 111111\n"]
    res = parse_predicates(pages, "K111572", IDS)
    assert res.pdf_own_knumber == "K111572"
    assert not any(f.flag_type == "wrong file" for f in res.flags)


def test_wrong_file_detected_from_re_line():
    pages = ["Re: K070278\nTrade Name: Other\nDear Sir:\n", "Predicate Device:\nAlpha Interbody System (K111111)\n"]
    res = parse_predicates(pages, "K111572", IDS)
    assert res.pdf_own_knumber == "K070278"
    assert any(f.flag_type == "wrong file" for f in res.flags)


def test_column_header_under_predicate_heading_does_not_end_section():
    pages = ["Predicate Devices\nIntended Use/Design/Technology/Operation\n* Alpha Interbody System (Alpha; K111111)\n"
             "Material\nx"]
    res = parse_predicates(pages, "K999999", IDS)
    assert [e.predicate_number for e in res.edges] == ["K111111"] and res.used_tier == 1


def test_equivalent_device_identification_and_pipe_bullet():
    for head in ("Equivalent Device Identification:", "| Legally Marketed Predicate Devices 21 CFR 807.92(a)(3)",
                 "Legally marketed device(s) to which Alpha Interbody System"):
        pages = [f"{head}\nAlpha Interbody System, K111111\nDevice Description:\nx"]
        res = parse_predicates(pages, "K999999", IDS)
        assert res.used_tier == 1, head


def test_reference_device_after_number_on_same_row():
    pages = ["Predicate Devices:\nK111111 Alpha Interbody System | MAX\nK222222 Beta Pedicle Screw System "
             "(reference device) | HRS\nDevice Description Summary\nx"]
    res = parse_predicates(pages, "K999999", IDS)
    assert {e.predicate_number: e.role for e in res.edges} == {"K111111": "primary", "K222222": "reference"}
