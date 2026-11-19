#!/usr/bin/env python3
"""Quick tests for the narrowed hreflang / language-switch gate."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_post as v

SITE = "pilotaseo.com"
META = {"title": "Test", "meta_description": "A " * 20, "language": "en"}


def errors(body: str, meta: dict | None = None, host: str = SITE) -> list[str]:
    return v.translation_markup_errors(body, meta or META, host)


def assert_pass(name: str, body: str, **kw) -> None:
    errs = errors(body, **kw)
    if errs:
        raise SystemExit(f"FAIL {name}: expected pass, got {errs}")
    print(f"OK pass: {name}")


def assert_fail(name: str, body: str, **kw) -> None:
    errs = errors(body, **kw)
    if not errs:
        raise SystemExit(f"FAIL {name}: expected fail, got no errors")
    print(f"OK fail: {name} -> {errs[0][:90]}")


def main() -> int:
    prose = (
        "<p>Link the versions with hreflang, and write the second language natively. "
        "A page with no counterpart gets no hreflang annotations.</p>"
    )
    assert_pass("prose mention of hreflang", prose)

    escaped = (
        "<p>Example markup:</p>"
        "<pre><code>"
        "&lt;link rel=\"canonical\" href=\"https://example.com/it/preventivo-tetto\" /&gt;\n"
        "&lt;link rel=\"alternate\" hreflang=\"it\" href=\"https://example.com/it/preventivo-tetto\" /&gt;\n"
        "&lt;link rel=\"alternate\" hreflang=\"en\" href=\"https://example.com/roof-quote\" /&gt;"
        "</code></pre>"
        "<p>The word hreflang in this sentence must also pass.</p>"
    )
    assert_pass("escaped hreflang example in pre/code", escaped)

    code_only = "<p>Put annotations in a <code>&lt;link hreflang&gt;</code> tag.</p>"
    assert_pass("escaped &lt;link hreflang&gt; in code", code_only)

    real_link = (
        '<p>Intro.</p>'
        '<link rel="alternate" hreflang="it" href="https://pilotaseo.com/it/post">'
        "<p>More text.</p>"
    )
    assert_fail("real <link rel=alternate hreflang=it> in body", real_link)

    real_attr = '<p hreflang="it">Italian version pointer in body markup.</p>'
    assert_fail("hreflang attribute on a p element", real_attr)

    switcher = '<div class="ce-lang-switch"><a href="/it/">IT</a></div>'
    assert_fail("ce-lang-switch element", switcher)

    escaped_switch = "<p>Do not ship a <code>&lt;div class=\"ce-lang-switch\"&gt;</code> widget.</p>"
    assert_pass("escaped ce-lang-switch in code", escaped_switch)

    lang_it = '<p lang="it">Questa è una frase in italiano.</p>'
    assert_fail("lang=it on an element", lang_it)

    lang_en = '<p lang="en">This is English.</p><html lang="en-US">'
    assert_pass("lang=en and lang=en-US", lang_en)

    locale_a = '<p>Read the <a href="/it/preventivo-tetto">Italian version</a>.</p>'
    assert_fail("same-site /it/ language-switch link", locale_a)

    locale_abs = '<p>See <a href="https://pilotaseo.com/it/setup">the Italian page</a>.</p>'
    assert_fail("absolute same-site /it/ link", locale_abs)

    code_path = "<p>A subfolder such as <code>example.com/it/</code> is usually simplest.</p>"
    assert_pass("locale path mentioned in code, not as a link", code_path)

    other_site = '<p>Source: <a href="https://developers.google.com/search/docs">Google</a>.</p>'
    assert_pass("external docs link is not a locale switch", other_site)

    # Regression: slugs that start with an ISO 639-1 code (is-, in-, to-, ...)
    # must not be treated as locale folders.
    ai_slug = '<p>See <a href="https://pilotaseo.com/is-ai-written-blog-content-bad-for-seo-google-guidance-2026">AI content</a>.</p>'
    assert_pass("hyphenated slug starting with is- is not a locale path", ai_slug)
    in_slug = '<p>See <a href="/internal-linking-small-business-blog-service-pages-2026">internal linking</a>.</p>'
    assert_pass("hyphenated slug starting with in- is not a locale path", in_slug)
    en_us = '<p>See <a href="https://pilotaseo.com/en-us/setup">US English</a>.</p>'
    assert_fail("en-us locale folder is a language-switch link", en_us)

    meta_tr = dict(META)
    meta_tr["translations"] = {"it": "https://pilotaseo.com/it/x"}
    if not errors("<p>No markup here, only a translations map.</p>", meta=meta_tr):
        raise SystemExit("FAIL translations map in meta should fail")
    print("OK fail: translations map in draft JSON")

    api = '<script src="https://translate.googleapis.com/translate_a/element.js"></script>'
    assert_fail("translate.googleapis script", api)

    # Full validate(): prose mention passes; real link tag fails.
    pad = " ".join(["word"] * 1300)
    base = (
        f"<p>{pad}</p>"
        '<p>See <a href="https://pilotaseo.com/pricing">pricing</a>, '
        '<a href="https://pilotaseo.com/canonical-tags-small-business-blog-when-you-need-one-2026">canonicals</a>, '
        'and <a href="https://pilotaseo.com/does-small-business-blog-need-xml-sitemap-2026">sitemaps</a>.</p>'
        '<p>Sources: <a href="https://developers.google.com/search/docs/specialty/international/localized-versions">Google hreflang docs</a> '
        'and <a href="https://developers.google.com/search/docs/specialty/international/managing-multi-regional-sites">multilingual sites</a>.</p>'
    )
    meta = {
        "title": "Should a Small Business Blog Be in Two Languages?",
        "meta_description": "A 5-step setup for a bilingual small business blog.",
        "language": "en",
    }
    prose_body = base + "<p>Link the versions with hreflang annotations.</p>"
    errs = v.validate(body_html=prose_body, meta=meta, site_host=SITE, skip_link_check=True)
    if errs:
        raise SystemExit(f"FAIL full validate prose mention: {errs}")
    print("OK pass: full validate() with prose mention of hreflang")

    fail_body = base + '<link rel="alternate" hreflang="it" href="https://pilotaseo.com/it/x">'
    errs = v.validate(body_html=fail_body, meta=meta, site_host=SITE, skip_link_check=True)
    if not errs or not any("hreflang" in e for e in errs):
        raise SystemExit(f"FAIL full validate real link tag: {errs}")
    print("OK fail: full validate() with real <link rel=alternate hreflang=it>")

    # The rejected draft itself (placeholders don't matter for this check)
    draft = Path(
        "/workspace/content-engine-repos/drafts/_tmp_gen/2026-11-19/tpl/"
        "pilotaseo-bilingual-REJECTED-by-gate.html"
    )
    if draft.exists():
        terr = v.translation_markup_errors(draft.read_text(), meta, SITE)
        if terr:
            raise SystemExit(f"FAIL rejected draft should now pass the hreflang gate: {terr}")
        print("OK pass: rejected bilingual draft has no language-switch markup")

    print("All hreflang gate tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
