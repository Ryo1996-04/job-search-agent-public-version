"""Tests for resume_gate.pdf_fill, on PDFs built here with text at known heights."""
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from resume_gate.pdf_fill import check, main, measure


def make_pdf(path: Path, pages: list[list[float]]) -> Path:
    """One Letter page per entry; each float is the y (points) of a text line."""
    w = PdfWriter()
    font = w._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for ys in pages:
        page = w.add_blank_page(612, 792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data("".join(f"BT /F1 11 Tf 72 {y} Td (line) Tj ET\n" for y in ys).encode())
        page[NameObject("/Contents")] = w._add_object(stream)
    w.write(str(path))
    return path


def test_full_page_passes(tmp_path):
    r = measure(make_pdf(tmp_path / "full.pdf", [[744, 400, 50]]))
    assert r.pages == 1 and r.lowest_text_y == 50
    assert check(r) == ([], [])


def test_short_page_warns(tmp_path):
    # a real resume that shrank: last line at y=186 -> ~79% full, ~2 in blank
    r = measure(make_pdf(tmp_path / "short.pdf", [[744, 186]]))
    errors, warnings = check(r)
    assert errors == []
    assert len(warnings) == 1 and "79.2% full" in warnings[0]
    assert round(r.blank_inches, 1) == 2.1


def test_two_pages_is_an_error(tmp_path):
    pdf = make_pdf(tmp_path / "two.pdf", [[744, 50], [744, 600]])
    errors, _ = check(measure(pdf))
    assert errors == ["2 pages; the limit is 1."]
    assert main([str(pdf)]) == 1


def test_warning_does_not_fail_the_run(tmp_path):
    assert main([str(make_pdf(tmp_path / "short.pdf", [[744, 186]]))]) == 0


def test_blank_pdf_fails_instead_of_passing(tmp_path):
    assert main([str(make_pdf(tmp_path / "blank.pdf", [[]]))]) == 1
