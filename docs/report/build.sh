#!/usr/bin/env bash
# Build REPORT.docx and REPORT.pdf from REPORT.md (Phase 10). Needs pandoc; the PDF also needs the frontend's
# Playwright Chromium (cd frontend && npm ci && npx playwright install chromium). No LaTeX: pandoc writes a
# self-contained HTML file (figures embedded) and Chromium prints it to A4 PDF with print.css.
#   bash docs/report/build.sh
set -euo pipefail
cd "$(dirname "$0")"
root="$(cd ../.. && pwd)"
here="$(pwd)"

# figure paths in REPORT.md are relative to this folder (../../reports/..., figures/...)
pandoc REPORT.md --toc --toc-depth=2 -o REPORT.docx
pandoc REPORT.md --toc --toc-depth=2 --standalone --embed-resources --css=print.css \
  --metadata=lang:en -o REPORT.html

(cd "$root/frontend" && node -e "
const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://$here/REPORT.html', { waitUntil: 'load' });
  await page.pdf({ path: '$here/REPORT.pdf', format: 'A4', printBackground: true, preferCSSPageSize: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style=\"font-size:8px;width:100%;text-align:center;color:#666\"><span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span></div>' });
  await browser.close();
})();
")
rm REPORT.html
ls -l REPORT.docx REPORT.pdf
