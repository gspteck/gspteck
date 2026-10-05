#!/usr/bin/env python3
"""Sign and POST a Content Engine draft. Never prints secrets.

Supports: ping | post.publish | post.update | post.delete | media.upload
For media.upload pass --media-files path1,path2,... (PNG/JPEG).
English only. Draft translations and --translations-json are ignored and
never sent. Pages are published from title, body_html, and meta_description.
"""
from __future__ import annotations
import argparse, base64, hashlib, hmac, json, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlparse
import validate_post

ROOT = Path(__file__).resolve().parents[1]
CARD = Path('/home/box/agent-data/box-secrets.json')

WEBHOOKS = {
    'coindrop': 'https://coindrop.website/api/contentengine-publish',
    'coinx': 'https://us-central1-coinx-c08b6.cloudfunctions.net/contentenginePublish',
    # Custom domain preferred (also served by Firebase Hosting rewrite)
    'autox': 'https://autox.network/api/contentengine-publish',
    'gspteck': 'https://gspteck.com/api/contentengine-publish',
    'buywellonce': 'https://buyoncewell.com/api/contentengine-publish',
}

SECRET_ENV_KEYS = {
    'coindrop': 'CONTENTENGINE_SECRET_COINDROP',
    'coinx': 'CONTENTENGINE_SECRET_COINX',
    'autox': 'CONTENTENGINE_SECRET_AUTOX',
    'gspteck': 'CONTENTENGINE_SECRET_GSPTECK',
    'buywellonce': 'CONTENTENGINE_SECRET_BUYWELLONCE',
}


SITE_HOSTS = {
    'coindrop': 'coindrop.website',
    'coinx': 'coinx.gspteck.com',
    'autox': 'autox.network',
    'gspteck': 'gspteck.com',
    'buywellonce': 'buyoncewell.com',
}

def verify_published_url(url: str, project: str) -> None:
    """Fail if live URL host mismatches project or cross-domain 3xx occurs."""
    expected = SITE_HOSTS.get(project)
    if not expected or not url:
        raise SystemExit(f'verify: missing expected host or url for project={project}')

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(5):
        req = urllib.request.Request(
            current, method='GET', headers={'User-Agent': 'ContentEnginePublish/1.0'}
        )
        try:
            with opener.open(req, timeout=30) as resp:
                code = resp.status
                host = (urlparse(current).hostname or '').lower().removeprefix('www.')
                if host != expected:
                    raise SystemExit(f'verify FAIL: host {host!r} != expected {expected!r}')
                if code >= 400:
                    raise SystemExit(f'verify FAIL: HTTP {code} for {current}')
                print(f'verify OK {code} {current}')
                return
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get('Location') or ''
                if not loc:
                    raise SystemExit(f'verify: redirect {e.code} without Location from {current}')
                from urllib.parse import urljoin
                nxt = urljoin(current, loc)
                cur_host = (urlparse(current).hostname or '').lower().removeprefix('www.')
                nxt_host = (urlparse(nxt).hostname or '').lower().removeprefix('www.')
                if nxt_host != cur_host:
                    raise SystemExit(
                        f'verify FAIL: cross-domain redirect {cur_host} -> {nxt_host} ({e.code})'
                    )
                current = nxt
                continue
            raise SystemExit(f'verify FAIL: HTTP {e.code} for {current}')
        except Exception as e:
            raise SystemExit(f'verify FAIL: {type(e).__name__}: {e}')
    raise SystemExit('verify FAIL: too many redirects')



def load_secret(project: str) -> str:
    # Keep trailing newline — Firebase secrets:set from file often stores it,
    # and HMAC must use the exact secret bytes the function has.
    def from_file(path: Path) -> str | None:
        if not path.exists():
            return None
        raw = path.read_bytes().decode()  # preserve trailing newline
        if not raw.strip():
            return None
        return raw

    p = ROOT / 'secrets' / f'{project}.CONTENTENGINE_SECRET'
    s = from_file(p)
    if s is not None:
        return s
    if CARD.exists():
        card = (json.loads(CARD.read_text()).get('card') or {})
        key = SECRET_ENV_KEYS.get(project)
        if key and card.get(key):
            v = str(card[key])
            return v
        if card.get('CONTENTENGINE_SECRET') and project in ('coindrop', 'coinx'):
            return str(card['CONTENTENGINE_SECRET'])
    legacy = ROOT / 'secrets' / 'CONTENTENGINE_SECRET'
    s = from_file(legacy) if project in ('coindrop', 'coinx') else None
    if s is not None:
        return s
    raise SystemExit(f'No CONTENTENGINE_SECRET for project={project}')

