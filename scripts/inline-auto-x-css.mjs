import {readFileSync, writeFileSync} from "fs";
import {resolve, dirname} from "path";
import {fileURLToPath} from "url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "public", "auto-x");
const html = readFileSync(resolve(root, "index.html"), "utf8");
const css = readFileSync(resolve(root, "style.css"), "utf8");
const link = '<link rel="stylesheet" href="/auto-x/style.css" />';
const inlined = html.replace(link, `<style>\n${css}\n</style>`);
if (inlined === html) {
  throw new Error("Could not find stylesheet link in index.html");
}
writeFileSync(resolve(root, "index.html"), inlined);
console.log(`Inlined ${css.length} bytes of CSS`);