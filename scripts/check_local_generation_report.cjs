// Static, local-only report check. Use bundled Playwright via NODE_PATH.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');
(async () => {
  const [report, screenshot] = process.argv.slice(2);
  // Allow an explicitly selected installed Chromium when the bundled revision is absent.
  const executablePath = process.env.MIDPROJECTRAG_REPORT_CHROMIUM || chromium.executablePath();
  const browser = await chromium.launch({headless:true,executablePath});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.resolve(report)).href, {waitUntil:'load'});
    const images = await page.locator('img').evaluateAll(nodes => nodes.map(n => ({width:n.naturalWidth,height:n.naturalHeight})));
    if (images.length !== 2 || images.some(n => !n.width || !n.height)) throw Error('diagram_load_failed');
    for (const text of ['실제 사용 스펙','실행 결과와 제한','Target / Current Flow','Target vs Current Gap','우선순위 / Relay']) {
      if (!await page.getByRole('heading',{name:text,exact:false}).isVisible()) throw Error('heading_missing');
    }
    if (!await page.locator('[aria-label="Color semantics"]').isVisible()) throw Error('legend_missing');
    if (await page.locator('table').count() !== 4) throw Error('table_missing');
    if (errors.length) throw Error('page_errors');
    fs.mkdirSync(path.dirname(screenshot),{recursive:true});
    await page.screenshot({path:screenshot,fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if (!await page.getByRole('heading',{level:1}).isVisible()) throw Error('mobile_heading_missing');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (overflow) throw Error('mobile_page_overflow');
    console.log(JSON.stringify({status:'PASS',images:images.length,tables:4,page_errors:errors.length,mobile_page_overflow:false}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
