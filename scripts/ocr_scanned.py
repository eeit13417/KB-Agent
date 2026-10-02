"""OCR the scanned PDFs once and cache the result next to them.

RapidOCR's model is trained on Simplified Chinese, so the text is converted with
OpenCC afterwards. That fixes character-form errors, not genuine misreads.
"""

import json
import pathlib
import time

import pymupdf
from opencc import OpenCC
from rapidocr_onnxruntime import RapidOCR

PDF_DIR = pathlib.Path("data/pdf")
CACHE_DIR = PDF_DIR / "ocr"
INSPECTION = PDF_DIR / "inspection.json"
DPI = 200
MIN_CONFIDENCE = 0.5


def page_text(ocr: RapidOCR, cc: OpenCC, page: pymupdf.Page) -> str:
    pix = page.get_pixmap(dpi=DPI)
    result, _ = ocr(pix.tobytes("png"))
    if not result:
        return ""

    boxes = [
        (min(p[0] for p in box), min(p[1] for p in box), text)
        for box, text, score in result
        if score >= MIN_CONFIDENCE
    ]

    # These books are scanned two printed pages per sheet, so on a landscape sheet
    # everything on the left half must be read before anything on the right.
    if pix.width > pix.height:
        middle = pix.width / 2
        halves = [[b for b in boxes if b[0] < middle], [b for b in boxes if b[0] >= middle]]
    else:
        halves = [boxes]

    lines: list[str] = []
    for half in halves:
        lines += [text for _, _, text in sorted(half, key=lambda b: (b[1], b[0]))]

    return cc.convert("\n".join(lines))


def main() -> None:
    inspection = json.loads(INSPECTION.read_text(encoding="utf-8"))
    targets = sorted(name for name, entry in inspection.items() if entry["kind"] == "scanned")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ocr = RapidOCR()
    cc = OpenCC("s2twp")

    for name in targets:
        cache = CACHE_DIR / f"{name}.json"
        if cache.exists():
            print(f"skip {name} (cached)")
            continue

        started = time.perf_counter()
        with pymupdf.open(PDF_DIR / name) as doc:
            pages = [page_text(ocr, cc, page) for page in doc]

        cache.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
        chars = sum(len(p) for p in pages)
        print(f"{name}: {len(pages)} pages, {chars} chars, {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
