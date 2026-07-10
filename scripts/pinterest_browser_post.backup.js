#!/usr/bin/env node
/**
 * Pinterest Browser Poster — Dad's Gadget Corner
 *
 * Posts pins from pinterest_posting_manifest.json using Playwright browser automation.
 * First run: opens visible browser for manual Pinterest login, saves session.
 * Subsequent runs: reuses saved session.
 *
 * Usage:
 *   node ~/.openclaw/scripts/pinterest_browser_post.js                # post all "ready" pins
 *   node ~/.openclaw/scripts/pinterest_browser_post.js --dry-run      # preview without posting
 *   node ~/.openclaw/scripts/pinterest_browser_post.js --board ai_smart_home  # post one board only
 *   node ~/.openclaw/scripts/pinterest_browser_post.js --pin board1_product1  # post one pin only
 *   node ~/.openclaw/scripts/pinterest_browser_post.js --login        # force re-login
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const MANIFEST_PATH = path.join(process.env.HOME, '.openclaw/workspace/pinterest_posting_manifest.json');
const PERSISTENT_PROFILE_DIR = path.join(process.env.HOME, '.openclaw/data/browser/profiles/atlas-pinterest');
const ATLAS_PROFILE_DIR = 'Profile 9';
const LOG_PATH = path.join(process.env.HOME, '.openclaw/workspace/pinterest_post_log.json');

// Parse CLI args
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const FORCE_LOGIN = args.includes('--login');
const DEBUG = args.includes('--debug');
const KEEP_OPEN = args.includes('--keep-open');
const BOARD_FILTER = args.includes('--board') ? args[args.indexOf('--board') + 1] : null;
const PIN_FILTER = args.includes('--pin') ? args[args.indexOf('--pin') + 1] : null;
const SCREENSHOT_DIR = path.join(process.env.HOME, '.openclaw/workspace/pinterest_debug');

// Random delay between min and max seconds
function delay(minSec, maxSec) {
  const ms = (minSec + Math.random() * (maxSec - minSec)) * 1000;
  return new Promise(r => setTimeout(r, ms));
}

// Load or initialize post log (tracks what's been posted)
function loadLog() {
  try {
    return JSON.parse(fs.readFileSync(LOG_PATH, 'utf-8'));
  } catch {
    return { posted: [], failed: [], skipped: [] };
  }
}

function saveLog(log) {
  fs.writeFileSync(LOG_PATH, JSON.stringify(log, null, 2));
}

async function ensureLoggedIn(page) {
  await page.goto('https://www.pinterest.com/', { waitUntil: 'domcontentloaded' });
  await delay(2, 3);

  // Check if we're logged in by looking for the create button or user avatar
  const isLoggedIn = await page.locator('[data-test-id="header-avatar"]').count() > 0
    || await page.locator('[aria-label="Create"]').count() > 0
    || await page.locator('[data-test-id="create-button"]').count() > 0;

  if (!isLoggedIn) {
    console.log('\n=== Pinterest Login Required ===');
    console.log('Log into Pinterest in the browser window.');
    console.log('Press ENTER here when done...\n');
    await new Promise(resolve => {
      process.stdin.once('data', resolve);
    });
  }

  // Save session after login
  console.log('Using Atlas host Chrome profile session.');
}

async function screenshot(page, name) {
  if (!DEBUG) return;
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const file = path.join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`  [debug] screenshot: ${file}`);
}

// Try multiple selectors, return first match
async function findField(page, selectors, label, timeoutMs = 10000) {
  for (const sel of selectors) {
    try {
      const loc = page.locator(sel).first();
      await loc.waitFor({ state: 'visible', timeout: timeoutMs });
      console.log(`  Found ${label} via: ${sel}`);
      return loc;
    } catch { /* try next */ }
  }
  throw new Error(`Could not find ${label} field. Run with --debug to see screenshots.`);
}

