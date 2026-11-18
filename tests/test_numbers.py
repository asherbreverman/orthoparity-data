from predicate_chain.numbers import find_numbers, normalize_knumber, number_kind, pdf_folder_candidates


def nums(text):
    return [n.number for n in find_numbers(text)]


def test_plain_k_number():
    assert nums("Predicate: K123456 (ABC Spine)") == ["K123456"]


def test_k_number_with_space_or_hyphen():
    assert nums("K 123456 and K-654321") == ["K123456", "K654321"]


def test_ocr_confusions_are_normalized_and_marked():
    found = find_numbers("cleared under Kl23O56")
    assert [f.number for f in found] == ["K123056"]
    assert found[0].normalized is True


def test_too_many_letters_rejected():
    assert nums("KIOOOOO") == []


def test_wrong_lengths_rejected():
    assert nums("K12345 and K1234567 and K123456X") == []


def test_k_inside_word_rejected():
    assert nums("SKK123456 PK123456") == []


def test_den_number():
    assert nums("De Novo DEN150034 granted") == ["DEN150034"]


def test_pma_with_supplement():
    found = find_numbers("PMA P970051/S020 and P030054")
    assert [f.number for f in found] == ["P970051/S020", "P030054"]
    assert found[0].base == "P970051"


def test_reading_order_across_kinds():
    assert nums("P123456 then K234567 then DEN345678") == ["P123456", "K234567", "DEN345678"]


def test_kind_and_normalize():
    assert number_kind("DEN000001") == "DEN"
    assert number_kind("K241487") == "K"
    assert number_kind("P970051/S020") == "P"
    assert normalize_knumber(" k-241487 ") == "K241487"


def test_pdf_folder_candidates():
    assert pdf_folder_candidates("K241487")[0] == "pdf24"
    assert pdf_folder_candidates("K051234")[0] == "pdf5"
    assert pdf_folder_candidates("K981234") == ["pdf"]
    assert pdf_folder_candidates("K011234") == ["pdf"]


def test_ocr_split_number_and_paren():
    found = find_numbers("Synthes; K9335 18) and (Fixion; K(002783, K013449)")
    assert [f.number for f in found] == ["K933518", "K002783", "K013449"]
    assert found[0].normalized is True


def test_two_spaces_rejected():
    assert nums("K 12 34 56") == []
