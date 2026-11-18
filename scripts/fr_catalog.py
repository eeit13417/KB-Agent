"""Download the Federal Register catalog (metadata only) for the agencies we cover.

The catalog drives selection: fetch_fr.py later reads it and downloads full text
only for the documents we keep, so the selection rules can change without
re-querying the API.
"""

import json
import pathlib
import time
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://www.federalregister.gov/api/v1/documents.json"
AGENCIES = ["wage-and-hour-division", "occupational-safety-and-health-administration"]
TYPES = ["RULE", "PRORULE", "NOTICE"]
FIELDS = [
    "document_number", "title", "type", "publication_date", "page_length",
    "pdf_url", "full_text_xml_url", "html_url", "cfr_references",
]
OUT = pathlib.Path("data/raw/fr")
HEADERS = {"User-Agent": "kb-agent/0.2"}
CHARS_PER_PAGE = 7500  # rough density of a three-column Federal Register page


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.loads(resp.read())


def list_documents(agency: str, doc_type: str) -> list[dict]:
    params = [
        ("conditions[agencies][]", agency),
        ("conditions[type][]", doc_type),
        ("per_page", "1000"),
        ("order", "oldest"),
    ] + [("fields[]", field) for field in FIELDS]
    url = f"{API}?{urllib.parse.urlencode(params)}"
    docs: list[dict] = []
    while url:
        page = get_json(url)
        docs.extend(page.get("results", []))
        url = page.get("next_page_url")
        time.sleep(0.5)  # be polite to a free public API
    return docs


def main() -> None:
    catalog: list[dict] = []
    for agency in AGENCIES:
        for doc_type in TYPES:
            docs = list_documents(agency, doc_type)
            for doc in docs:
                doc["agency"] = agency
            catalog.extend(docs)
            pages = sum(doc.get("page_length") or 0 for doc in docs)
            print(f"{agency:<48} {doc_type:<8} {len(docs):>5} docs {pages:>7} pages")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"wrote {len(catalog)} entries to {OUT / 'catalog.json'}")

    # Page-length spread per agency and type, to choose a size cap with real numbers.
    buckets = [(1, 5), (6, 20), (21, 50), (51, 100), (101, 10_000)]
    spread: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(buckets))
    for doc in catalog:
        length = doc.get("page_length") or 0
        for i, (low, high) in enumerate(buckets):
            if low <= length <= high:
                spread[(doc["agency"][:20], doc["type"])][i] += 1
    print("\npages:", "  ".join(f"{low}-{high if high < 10_000 else '+'}" for low, high in buckets))
    for key, counts in sorted(spread.items()):
        print(f"{key[0]:<20} {key[1]:<15}", "  ".join(f"{c:>5}" for c in counts))


if __name__ == "__main__":
    main()
