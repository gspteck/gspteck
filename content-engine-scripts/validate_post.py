#!/usr/bin/env python3
"""Pre-publish quality gate for Content Engine posts.

Fails (exit 1) unless:
- body word count is between 1200 and 1800
- >=2 external primary-source https links that respond 2xx/3xx (HEAD then GET)
- >=2 internal same-site links
- meta title and meta description present (from draft JSON and/or body <title>/<meta>)
- no placeholders/TODO/[insert]
- no RichAds script in the body itself
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

WORD_RE = re.compile(r"[A-Za-z0-9']+")
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
PLACEHOLDER_RE = re.compile(
    r"\bTODO\b|\bTBD\b|\[insert[^\]]*\]|\[citation needed\]|lorem ipsum",
    re.I,
)
RICHADS_RE = re.compile(r"richads-pu-ob\.js", re.I)

# Domains that do not count as primary sources
SKIP_EXTERNAL_HOST_PARTS = (
    "googleapis.com",
    "gstatic.com",
    "google-analytics.com",
    "googletagmanager.com",
    "richinfo.co",
    "storage.googleapis.com",
)


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def text_words(html: str) -> int:
    s = _Stripper()
    try:
        s.feed(html)
    except Exception:
        pass
    return len(WORD_RE.findall(" ".join(s.parts)))


def link_ok(url: str, timeout: float = 12.0) -> bool:
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(
            url,
            method=method,
            headers={"User-Agent": "ContentEngineValidator/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 400:
                    return True
        except urllib.error.HTTPError as e:
            if 200 <= e.code < 400:
                return True
            if method == "HEAD" and e.code in (405, 403, 400):
                continue
        except Exception:
            if method == "HEAD":
                continue
            return False
    return False


def validate(
    *,
    body_html: str,
    meta: dict,
    site_host: str | None,
    skip_link_check: bool = False,
) -> list[str]:
    errors: list[str] = []
    title = (meta.get("title") or "").strip()
    meta_desc = (meta.get("meta_description") or "").strip()
    if not title:
        # fallback: <title> in body
        m = re.search(r"<title[^>]*>([^<]+)</title>", body_html, re.I)
        title = (m.group(1).strip() if m else "")
    if not meta_desc:
        m = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            body_html,
            re.I,
        )
        if not m:
            m = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
                body_html,
                re.I,
            )
        meta_desc = (m.group(1).strip() if m else "")
    if not title:
        errors.append("missing meta title")
    if not meta_desc:
        errors.append("missing meta description")

    if PLACEHOLDER_RE.search(body_html):
        errors.append("body contains placeholder/TODO/[insert] text")
    if RICHADS_RE.search(body_html):
        errors.append("body contains RichAds script (must be injected by publisher, not draft)")

    words = text_words(body_html)
    if words < 1200 or words > 1800:
        errors.append(f"word count {words} outside 1200–1800")

    hrefs = HREF_RE.findall(body_html)
    host = (site_host or "").lower().removeprefix("www.")
    internal = []
    external = []
    for h in hrefs:
        if not h or h.startswith("#") or h.startswith("mailto:") or h.startswith("tel:"):
            continue
        if h.startswith("/") and not h.startswith("//"):
            internal.append(h)
            continue
        if not h.startswith("http://") and not h.startswith("https://"):
            continue
        if not h.startswith("https://"):
            continue
        p = urlparse(h)
        hhost = (p.hostname or "").lower().removeprefix("www.")
        if any(part in hhost for part in SKIP_EXTERNAL_HOST_PARTS):
            continue
        if host and (hhost == host or hhost.endswith("." + host)):
            internal.append(h)
        else:
            external.append(h)

    # dedupe preserve order
    def uniq(xs: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    internal = uniq(internal)
    external = uniq(external)
    if len(internal) < 2:
        errors.append(f"need >=2 internal links, found {len(internal)}")
    if len(external) < 2:
        errors.append(f"need >=2 external primary-source https links, found {len(external)}")
    elif not skip_link_check:
        live = []
        for u in external:
            if link_ok(u):
                live.append(u)
            if len(live) >= 2:
                break
        if len(live) < 2:
            errors.append(
                f"need >=2 live external primary-source links (2xx/3xx); checked ok={len(live)} of {len(external)}"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-json", required=True)
    ap.add_argument("--body-html", required=True)
    ap.add_argument("--site-host", default="", help="e.g. gspteck.com for internal-link detection")
    ap.add_argument("--skip-link-check", action="store_true")
    args = ap.parse_args()
    meta = json.loads(Path(args.draft_json).read_text())
    body = Path(args.body_html).read_text()
    host = args.site_host or ""
    if not host:
        canon = meta.get("canonical") or meta.get("url") or ""
        if canon.startswith("http"):
            host = urlparse(canon).hostname or ""
    errs = validate(
        body_html=body,
        meta=meta,
        site_host=host,
        skip_link_check=args.skip_link_check,
    )
    if errs:
        print("validate_post FAILED:")
        for e in errs:
            print(" -", e)
        return 1
    print("validate_post OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