def sign(raw: bytes, secret: str) -> str:
    return 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

def post_signed(url: str, event: str, payload: dict, secret: str) -> tuple[int, str]:
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    headers = {
        'Content-Type': 'application/json',
        'X-ContentEngine-Event': event,
        'X-ContentEngine-Timestamp': str(int(time.time())),
        'X-ContentEngine-Signature': sign(raw, secret),
    }
    req = urllib.request.Request(url, data=raw, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace') if hasattr(e, 'read') else ''
        return e.code, body
    except Exception as e:
        return 0, f'{type(e).__name__}: {e}'

def guess_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
    }.get(ext, 'application/octet-stream')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True, choices=['coindrop','coinx','autox','gspteck','buywellonce'])
    ap.add_argument('--draft-json', default='')
    ap.add_argument('--body-html', default='')
    ap.add_argument('--event', default='post.publish',
                    choices=['ping','post.publish','post.update','post.delete','media.upload'])
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--media-files', default='',
                    help='Comma-separated image paths for media.upload')
    ap.add_argument('--post-slug', default='',
                    help='Override slug for media.upload (else from draft-json)')
    ap.add_argument('--webhook', default='',
                    help='Override webhook URL')
    ap.add_argument('--translations-json', default='',
                    help='Ignored. Content Engine posts are English only.')
    args = ap.parse_args()

    webhook = args.webhook or WEBHOOKS.get(args.project)
    if not webhook:
        raise SystemExit('no webhook')

    secret = load_secret(args.project)
    meta = {}
    if args.draft_json:
        meta = json.loads(Path(args.draft_json).read_text())

    if args.event == 'ping':
        payload = {'event': 'ping', 'test': bool(args.test)}
        if args.project in ('coindrop', 'coinx'):
            payload['site'] = args.project
        status, body = post_signed(webhook, args.event, payload, secret)
        print('status', status)
        print(body[:2000])
        return

    if args.event == 'media.upload':
        slug = args.post_slug or meta.get('slug')
        if not slug:
            raise SystemExit('media.upload needs --post-slug or --draft-json with slug')
        files = [Path(p.strip()) for p in args.media_files.split(',') if p.strip()]
        if not files:
            raise SystemExit('media.upload needs --media-files')
        media = []
        for f in files:
            if not f.exists():
                raise SystemExit(f'missing media file: {f}')
            media.append({
                'filename': f.name,
                'content_type': guess_content_type(f),
                'data_base64': base64.b64encode(f.read_bytes()).decode('ascii'),
            })
        payload = {
            'event': 'media.upload',
            'test': bool(args.test),
            'post_slug': slug,
            'media': media,
        }
        if args.project in ('coindrop', 'coinx'):
            payload['site'] = args.project
        status, body = post_signed(webhook, args.event, payload, secret)
        print('status', status)
        print(body[:8000])
        return

    if not args.draft_json or not args.body_html:
        raise SystemExit('post.* events need --draft-json and --body-html')

    body_html = Path(args.body_html).read_text()
    payload = {
        'event': args.event,
        'test': bool(args.test),
        'post': {
            'slug': meta['slug'],
            'title': meta.get('title'),
            'body_html': body_html,
            'meta_description': meta.get('meta_description'),
            'tags': meta.get('tags') or [],
            'author': meta.get('author'),
        },
        'related_articles': meta.get('related_articles') or [],
    }
    if args.translations_json or (isinstance(meta.get('translations'), dict) and meta.get('translations')):
        print('translations ignored; publishing English only', flush=True)
    if args.project in ('coindrop', 'coinx'):
        payload['site'] = args.project

    # Quality gate before any publish/update webhook call
    if args.event in ('post.publish', 'post.update'):
        host = SITE_HOSTS.get(args.project, '')
        errs = validate_post.validate(
            body_html=body_html,
            meta=meta,
            site_host=host,
        )
        if errs:
            print('validate_post FAILED — webhook not called:')
            for e in errs:
                print(' -', e)
            raise SystemExit(1)
        print('validate_post OK', flush=True)

    status, body = post_signed(webhook, args.event, payload, secret)
    print('status', status)
    print(body[:2000])

    if status == 200 and args.event in ('post.publish', 'post.update'):
        published_url = None
        try:
            published_url = (json.loads(body) or {}).get('published_url')
        except Exception:
            published_url = None
        if not published_url:
            slug = meta.get('slug')
            host = SITE_HOSTS.get(args.project)
            if slug and host:
                published_url = f'https://{host}/{slug}'
        if published_url:
            verify_published_url(published_url, args.project)

if __name__ == '__main__':
    main()
