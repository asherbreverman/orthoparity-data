from predicate_chain.loaders import read_pipe_file
from predicate_chain.textclean import clean_field, snippet, strip_control_chars


def test_strip_control_chars_keeps_tabs_and_newlines():
    assert strip_control_chars("A\x00B\x07C\tD\nE\x1bF\x7f") == "ABC\tD\nEF"


def test_clean_field_empty_becomes_none():
    assert clean_field("  \x0b ") is None
    assert clean_field(" Acme\x0c Inc. ") == "Acme Inc."


def test_snippet_max_300():
    text = "x" * 1000 + "K123456" + "y" * 1000
    s = snippet(text, 1000, 1007, 300)
    assert len(s) <= 300 and "K123456" in s


def test_pipe_file_control_chars_and_stray_cr(tmp_path):
    p = tmp_path / "f.txt"
    # A stray carriage return and a vertical tab inside a record must not split or corrupt it.
    p.write_bytes(b"KNUMBER|APPLICANT|DEVICENAME\nK000001|Acme\rCorp|Widget\x0b One\nK000002|Beta|Gadget\n")
    header, rows, dirty = read_pipe_file(p)
    assert header == ["KNUMBER", "APPLICANT", "DEVICENAME"]
    assert len(rows) == 2
    assert rows[0][2] == "Widget One"
    assert dirty == 1


def test_shifted_font_text_is_decoded():
    from predicate_chain.pdftext import _clean_page
    plain = ("The device is substantially equivalent to the predicate device (K111111) and the results of "
             "testing show that the strength of the device is sufficient for its intended use. ") * 3
    shifted = "".join(chr(ord(c) - 29) if 32 <= ord(c) <= 122 else c for c in plain)
    text, status = _clean_page(shifted)
    assert status == "decoded" and "K111111" in text and "substantially equivalent" in text


def test_symbol_soup_is_garbled_and_tables_are_not():
    from predicate_chain.pdftext import _clean_page
    soup = "') $)0') +-  *+C%+) &)' %),**0*+$9@F?GD@:4 + &%# ') +* %#,+C)- #' %),**0*+$8+%#&%9@H?GF?:2#&,* " * 3
    assert _clean_page(soup)[1] == "garbled"
    table = "K201234 ABC Interbody MAX OVD Primary\nK073291 CAPSTONE PEEK MAX Additional\n" * 4
    assert _clean_page(table)[1] == "ok"


def test_shifted_font_without_spaces_is_sent_to_ocr():
    from predicate_chain.pdftext import _clean_page
    plain = "Theresultsofthisnonclinicaltestingshowthatthestrengthofthedeviceissufficientforitsintendeduse" * 3
    shifted = "".join(chr(ord(c) - 29) for c in plain)
    text, status = _clean_page(shifted)
    assert status == "decoded_nospace" and text.startswith("Theresults")
