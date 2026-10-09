# Translation is permanently banned

**Ban (user decision, 9 Oct 2026):** never translate Content Engine content again, by any method:
no Google Cloud Translation API (it caused €185.70 in Sep 2026 and €53.74 by 9 Oct 2026 on `gspteck-a9e49`),
no Grok/LLM auto-translation, no 46-language generation, no `post.translations` map, no hreflang
alternates for machine-translated versions, no `?lang=` rendering, no `.ce-lang-switch` bar,
and no Cloud Function or scheduler that translates. Do not re-enable `translate.googleapis.com`
on any project. Each post is written once in its site's native language: English, or Italian
only where the site is natively Italian (PilotaSEO's hand-written IT page/posts).
This applies to every Content Engine site, including Buy Well Once (`buywellonce-7f2a`) and PilotaSEO.

# Content Engine is English only

Published posts on autox.network, coinx.gspteck.com, coindrop.website, and gspteck.com are English only. There is no 46-language translation step, no `post.translations` field, and no `.ce-lang-switch` language bar.

Buy Well Once (`affiliate-engine/buywellonce-site`) is also English only since 9 Oct 2026: `pickTranslation`, the language selector and `?lang=` rendering were removed.

## What a post contains

Flat English fields only:

- `title`
- `meta_description`
- `body_html`

`scripts/publish_contentengine.py` sends those fields. If a draft still has a `translations` object, or you pass `--translations-json`, the publisher ignores it.

`scripts/translate_and_publish.py` is a banned no-op stub. It does not call Google Translate or the Grok API and does not republish. Never restore its old behaviour.

## Functions

| Firebase project | Source | Collections |
|---|---|---|
| `autox-tg-bot` | `AutoX/functions` | `autoxPages` |
| `gspteck-a9e49` | `gspteck/functions` | `gspteckPages` |
| `coinx-c08b6` (dual-site) | `CoinX/functions` — never a RankGoat-only tree | `coinxPages`, `coindropPages` |
| `buywellonce-7f2a` | `affiliate-engine/buywellonce-site/functions` | published pages |
| `pilotaseo` | `PilotaSEO/functions` | one language per post (en or it), no translations |

On publish, the webhook deletes any stored `translations` map. Serve always returns the stored English HTML and strips a leftover `.ce-lang-switch` bar if one was baked in.

## Publish

```bash
python3 scripts/publish_contentengine.py \
  --project autox \
  --draft-json drafts/autox/SLUG.json \
  --body-html drafts/autox/SLUG.body.html \
  --event post.publish
```

## Verify

```bash
curl -sL 'https://autox.network/SLUG' | rg -n 'ce-lang-switch|<h1>'
curl -sL 'https://coinx.gspteck.com/SLUG' | rg -n 'ce-lang-switch|<h1>'
curl -sL 'https://coindrop.website/SLUG' | rg -n 'ce-lang-switch|<h1>'
curl -sL 'https://gspteck.com/SLUG' | rg -n 'ce-lang-switch|<h1>'
```

Expect an English `<h1>` and no `ce-lang-switch`. `?lang=` does not switch the page.
