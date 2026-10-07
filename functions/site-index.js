/*
 * Server-rendered homepage "Latest articles" block and plain HTML /blog archive.
 * No JS dependency, no RichAds (landings only). Rendered from Firestore at request
 * time (cached per instance for a few minutes) so new posts appear automatically.
 */
const fs = require("fs");
const path = require("path");

const BLOG_PATH = "/blog";
const HOME_LATEST_COUNT = 5;
const INDEX_CACHE_TTL_MS = 5 * 60 * 1000;

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function decodeBasicEntities(str) {
  return String(str || "")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function extractTitle(html, slug) {
  const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html || "");
  const t = m ? decodeBasicEntities(m[1]).replace(/\s+/g, " ").trim() : "";
  if (t) return t;
  return String(slug || "")
    .split("-")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function extractDescription(html) {
  const m = /<meta\b[^>]*\bname\s*=\s*["']description["'][^>]*>/i.exec(html || "");
  if (!m) return "";
  const c = /\bcontent\s*=\s*"([^"]*)"/i.exec(m[0]) || /\bcontent\s*=\s*'([^']*)'/i.exec(m[0]);
  return c ? decodeBasicEntities(c[1]).trim() : "";
}

function tsToMillis(ts) {
  if (!ts) return 0;
  if (typeof ts.toMillis === "function") return ts.toMillis();
  if (typeof ts.toDate === "function") return ts.toDate().getTime();
  if (ts instanceof Date) return ts.getTime();
  return 0;
}

function isoDay(ms) {
  return ms ? new Date(ms).toISOString().split("T")[0] : "";
}

/**
 * @param {object} opts
 * @param {FirebaseFirestore.Firestore} opts.db
 * @param {string} opts.collection
 * @param {string} opts.baseUrl            e.g. "https://autox.network"
 * @param {string} opts.siteName           e.g. "AutoX"
 * @param {(slug:string)=>boolean} opts.isPublishableSlug  valid, not removed/410
 * @param {string} opts.homeTemplatePath   template with <!--LATEST_ARTICLES_ITEMS--> and <!--ARTICLE_COUNT-->
 */
function createSiteIndex(opts) {
  const { db, collection, baseUrl, siteName, isPublishableSlug, homeTemplatePath } = opts;
  let cache = null;
  let template = null;

  async function getIndex() {
    if (cache && Date.now() - cache.at < INDEX_CACHE_TTL_MS) return cache.items;
    const snap = await db.collection(collection).get();
    const items = [];
    for (const d of snap.docs) {
      const slug = d.id;
      if (!isPublishableSlug(slug)) continue;
      const data = d.data() || {};
      if (!data.html) continue;
      const ms = tsToMillis(data.publishedAt) || tsToMillis(data.updatedAt);
      items.push({
        slug,
        url: `${baseUrl}/${slug}`,
        title: extractTitle(data.html, slug),
        description: extractDescription(data.html),
        ms,
        date: isoDay(ms),
      });
    }
    items.sort((a, b) => b.ms - a.ms || a.slug.localeCompare(b.slug));
    cache = { at: Date.now(), items };
    return items;
  }

  function latestItemsHtml(items, indent) {
    const pad = indent || "            ";
    return items
      .slice(0, HOME_LATEST_COUNT)
      .map(
        (a) =>
          `${pad}<li><a href="${escapeHtml(a.url)}">${escapeHtml(a.title)}</a>` +
          (a.date ? ` <time datetime="${a.date}">${a.date}</time>` : "") +
          `</li>`
      )
      .join("\n");
  }

  function renderHome(items) {
    if (template === null) template = fs.readFileSync(homeTemplatePath, "utf8");
    return template
      .replace("<!--LATEST_ARTICLES_ITEMS-->", latestItemsHtml(items))
      .replace(/<!--ARTICLE_COUNT-->/g, String(items.length));
  }

  function renderBlog(items) {
    const title = `All ${siteName} articles`;
    const canonical = `${baseUrl}${BLOG_PATH}`;
    const list = items
      .map(
        (a) =>
          `      <li><a href="${escapeHtml(a.url)}">${escapeHtml(a.title)}</a>` +
          (a.date ? ` <time datetime="${a.date}">${a.date}</time>` : "") +
          (a.description ? `<br><span class="desc">${escapeHtml(a.description)}</span>` : "") +
          `</li>`
      )
      .join("\n");
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(title)}</title>
  <link rel="canonical" href="${escapeHtml(canonical)}">
  <meta name="description" content="${escapeHtml(`Every published ${siteName} article, newest first.`)}">
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; max-width: 780px; margin: 40px auto; padding: 0 16px; }
    ul { padding-left: 1.25rem; }
    li { margin: 0.75rem 0; }
    time { color: #6b7280; font-size: 0.9em; margin-left: 0.25rem; }
    .desc { color: #6b7280; font-size: 0.95em; }
  </style>
</head>
<body>
  <nav><a href="${escapeHtml(baseUrl)}/">${escapeHtml(siteName)} home</a></nav>
  <main>
    <h1>${escapeHtml(title)}</h1>
    <p>${items.length} articles, newest first.</p>
    <ul>
${list}
    </ul>
  </main>
  <footer><p><a href="${escapeHtml(baseUrl)}/">${escapeHtml(siteName)} home</a> &middot; <a href="${escapeHtml(baseUrl)}/sitemap.xml">Sitemap</a></p></footer>
</body>
</html>`;
  }

  /**
   * Handle "/", "/index.html", "/blog" requests. Returns true when handled.
   * @param {(res:any, path:string)=>void} redirectCanonical 301 helper to the canonical host+path
   * @param {boolean} canonicalHost whether the request host is the canonical apex
   */
  async function handleLanding(req, res, redirectCanonical, canonicalHost) {
    const p = req.path || "";
    const isHome = p === "" || p === "/";
    const isIndexHtml = /^\/index(\.html)?$/i.test(p);
    const isBlog = /^\/blog(\/|\.html)?$/i.test(p);
    if (!isHome && !isIndexHtml && !isBlog) return false;
    if (isIndexHtml) {
      redirectCanonical(res, "/");
      return true;
    }
    const target = isHome ? "/" : BLOG_PATH;
    if (!canonicalHost || (isBlog && p !== BLOG_PATH)) {
      redirectCanonical(res, target);
      return true;
    }
    let items = [];
    try {
      items = await getIndex();
    } catch (err) {
      console.error("[site-index] failed to list published pages", err);
    }
    const html = isHome ? renderHome(items) : renderBlog(items);
    const canonicalHref = isHome ? `${baseUrl}/` : `${baseUrl}${BLOG_PATH}`;
    res.set("Content-Type", "text/html; charset=utf-8");
    res.set("Cache-Control", "public, max-age=300");
    res.set("Link", `<${canonicalHref}>; rel="canonical"`);
    res.status(200).send(html);
    return true;
  }

  return { getIndex, renderHome, renderBlog, handleLanding };
}

module.exports = { createSiteIndex, BLOG_PATH, HOME_LATEST_COUNT };
