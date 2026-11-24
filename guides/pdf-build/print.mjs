// Usage: node print.mjs in.html out.pdf  — prints an HTML file to PDF with the pre-installed Chromium.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const { chromium } = createRequire(import.meta.url)('playwright');
const [inp, out, title] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(path.resolve(inp)).href, { waitUntil: 'networkidle' });
await page.pdf({
  path: out, format: 'Letter', printBackground: true, preferCSSPageSize: true,
  displayHeaderFooter: true,
  headerTemplate: '<span></span>',
  footerTemplate: `<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;display:flex;justify-content:space-between;font-family:Arial">
    <span>${title}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
});
await browser.close();