async function postPin(page, pin) {
  console.log(`\nPosting: ${pin.id} — "${pin.title}"`);

  // Navigate to pin creation
  await page.goto('https://www.pinterest.com/pin-creation-tool/', { waitUntil: 'domcontentloaded' });
  await delay(3, 5);
  await screenshot(page, `${pin.id}_01_creation_tool`);

  // Upload image
  const imagePath = pin.image_file.replace('~', process.env.HOME);
  if (!fs.existsSync(imagePath)) {
    throw new Error(`Image not found: ${imagePath}`);
  }

  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(imagePath);
  console.log('  Image uploaded, waiting for processing...');
  await delay(4, 6);
  await screenshot(page, `${pin.id}_02_image_uploaded`);

  // Fill title — visible from screenshot: placeholder "Add a title"
  const titleField = await findField(page, [
    '[placeholder="Add a title"]',
    'input[placeholder*="title" i]',
    '[data-test-id="pin-draft-title"] input',
    '[data-test-id="pin-draft-title"] textarea',
    '[data-test-id="pin-draft-title"] [contenteditable="true"]',
  ], 'title', 8000);
  await titleField.click();
  await titleField.fill('');
  await page.keyboard.type(pin.title, { delay: 20 });
  await delay(0.5, 1);
  await screenshot(page, `${pin.id}_03_title_filled`);

  // Fill description — visible from screenshot: "Add a detailed description" placeholder
  const fullDesc = pin.description + '\n\n' + pin.hashtags.join(' ');

  // Try Playwright's getByPlaceholder first (works on divs, textareas, inputs)
  let descField;
  try {
    descField = page.getByPlaceholder('Add a detailed description');
    await descField.waitFor({ state: 'visible', timeout: 5000 });
    console.log('  Found description via getByPlaceholder');
  } catch {
    // Fallback: tab from title field to description
    try {
      descField = await findField(page, [
        '[placeholder="Add a detailed description"]',
        'div[data-placeholder*="description" i]',
        '[aria-label*="description" i]',
        'textarea[placeholder*="description" i]',
        'div[placeholder*="description" i]',
        '[contenteditable="true"][role="textbox"]',
        '[data-test-id="pin-draft-description"] [contenteditable="true"]',
      ], 'description', 5000);
    } catch {
      // Last resort: press Tab from title to move focus to description
      console.log('  Trying Tab from title to reach description...');
      await page.keyboard.press('Tab');
      await delay(0.5, 1);
      descField = null;
    }
  }
  if (descField) {
    await descField.click();
    try { await descField.fill(''); } catch { /* contenteditable may not support fill */ }
  }
  await page.keyboard.type(fullDesc, { delay: 10 });
  await delay(0.5, 1);
  await screenshot(page, `${pin.id}_04_desc_filled`);

  // Scroll down to reveal link field and board selector
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await delay(1, 2);
  await screenshot(page, `${pin.id}_04b_scrolled`);

  // Fill affiliate link
  const linkField = await findField(page, [
    '[placeholder*="destination" i]',
    '[placeholder*="link" i]',
    '[placeholder*="url" i]',
    '[placeholder*="website" i]',
    'input[placeholder*="Add a destination link" i]',
    '[data-test-id="pin-draft-link"] input',
    'input[aria-label*="link" i]',
  ], 'link', 8000);
  await linkField.click();
  await linkField.fill('');
  await page.keyboard.type(pin.affiliate_url, { delay: 15 });
  await delay(0.5, 1);
  await screenshot(page, `${pin.id}_05_link_filled`);

  // Board name mapping
  const boardNames = {
    'ai_smart_home': 'AI & Smart Home Gadgets',
    'home_office': 'Home Office & Desk Setup Essentials',
    'audio_recording': 'Audio & Recording Gear',
    'tech_gifts_dads': 'Tech Gifts for Dads',
    'portable_power': 'Portable Power & On-the-Go Tech'
  };
  const boardName = boardNames[pin.board_key] || pin.board_key;

  // Select board — look for the "Saving:" dropdown area visible in screenshot
  const boardBtn = await findField(page, [
    'button:has-text("Saving")',
    'button:has-text("Choose a board")',
    'button:has-text("Select")',
    '[data-test-id="board-dropdown-select-button"]',
    '[data-test-id="board-dropdown"] button',
    'button[aria-label*="oard"]',
    'div:has-text("Saving") >> button',
  ], 'board selector', 8000);
  await boardBtn.click();
  await delay(1, 2);
  await screenshot(page, `${pin.id}_06_board_dropdown`);

  // Try to search for board, or just click it directly
  try {
    const boardSearch = page.locator('[placeholder*="earch" i]').first();
    await boardSearch.waitFor({ state: 'visible', timeout: 3000 });
    await boardSearch.fill(boardName);
    await delay(1, 2);
  } catch {
    console.log('  No board search field, looking for board directly...');
  }

  // Click matching board option
  const boardOption = page.getByText(boardName, { exact: false }).first();
  await boardOption.waitFor({ state: 'visible', timeout: 5000 });
  await boardOption.click();
  await delay(1, 2);
  await screenshot(page, `${pin.id}_07_board_selected`);

  // Click Publish button — visible in top-right of screenshot as red "Publish" button
  const publishBtn = await findField(page, [
    'button:has-text("Publish")',
    '[data-test-id="board-dropdown-save-button"]',
    'button:has-text("Save")',
    'button[aria-label="Publish"]',
  ], 'publish button', 8000);
  await publishBtn.click();
  console.log('  Publish clicked. Waiting for confirmation...');
  await delay(4, 6);
  await screenshot(page, `${pin.id}_08_after_publish`);

  // Check for success
  const currentUrl = page.url();
  const success = currentUrl.includes('/pin/')
    || await page.locator(':text("Published"), :text("saved"), :text("created")').count() > 0
    || !currentUrl.includes('pin-creation-tool');

  return success;
}

