// Offline report QA; use the existing bundled Playwright through NODE_PATH.
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

(async () => {
  const [report, screenshot, milestone = 'EH2.6.c4.1'] = process.argv.slice(2);
  if (!report || !screenshot) throw Error('report_and_screenshot_required');
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.MIDPROJECTRAG_REPORT_CHROMIUM || chromium.executablePath(),
  });
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    const external = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(/^https?:/, route => {
      external.push(route.request().url());
      return route.abort();
    });
    await page.goto(pathToFileURL(path.resolve(report)).href, {waitUntil: 'load'});
    for (const heading of ['지금 무엇을 쓰고 무엇을 만드는가', 'Gap / Priority',
      'Target Flow / Current Implementation Flow', '같은 계층으로 정렬한 스펙',
      '완료와 남은 gap', 'Validation']) {
      if (!await page.getByRole('heading', {name: heading, exact: true}).isVisible()) {
        throw Error(`heading_missing:${heading}`);
      }
    }
    const images = await page.locator('figure img').evaluateAll(nodes =>
      nodes.map(node => ({width: node.naturalWidth, height: node.naturalHeight})));
    if (images.length !== 2 || images.some(item => item.width === 0 || item.height === 0)) {
      throw Error('diagram_load_failed');
    }
    if (!await page.locator('.sub').first().innerText().then(text => text.includes(milestone))) {
      throw Error('milestone_missing');
    }
    const tables = await page.locator('table').count();
    if (tables < 6 || await page.locator('.legend .chip').count() !== 5) throw Error('comparison_missing');
    await page.screenshot({path: screenshot, fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
      throw Error('mobile_page_overflow');
    }
    if (errors.length || external.length) throw Error('page_errors_or_external_request');
    console.log(JSON.stringify({status: 'PASS', milestone, images, tables,
      desktop: '1440x1000', mobile: '390x844', page_errors: 0, external_requests: 0}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
