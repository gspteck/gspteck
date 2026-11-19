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
# Machine-translation APIs are still banned anywhere in the draft.
TRANSLATE_API_RE = re.compile(r"translate\.googleapis|translation\.googleapis", re.I)
# Language-switcher hook used by the removed translation widget.
LANG_SWITCH_ATTR_RE = re.compile(
    r"""<(?:[a-zA-Z][\w:-]*)\b[^>]*(?:class|id)\s*=\s*["'][^"']*\bce-lang-switch\b""",
    re.I | re.S,
)
# Real HTML attribute, not the word in prose or escaped examples (&lt;link hreflang&gt;).
HREFLANG_ATTR_RE = re.compile(
    r"""<[a-zA-Z][\w:-]*\b[^>]*\bhreflang\s*=""",
    re.I | re.S,
)
# lang= / xml:lang= on a real tag.
LANG_ATTR_RE = re.compile(
    r"""<[a-zA-Z][\w:-]*\b[^>]*\b(?:xml:)?lang\s*=\s*(?:["']\s*)?([a-zA-Z]{1,8}(?:-[a-zA-Z0-9]{1,8})*)""",
    re.I | re.S,
)
# Common ISO 639-1 codes used as a first path segment or language subdomain.
LOCALE_LANG_CODES = frozenset(
    """
    aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch
    co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga
    gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja
    jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv
    mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or
    os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr
    ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi
    vo wa wo xh yi yo za zh zu
    """.split()
)
SWITCHER_CLASS_RE = re.compile(
    r"""<(?:[a-zA-Z][\w:-]*)\b[^>]*(?:class|id)\s*=\s*["'][^"']*\b(?:language-switcher|lang-switcher|lang-switch|hreflang-switch)\b""",
    re.I | re.S,
)

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


def _expected_lang(meta: dict) -> str:
    raw = str(meta.get("language") or meta.get("lang") or "en").strip().lower().replace("_", "-")
    return raw or "en"


def _lang_ok(value: str, expected: str) -> bool:
    value = (value or "").strip().lower().replace("_", "-")
    expected = (expected or "en").strip().lower().replace("_", "-")
    if not value:
        return True
    return value.split("-")[0] == expected.split("-")[0]


def _is_locale_path_segment(seg: str) -> bool:
    """True for it, en, en-us, pt-br, zh-hans, zh-hant-cn — not hyphenated slugs."""
    seg = (seg or "").lower()
    if seg in LOCALE_LANG_CODES:
        return True
    parts = seg.split("-")
    scripts = {"hans", "hant", "latn", "cyrl", "arab"}
    if len(parts) == 2:
        lang, rest = parts
        if lang in LOCALE_LANG_CODES and (len(rest) == 2 and rest.isalpha() or rest in scripts):
            return True
    if len(parts) == 3:
        lang, mid, region = parts
        if lang in LOCALE_LANG_CODES and mid in scripts and len(region) == 2 and region.isalpha():
            return True
    return False


def _path_starts_with_locale(path: str) -> bool:
    parts = [p for p in (path or "").split("/") if p]
    if not parts:
        return False
    return _is_locale_path_segment(parts[0])


def _is_same_site_host(host: str, site_host: str | None) -> bool:
    host = (host or "").lower().removeprefix("www.")
    site = (site_host or "").lower().removeprefix("www.")
    if not host or not site:
        return False
    return host == site or host.endswith("." + site) or host in SITE_HOST_ALIASES.get(site, ())


def _is_locale_switch_href(href: str, site_host: str | None) -> bool:
    """True for language-switch links to /it/ (or other locale) versions of this site."""
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return False
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        p = urlparse(href)
        host = (p.hostname or "").lower()
        if not _is_same_site_host(host, site_host):
            return False
        sub = host.split(".")[0]
        site = (site_host or "").lower().removeprefix("www.")
        # Language subdomain of this site, e.g. it.pilotaseo.com
        if sub in LOCALE_LANG_CODES and host.removeprefix("www.") != site:
            return True
        return _path_starts_with_locale(p.path or "/")
    if href.startswith("/") and not href.startswith("//"):
        return _path_starts_with_locale(href)
    return False


def translation_markup_errors(body_html: str, meta: dict, site_host: str | None = None) -> list[str]:
    """Flag real translation / language-switch markup, not prose mentions of hreflang.

    Fails: <link hreflang>, any hreflang attribute, ce-lang-switch / language-switcher
    elements, same-site links to /it/ (or other locale) versions, lang attributes
    other than the expected language, a translations map in draft JSON, and
    translate.googleapis / translation.googleapis. Passes: the word "hreflang"
    in prose, and escaped examples inside <code> or <pre> such as
    &lt;link hreflang&gt;.
    """
    errors: list[str] = []
    if isinstance(meta.get("translations"), dict) and meta.get("translations"):
        errors.append(
            "translation artifacts found (translations map in draft JSON); translation is banned"
        )
    if TRANSLATE_API_RE.search(body_html or ""):
        errors.append(
            "translation artifacts found (translate API); translation is banned"
        )
    if HREFLANG_ATTR_RE.search(body_html or ""):
        errors.append(
            "language-switch markup found (hreflang attribute on an HTML element); "
            "prose or escaped examples are allowed, real markup is not"
        )
    if LANG_SWITCH_ATTR_RE.search(body_html or "") or SWITCHER_CLASS_RE.search(body_html or ""):
        errors.append(
            "language-switch markup found (language-switcher element); translation widgets are banned"
        )
    expected = _expected_lang(meta)
    for m in LANG_ATTR_RE.finditer(body_html or ""):
        if not _lang_ok(m.group(1), expected):
            errors.append(
                f"language-switch markup found (lang={m.group(1)!r} on an HTML element; "
                f"expected {expected})"
            )
            break
    for href in HREF_RE.findall(body_html or ""):
        if _is_locale_switch_href(href, site_host):
            errors.append(
                f"language-switch markup found (same-site locale-version link: {href})"
            )
            break
    return errors


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
        errors.append("body contains RichAds script (RichAds has been removed; do not include it in drafts)")
    # Translation widgets and language-switch *markup* are banned; the word
    # "hreflang" in prose or escaped <code>/<pre> examples is allowed.
    errors.extend(translation_markup_errors(body_html, meta, site_host))

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
