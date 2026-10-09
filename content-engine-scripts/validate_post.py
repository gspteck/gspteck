#!/usr/bin/env python3
"""Pre-publish quality gate for Content Engine posts.

Fails (exit 1) unless:
- body word count is between 1200 and 1800
- >=2 external primary-source https links that respond 2xx/3xx (HEAD then GET)
- >=2 internal same-site links
- meta title and meta description present (from draft JSON and/or body <title>/<meta>)
- no placeholders/TODO/[insert]
- no RichAds script in the body itself

Roundup posts (draft JSON "post_type": "roundup", or "type": "roundup"):
- word count 1500–3000 instead of 1200–1800
- Amazon links do not count toward the >=2 external primary sources
- every Amazon link must be https://www.amazon.com/dp/<ASIN>?tag=<tag>
  (tag from draft "affiliates"[].tag, default buywellonce-20)
- >=3 distinct tagged ASINs, and every ASIN in draft "affiliates" must be linked
- must contain a comparison <table>
Single-product posts are validated exactly as before.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WORD_RE = re.compile(r"[A-Za-z0-9']+")
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
PLACEHOLDER_RE = re.compile(
    r"\bTODO\b|\bTBD\b|\[insert[^\]]*\]|\[citation needed\]|lorem ipsum",
    re.I,
)
RICHADS_RE = re.compile(r"richads-pu-ob\.js", re.I)
TRANSLATION_RE = re.compile(r"hreflang|ce-lang-switch|translate\.googleapis|translation\.googleapis", re.I)
AMAZON_DP_RE = re.compile(r"^/(?:[^/]+/)?dp/([A-Z0-9]{10})/?$", re.I)

ROUNDUP_MIN_WORDS = 1500
ROUNDUP_MAX_WORDS = 3000
ROUNDUP_MIN_ASINS = 3


def is_roundup(meta: dict) -> bool:
    t = str(meta.get("post_type") or meta.get("type") or "").strip().lower()
    return t == "roundup"


def _is_amazon_host(host: str) -> bool:
    host = (host or "").lower()
    return host == "amazon.com" or host.endswith(".amazon.com") or host.startswith("amazon.") or ".amazon." in host or host == "amzn.to"

# Alternate hostnames that serve (or 301 to) the same site; links to them count as internal.
SITE_HOST_ALIASES = {
    "swappr.website": ("swapprapp.web.app", "swapprapp.firebaseapp.com"),
    "coindrop.website": ("coindropapp.web.app", "coindropapp.firebaseapp.com"),
    "coinx.gspteck.com": ("coinx-c08b6.web.app", "coinx-c08b6.firebaseapp.com"),
    "pilotaseo.com": ("pilotaseo.web.app", "pilotaseo.firebaseapp.com"),
}

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
    # Translation is permanently banned (9 Oct 2026): no machine-translated variants or switchers.
    if TRANSLATION_RE.search(body_html) or (isinstance(meta.get("translations"), dict) and meta.get("translations")):
        errors.append("translation artifacts found (translations map / hreflang / ce-lang-switch / translate API); translation is banned")

    roundup = is_roundup(meta)
    words = text_words(body_html)
    lo, hi = (ROUNDUP_MIN_WORDS, ROUNDUP_MAX_WORDS) if roundup else (1200, 1800)
    if words < lo or words > hi:
        errors.append(f"word count {words} outside {lo}–{hi}")

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
        if host and (hhost == host or hhost.endswith("." + host) or hhost in SITE_HOST_ALIASES.get(host, ())):
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
    if roundup:
        errors.extend(_roundup_checks(body_html, meta))
        external = [u for u in external if not _is_amazon_host(urlparse(u).hostname or "")]
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


def _roundup_checks(body_html: str, meta: dict) -> list[str]:
    errs: list[str] = []
    affs = meta.get("affiliates") or []
    tag = next((a.get("tag") for a in affs if isinstance(a, dict) and a.get("tag")), None) or "buywellonce-20"
    expected = {str(a.get("asin")).upper() for a in affs if isinstance(a, dict) and a.get("asin")}
    linked: set[str] = set()
    for h in HREF_RE.findall(body_html):
        h = _html.unescape(h)
        p = urlparse(h)
        if not _is_amazon_host(p.hostname or ""):
            continue
        host = (p.hostname or "").lower()
        m = AMAZON_DP_RE.match(p.path or "")
        q = {k: v[0] for k, v in parse_qs(p.query or "").items()}
        if p.scheme != "https" or host not in ("www.amazon.com", "amazon.com") or not m:
            errs.append(f"roundup: non-US or non-/dp/ Amazon link: {h}")
            continue
        if q.get("tag") != tag:
            errs.append(f"roundup: Amazon link missing tag={tag}: {h}")
            continue
        linked.add(m.group(1).upper())
    if len(linked) < ROUNDUP_MIN_ASINS:
        errs.append(f"roundup: need >={ROUNDUP_MIN_ASINS} distinct tagged ASIN links, found {len(linked)}")
    missing = sorted(expected - linked)
    if missing:
        errs.append(f"roundup: affiliates ASINs not linked in body: {', '.join(missing)}")
    if not re.search(r"<table\b", body_html, re.I):
        errs.append("roundup: missing comparison <table>")
    return errs


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
