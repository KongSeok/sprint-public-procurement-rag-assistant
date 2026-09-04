// Static report only; no application requests or corpus content.
const fs = require('fs');
const path = require('path');
const {pathToFileURL} = require('url');
const {chromium} = require('playwright');
(async () => {
  const [report, screenshot] = process.argv.slice(2);
  const browser = await chromium.launch({headless:true, executablePath:process.env.MIDPROJECTRAG_REPORT_CHROMIUM || chromium.executablePath()});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1100}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.resolve(report)).href, {waitUntil:'load'});
    const images = await page.locator('img').evaluateAll(nodes => nodes.map(n => [n.naturalWidth,n.naturalHeight]));
    if (images.length !== 2 || images.some(v => v.some(n => n === 0))) throw Error('diagram_load_failed');
    for (const name of ['Target Flow / Current Implementation Flow','Gap / Priority','완료와 남은 gap','Validation']) {
      if (!await page.getByRole('heading',{name,exact:true}).isVisible()) throw Error('heading_missing');
    }
    const tables = await page.locator('table').count();
    if (!await page.locator('.legend').isVisible() || tables < 8 || errors.length) throw Error('report_contract_failed');
    fs.mkdirSync(path.dirname(screenshot), {recursive:true});
    await page.screenshot({path:screenshot,fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('mobile_overflow');
    console.log(JSON.stringify({status:'PASS',images:2,tables,page_errors:errors.length,mobile_overflow:false}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error.message); process.exitCode=1;});
