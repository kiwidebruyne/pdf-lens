#!/usr/bin/env python3
"""Minimal end-to-end validation for a staged PDF Lens runtime."""
import sys
import tempfile
from pathlib import Path

import pymupdf
from playwright.sync_api import sync_playwright


def main() -> int:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "PDF Lens setup smoke test")
    with tempfile.TemporaryDirectory() as temp:
        pdf = Path(temp) / "smoke.pdf"
        doc.save(pdf)
        doc.close()
        with pymupdf.open(pdf) as opened:
            if opened.page_count != 1 or "PDF Lens" not in opened[0].get_text():
                raise RuntimeError("PyMuPDF could not read the smoke-test PDF")
            rendered_svg = opened[0].get_svg_image()
            if "<svg" not in rendered_svg or "<path" not in rendered_svg or not rendered_svg.strip().endswith("</svg>"):
                raise RuntimeError("PyMuPDF could not render the smoke-test page to SVG")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()
    print("PDF Lens runtime smoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PDF Lens runtime smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