async function main() {
  // Load manifest
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
  let pins = manifest.pins.filter(p => p.status === 'ready');

  // Apply filters
  if (BOARD_FILTER) {
    pins = pins.filter(p => p.board_key === BOARD_FILTER);
  }
  if (PIN_FILTER) {
    pins = pins.filter(p => p.id === PIN_FILTER);
  }

  const log = loadLog();
  // Skip already-posted pins
  pins = pins.filter(p => !log.posted.includes(p.id));

  console.log(`\nPinterest Browser Poster`);
  console.log(`Pins to post: ${pins.length}`);
  if (DRY_RUN) console.log('DRY RUN — no pins will be posted\n');

  if (pins.length === 0) {
    console.log('Nothing to post.');
    return;
  }

  if (DRY_RUN) {
    pins.forEach(p => console.log(`  [DRY] ${p.id}: ${p.title} -> ${p.board_key}`));
    return;
  }

  // Launch browser (visible so Pinterest doesn't flag it)
  fs.mkdirSync(PERSISTENT_PROFILE_DIR, { recursive: true });
  const context = await chromium.launchPersistentContext(PERSISTENT_PROFILE_DIR, {
    headless: false,
    channel: 'chrome',
    args: [
      '--disable-blink-features=AutomationControlled',
      `--profile-directory=${ATLAS_PROFILE_DIR}`
    ],
    viewport: { width: 1280, height: 900 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  });
  const browser = context.browser();
  const page = context.pages()[0] || await context.newPage();

  try {
    await ensureLoggedIn(page);

    let posted = 0;
    let failed = 0;

    for (const pin of pins) {
      try {
        const success = await postPin(page, pin);
        if (success) {
          log.posted.push(pin.id);
          posted++;
          console.log(`  POSTED (${posted}/${pins.length})`);
        } else {
          log.failed.push({ id: pin.id, reason: 'no confirmation detected', time: new Date().toISOString() });
          failed++;
          console.log(`  WARNING: no confirmation detected — check manually`);
        }
      } catch (err) {
        log.failed.push({ id: pin.id, reason: err.message, time: new Date().toISOString() });
        failed++;
        console.log(`  FAILED: ${err.message}`);
      }

      saveLog(log);

      // Human-like delay between pins (30-60 seconds)
      if (pins.indexOf(pin) < pins.length - 1) {
        const waitSec = 30 + Math.random() * 30;
        console.log(`  Waiting ${Math.round(waitSec)}s before next pin...`);
        await delay(waitSec, waitSec + 1);
      }
    }

    console.log(`\nDone. Posted: ${posted}, Failed: ${failed}`);
    console.log(`Log saved to: ${LOG_PATH}`);

  } finally {
    if (KEEP_OPEN) {
      console.log('\n--keep-open: browser stays open. Close it manually when done.');
      await new Promise(() => {}); // hang until user closes browser
    }
    await browser.close();
  }
}

main().catch(err => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
