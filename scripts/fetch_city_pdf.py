"""Download PDFs from city labour-inspection sites.

Unlike the OSHA crawler, these listings link the files directly, so there is no
detail page to visit. Start pages are crawled for sibling categories too.
"""

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

START_PAGES = {
    "臺北市勞檢處": "https://lio.gov.taipei/News.aspx?n=DE40B914B9E03BE2&sms=AB3745AD59DE09F4",
}
OUT = pathlib.Path("data/pdf")
MANIFEST = OUT / "manifest.json"
PAGE_SIZE = 200

CATEGORY_RE = re.compile(r"News\.aspx\?n=[A-F0-9]+&amp;sms=[A-F0-9]+")
FILE_RE = re.compile(r'href="(https?://[^"]*(?:Download\.ashx\?[^"]+|\.pdf))"')
FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)")


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def categories(start: str) -> list[str]:
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(start))
    page = get(start)
    found = {f"{origin}/{c.replace('&amp;', '&')}" for c in CATEGORY_RE.findall(page)}
    return sorted(found | {start})


def download(url: str, section: str, manifest: dict) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=180) as resp:
        disposition = resp.headers.get("Content-Disposition", "")
        match = FILENAME_RE.search(disposition)
        raw_name = urllib.parse.unquote(match.group(1)) if match else pathlib.Path(url).name
        name = re.sub(r"[^\w.\-]", "_", raw_name)
        if not name.lower().endswith(".pdf"):
            return

        target = OUT / name
        if target.exists():
            return
        target.write_bytes(resp.read())

    manifest[name] = {"title": pathlib.Path(raw_name).stem, "section": section, "source_url": url}
    print(f"  {name} ({target.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}

    for site, start in START_PAGES.items():
        for category in categories(start):
            page = get(f"{category}&page=1&PageSize={PAGE_SIZE}")
            links = sorted(set(FILE_RE.findall(page)))
            if links:
                print(f"{site} {category.split('n=')[1][:8]}: {len(links)} files")

            for link in links:
                try:
                    download(link.replace("&amp;", "&"), site, manifest)
                except Exception as exc:
                    print(f"  skip: {type(exc).__name__}")
                time.sleep(0.5)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} files in manifest")


if __name__ == "__main__":
    main()
