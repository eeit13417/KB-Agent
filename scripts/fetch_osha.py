"""Crawl government publication sections and download their attachments.

Works on any Umbraco-based agency site (osha.gov.tw, ilosh.gov.tw, ...): a section
lists detail pages, and each detail page links files under /media/.
Formats are mixed (pdf, doc, odt) and many PDFs are scans, which is the point.
"""

import html
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

SECTIONS = {
    "宣導摺頁": "https://www.osha.gov.tw/48110/48461/48517/48539/48543/",
    "宣導海報": "https://www.osha.gov.tw/48110/48461/48517/48539/48545/",
    "宣導手冊": "https://www.osha.gov.tw/48110/48461/48517/48539/48547/",
    "宣導其他": "https://www.osha.gov.tw/48110/48461/48517/48539/48549/",
    "訓練教材": "https://www.osha.gov.tw/48110/48461/48517/48539/48551/",
}
OUT = pathlib.Path("data/pdf")
MANIFEST = OUT / "manifest.json"
WANTED = (".pdf", ".doc", ".docx", ".odt")

DETAIL_RE = re.compile(r'href="(/\d+(?:/\d+)+/post)"')
MEDIA_RE = re.compile(r'href="(/media/[^"?]+)"')
TITLE_RE = re.compile(r"<title>([^<]*)</title>")


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def detail_urls(section_url: str) -> list[str]:
    urls: list[str] = []
    for page in range(1, 50):
        found = sorted(set(DETAIL_RE.findall(get(f"{section_url}?page={page}"))))
        if not found:
            break
        urls.extend(found)
        time.sleep(0.5)
    return sorted(set(urls))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}

    for name, section_url in SECTIONS.items():
        origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(section_url))
        details = detail_urls(section_url)
        print(f"{name}: {len(details)} detail pages")

        for detail in details:
            page = get(origin + detail)
            title = html.unescape(TITLE_RE.search(page).group(1)).split("-")[0].strip()

            for media in sorted(set(MEDIA_RE.findall(page))):
                decoded = urllib.parse.unquote(media)
                if not decoded.lower().endswith(WANTED):
                    continue

                filename = re.sub(r"[^\w.\-]", "_", pathlib.Path(decoded).name)
                target = OUT / filename
                if target.exists():
                    continue

                url = origin + urllib.parse.quote(urllib.parse.unquote(media), safe="/")

                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(request, timeout=120) as resp:
                        target.write_bytes(resp.read())
                except Exception as exc:
                    print(f"  skip {filename}: {type(exc).__name__}")
                    continue

                manifest[filename] = {"title": title, "section": name, "source_url": url}
                print(f"  {filename} ({target.stat().st_size / 1e6:.1f} MB)")
                time.sleep(0.5)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} files in {OUT}")


if __name__ == "__main__":
    main()
