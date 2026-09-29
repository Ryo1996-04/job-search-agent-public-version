"""Page-count and fill check for a rendered resume PDF.

A one-page cap alone let a resume shrink to ~0.75 of a page unnoticed.
This measures how far down the last page the text reaches and warns when the page is
under-filled.

    python -m resume_gate.pdf_fill <resume.pdf> [--max-pages 1] [--min-fill 0.9] [--margin-in 0.5]

Exit 1 on too many pages or an unreadable PDF; an under-filled page is a warning (exit 0).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

POINTS_PER_INCH = 72.0


@dataclass
class FillReport:
    pages: int
    page_height: float
    lowest_text_y: float
    margin: float

    @property
    def usable_height(self) -> float:
        return self.page_height - 2 * self.margin

    @property
    def fill(self) -> float:
        used = self.page_height - self.margin - self.lowest_text_y
        return max(0.0, min(1.0, used / self.usable_height))

    @property
    def blank_inches(self) -> float:
        return max(0.0, self.lowest_text_y - self.margin) / POINTS_PER_INCH


def measure(pdf_path: Path, margin_in: float = 0.5) -> FillReport:
    reader = PdfReader(str(pdf_path))
    page = reader.pages[-1]
    ys: list[float] = []

    def visit(text, cm, tm, _font, _size):
        if text.strip():
            # y of the text origin in page space: text matrix combined with the CTM
            ys.append(tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

    page.extract_text(visitor_text=visit)
    if not ys:
        raise ValueError(f"no text found on the last page of {pdf_path}")
    return FillReport(
        pages=len(reader.pages),
        page_height=float(page.mediabox.height),
        lowest_text_y=min(ys),
        margin=margin_in * POINTS_PER_INCH,
    )


def check(report: FillReport, max_pages: int = 1, min_fill: float = 0.9) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if report.pages > max_pages:
        errors.append(f"{report.pages} pages; the limit is {max_pages}.")
    if report.fill < min_fill:
        warnings.append(
            f"last page is {report.fill:.1%} full ({report.blank_inches:.1f} in blank at the "
            f"bottom); target is at least {min_fill:.0%}. Room for more evidence-backed bullets."
        )
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="resume_gate.pdf_fill", description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--min-fill", type=float, default=0.9)
    ap.add_argument("--margin-in", type=float, default=0.5, help="page margin in inches (top and bottom)")
    args = ap.parse_args(argv)

    try:
        report = measure(args.pdf, args.margin_in)
    except Exception as exc:  # unreadable PDF is a failed check, not a pass
        print(f"pdf_fill: ERROR {exc}")
        return 1
    errors, warnings = check(report, args.max_pages, args.min_fill)

    print(f"pdf_fill — {args.pdf.name}")
    print(f"  pages {report.pages} · last page {report.fill:.1%} full · {report.blank_inches:.1f} in blank")
    for e in errors:
        print(f"  ERROR   {e}")
    for w in warnings:
        print(f"  WARNING {w}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s). {'FAIL' if errors else 'OK'}.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
