/**
 * gspteck ImageObject creator (Image Metadata). Run with `node --test`.
 */
const { test } = require("node:test");
const assert = require("node:assert");
const {
  enhancePostHtml,
  ensureImageCreatorInJsonLd,
  GSPTECK_IMAGE_CREATOR,
  GSPTECK_PUBLISHER,
} = require("/workspace/content-engine-repos/gspteck/functions/seo-extras.js");

const CREATOR = {
  "@type": "Person",
  name: "giosaia (GSPTeck)",
  url: "https://gspteck.com/author/giosaia",
};

function ldBlocks(html) {
  const blocks = [];
  const re = /<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) blocks.push(JSON.parse(m[1]));
  return blocks;
}

test("GSPTECK_IMAGE_CREATOR is Person giosaia, no license fields", () => {
  assert.deepStrictEqual(GSPTECK_IMAGE_CREATOR, CREATOR);
  assert.ok(!("license" in GSPTECK_IMAGE_CREATOR));
  assert.ok(!("acquireLicensePage" in GSPTECK_IMAGE_CREATOR));
});

test("adds creator to a standalone ImageObject and leaves license fields absent", () => {
  const html = `<head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"ImageObject","contentUrl":"https://example.com/a.webp","url":"https://example.com/a.webp","creditText":"giosaia (GSPTeck)","copyrightNotice":"GSPTeck"}</script>
</head>`;
  const out = ensureImageCreatorInJsonLd(html);
  const [img] = ldBlocks(out);
  assert.strictEqual(img["@type"], "ImageObject");
  assert.deepStrictEqual(img.creator, CREATOR);
  assert.strictEqual(img.creditText, "giosaia (GSPTeck)");
  assert.ok(!("license" in img));
  assert.ok(!("acquireLicensePage" in img));
});

test("adds creator to BlogPosting.image but not publisher.logo", () => {
  const html = `<head>
<script type="application/ld+json">${JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: "Test",
    image: {
      "@type": "ImageObject",
      url: "https://example.com/post.webp",
      contentUrl: "https://example.com/post.webp",
    },
    publisher: {
      "@type": "Organization",
      name: "GSPTeck",
      url: "https://gspteck.com/",
      logo: { "@type": "ImageObject", url: "https://gspteck.com/assets/gspteck-high-resolution-logo.png" },
    },
  })}</script>
</head>`;
  const out = ensureImageCreatorInJsonLd(html);
  const [ld] = ldBlocks(out);
  assert.deepStrictEqual(ld.image.creator, CREATOR);
  assert.ok(!ld.publisher.logo.creator);
  assert.ok(!("license" in ld.image));
});

test("enhancePostHtml generates BlogPosting.image with creator and upgrades stored ImageObject", () => {
  const stored = `<!doctype html><html><head>
<title>Firebase Storage unauthorized in Flutter</title>
<meta name="description" content="Find the Storage rule that denies the request.">
<script type="application/ld+json">${JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: "Firebase Storage unauthorized in Flutter",
    image: "https://storage.googleapis.com/gspteck-a9e49.firebasestorage.app/lead.png",
    publisher: {
      "@type": "Organization",
      name: "GSPTeck",
      logo: { "@type": "ImageObject", url: GSPTECK_PUBLISHER.logo },
    },
  })}</script>
<script type="application/ld+json">${JSON.stringify({
    "@context": "https://schema.org",
    "@type": "ImageObject",
    contentUrl: "https://storage.googleapis.com/gspteck-a9e49.firebasestorage.app/lead.png",
    url: "https://storage.googleapis.com/gspteck-a9e49.firebasestorage.app/lead.png",
    creditText: "giosaia (GSPTeck)",
    copyrightNotice: "GSPTeck",
  })}</script>
</head><body>
<h1>Firebase Storage unauthorized in Flutter</h1>
<p class="byline"><strong>By giosaia (GSPTeck)</strong></p>
<p><img src="https://storage.googleapis.com/gspteck-a9e49.firebasestorage.app/lead.png" alt="Lead image"></p>
</body></html>`;
  const out = enhancePostHtml(stored, {
    canonical: "https://gspteck.com/firebase-storage-unauthorized-flutter-fix",
    publishedAt: "2026-11-19T07:18:01.684Z",
    updatedAt: "2026-11-19T07:18:01.684Z",
    author: { type: "Person", url: "https://gspteck.com/author/giosaia" },
    publisher: GSPTECK_PUBLISHER,
  });
  const blocks = ldBlocks(out);
  const posting = blocks.find((b) => b["@type"] === "BlogPosting");
  const image = blocks.find((b) => b["@type"] === "ImageObject");
  assert.ok(posting && posting.image && posting.image.creator);
  assert.deepStrictEqual(posting.image.creator, CREATOR);
  assert.ok(!posting.publisher.logo.creator);
  assert.deepStrictEqual(image.creator, CREATOR);
  assert.ok(!("license" in posting.image));
  assert.ok(!("acquireLicensePage" in image));
});
