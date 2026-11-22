"""load_approvals.py: supplement categories, indications text and record building. Synthetic fixtures only, no network."""
from pipeline import load_approvals as L


def test_categories():
    assert L.category("Panel Track", "Change Design/Components/Specifications/Material") == "new indication"
    assert L.category("180-Day", "Change Design/Components/Specifications/Material") == "design change"
    assert L.category("Special (Immediate Track)", "Labeling Change - Indications/instructions/shelf life/tradename") == "labeling change"
    assert L.category("normal 75 day track", "postapproval study protocol") == "post-approval study"
    assert L.category("30-Day Notice", "") == "manufacturing change"
    assert L.category("Real-Time Process", "Process Change - Manufacturer/Sterilizer/Packager/Supplier") == "manufacturing change"
    assert L.category("normal 75 day track", "location change - manufacturer/sterilizer/packager/supplier") == "site change"
    assert L.category("normal 75 day track", "request for adn") == "other"


def test_pathway():
    assert L.pathway("H190005") == "HDE"
    assert L.pathway("P940015") == "PMA"
    assert L.pathway("N17113") == "PMA"


def test_indications_text_drops_only_the_opening_approval_sentence():
    assert L.indications_text("APPROVAL FOR ACME GEL. THIS DEVICE IS INDICATED FOR KNEE PAIN.") == "This device is indicated for knee pain."
    # no indications sentence after it: FDA's wording is kept
    assert L.indications_text("Approval for a manufacturing site in Ohio.") == "Approval for a manufacturing site in Ohio."
    assert L.indications_text("The device is intended to treat X.") == "The device is intended to treat X."


def test_approvals_from_sources_pma_and_hde():
    pma = [
        {"pma_number": "P000001", "trade_name": "Acme Gel", "applicant": "Acme, Inc.", "product_code": "MOZ",
         "decision_date": "2001-01-24", "date_received": "2000-01-01", "decision_code": "APPR",
         "ao_statement": "Approval for Acme Gel. The device is indicated for knee pain."},
        {"pma_number": "P000001", "supplement_number": "S001", "supplement_type": "Panel Track",
         "supplement_reason": "Labeling Change - Indications/instructions/shelf life/tradename",
         "decision_date": "2010-05-01", "product_code": "MOZ", "ao_statement": "New indication for the hip."},
        {"pma_number": "P000001", "supplement_number": "S002", "supplement_type": "30-Day Notice",
         "supplement_reason": "Process Change - Manufacturer/Sterilizer/Packager/Supplier",
         "decision_date": "2012-05-01", "product_code": "MOZ", "ao_statement": "New supplier."},
        # supplements only: no original on file
        {"pma_number": "P000002", "supplement_number": "S004", "supplement_type": "180-Day",
         "supplement_reason": "Change Design/Components/Specifications/Material", "decision_date": "2015-01-01",
         "product_code": "LOF", "trade_name": "Stim"},
    ]
    hde = [
        {"id": "1", "HDE Number": "H000001", "Trade Name": "Rare Implant", "Generic Name": "implant", "applicant": "Small Co",
         "Date Received": "01/02/2020", "Decision Date": "06/30/2020", "Product Code": "QNN[ Registered Establishments with QNN ]",
         "Supplement Type": "hde original", "Expedited Review Granted?": "No",
         "ao": "Approval for the rare implant. This device is indicated for a rare condition."},
        {"id": "2", "HDE Number": "H000001", "Supplement Number": "S001", "Trade Name": "Rare Implant",
         "Decision Date": "01/15/2021", "Product Code": "QNN", "Supplement Type": "normal 75 day track",
         "Supplement Reason": "postapproval study protocol", "ao": "Approval of the study protocol."},
    ]
    apps, sups = L.approvals_from_sources(pma, hde)
    assert set(apps) == {"P000001", "P000002", "H000001"}
    p = apps["P000001"]
    assert p["pathway"] == "PMA" and p["original_on_file"] and p["indications"] == "The device is indicated for knee pain."
    assert not apps["P000002"]["original_on_file"] and apps["P000002"]["decision_date"] == ""
    h = apps["H000001"]
    assert h["pathway"] == "HDE" and h["product_code"] == "QNN" and h["decision_date"] == "2020-06-30"
    assert h["indications"] == "This device is indicated for a rare condition."
    by = {(s["number"], s["supplement_number"]): s for s in sups}
    assert by[("P000001", "S001")]["category"] == "new indication" and by[("P000001", "S001")]["shown"]
    assert by[("P000001", "S002")]["category"] == "manufacturing change" and not by[("P000001", "S002")]["shown"]
    assert by[("H000001", "S001")]["category"] == "post-approval study" and by[("H000001", "S001")]["decision_date"] == "2021-01-15"


def test_fix_caps_sentence_cases_all_caps_only():
    t = L.fix_caps("APPROVAL FOR A CHANGE TO THE CLEAR PLASTIC RIGID TIP CAP (PRTC) OF SYNVISC ON JANUARY 27, 1994; THE PRTC IS BLUE.",
                   ("SYNVISC ONE", "Sanofi Genzyme Corp."))
    assert t == "Approval for a change to the clear plastic rigid tip cap (PRTC) of Synvisc on January 27, 1994; the PRTC is blue."
    # mixed-case text is FDA's own wording and stays as is
    assert L.fix_caps("The device is indicated for OA of the knee.") == "The device is indicated for OA of the knee."


def test_clean_fixes_windows_1252_and_soft_hyphens():
    assert L.clean("Infuse\x99 Bone Graft") == "Infuse™ Bone Graft"
    assert L.clean("DIAM­ Spinal") == "DIAM Spinal"


def test_same_company_for_registered_sites():
    assert L.same_company("genzyme", ["sanofigenzyme"])
    assert L.same_company("restor3d", ["restor3d"])
    assert not L.same_company("neomedico", ["sanofigenzyme"])
    assert not L.same_company("abc", ["abcd"])
