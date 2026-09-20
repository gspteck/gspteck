# Content Engine webhook — gspteck

Ported from AutoX `contentenginePublish` (X-ContentEngine-* HMAC contract).

## Endpoints (after deploy + custom domain)

- `POST https://gspteck.com/api/contentengine-publish`
- Direct: `https://us-central1-<PROJECT>.cloudfunctions.net/contentenginePublish`
- Dynamic `https://gspteck.com/sitemap.xml` and `/robots.txt`

## One-time setup

1. Create/select a Firebase project (edit `.firebaserc` `default` if not `gspteck`).
2. `firebase login` && `firebase use <project>`
3. Enable Hosting, Functions, Firestore, Storage.
4. Set secret from local file (do not paste in chat):

```bash
firebase functions:secrets:set CONTENTENGINE_SECRET --project <project> \
  < /workspace/content-engine-repos/secrets/gspteck.CONTENTENGINE_SECRET
```

5. Deploy:

```bash
cd functions && npm install
cd .. && firebase deploy --only functions,hosting --project <project>
```

6. Point `gspteck.com` to Firebase Hosting (or use `*.web.app` until DNS is ready).

## Local Content Engine

Secret fingerprint lives in `../secrets/index.json`. Publish helper:

```bash
python3 ../scripts/publish_contentengine.py --project gspteck ...
```

(gspteck publish is enabled once the live webhook exists.)
