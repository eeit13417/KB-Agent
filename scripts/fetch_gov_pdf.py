"""Sweep government sites for PDFs, starting from a few seed pages.

Earlier crawlers needed the exact listing page for each category. This one walks
links within the seed's own path prefix instead, so new sections are found on
their own. Limits keep it polite: same host, bounded depth, capped page count.
"""

import collections
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

# Seeds must be pages that actually list things: the bare section roots of these
# sites return an empty shell with no links at all.
SEEDS = {
    "職安署": "https://www.osha.gov.tw/48110/48461/48517/48539/48547/",
    "勞動部": "https://www.mol.gov.tw/1607/28162/28166/",
    "勞動部主題": "https://www.mol.gov.tw/topic/6035/6076/45792/",
    "臺北市勞檢處": "https://lio.gov.taipei/News.aspx?n=DE40B914B9E03BE2&sms=AB3745AD59DE09F4",
    "高雄市勞檢處": "https://klsio.kcg.gov.tw/News.aspx?n=D9769F41F3C6A1C7&sms=275D4AA031F91871",
    "新北市勞檢處": "https://ilabor.ntpc.gov.tw/",
    "高雄市勞工局": "https://labor.kcg.gov.tw/",

}
OUT = pathlib.Path("data/pdf")
MANIFEST = OUT / "manifest.json"
MAX_PAGES = 400
MAX_DEPTH = 3
DELAY = 0.4

LINK_RE = re.compile(r'href="([^"#]+)"')
ASSET_RE = re.compile(r"\.(css|js|png|jpe?g|gif|ico|svg|woff2?|ttf|zip|mp4)(\?|$)", re.I)
FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)")


def fetch(url: str, timeout: int = 60) -> urllib.request.addinfourl:
    # URLs may contain Chinese characters, which urllib refuses to send. Encode only
    # the non-ASCII parts; "%" stays safe so already-encoded links are left alone.
    safe_url = urllib.parse.quote(url, safe="/:?=&%#+~!$'()*,;@[]")
    request = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(request, timeout=timeout)


def is_pdf_link(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "download.ashx" in lowered


def save(url: str, section: str, manifest: dict) -> bool:
    with fetch(url, timeout=180) as resp:
        if "pdf" not in resp.headers.get("Content-Type", "").lower():
            return False

        match = FILENAME_RE.search(resp.headers.get("Content-Disposition", ""))
        raw = urllib.parse.unquote(match.group(1) if match else pathlib.Path(url).name)
        name = re.sub(r"[^\w.\-]", "_", raw)
        if not name.lower().endswith(".pdf"):
            name += ".pdf"

        target = OUT / name
        if target.exists():
            return False
        target.write_bytes(resp.read())

    manifest[name] = {"title": pathlib.Path(raw).stem, "section": section, "source_url": url}
    print(f"    {name} ({target.stat().st_size / 1e6:.1f} MB)")
    return True


def crawl(section: str, seed: str, manifest: dict) -> None:
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(seed))
    # Directory of the seed, so a seed like /News.aspx?... opens up the whole site
    # while /48110/.../48547/ stays inside the publications area.
    prefix = urllib.parse.urlsplit(seed).path.rsplit("/", 1)[0] + "/"

    queue = collections.deque([(seed, 0)])
    seen_pages = {seed}
    seen_files: set[str] = set()
    pages = 0

    while queue and pages < MAX_PAGES:
        url, depth = queue.popleft()
        try:
            with fetch(url) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        pages += 1
        time.sleep(DELAY)

        for href in LINK_RE.findall(html):
            absolute = urllib.parse.urljoin(url, href.replace("&amp;", "&"))
            if not absolute.startswith(origin):
                continue

            if is_pdf_link(absolute):
                if absolute in seen_files:
                    continue
                seen_files.add(absolute)
                try:
                    save(absolute, section, manifest)
                except Exception as exc:
                    print(f"    skip: {type(exc).__name__}")
                time.sleep(DELAY)
                continue

            if ASSET_RE.search(absolute):
                continue

            path = urllib.parse.urlsplit(absolute).path
            if depth < MAX_DEPTH and path.startswith(prefix) and absolute not in seen_pages:
                seen_pages.add(absolute)
                queue.append((absolute, depth + 1))

    print(f"{section}: visited {pages} pages")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}

    for section, seed in SEEDS.items():
        print(f"=== {section}")
        crawl(section, seed, manifest)
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(manifest)} files in manifest")


if __name__ == "__main__":
    main()
