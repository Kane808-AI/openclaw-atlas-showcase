#!/usr/bin/env node
/**
 * Pinterest Browser Poster — Dad's Gadget Corner
 *
 * Posts or edits pins from pinterest_posting_manifest.json using the Atlas Chrome
 * CDP session (Profile 9, atlas-host-chrome user-data-dir). No AppleScript, no
 * System Events — all interactions go through Playwright CDP.
 *
 * Prerequisites: node browser_tool.js start --session atlas
 *
 * Usage:
 *   node pinterest_browser_post.js --dry-run
 *   node pinterest_browser_post.js --pin board1_product1
 *   node pinterest_browser_post.js --board ai_smart_home
 *   node pinterest_browser_post.js --edit-pin board1_product5 --pin-url https://pinterest.com/pin/123/
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const MANIFEST_PATH = path.join(process.env.HOME, '.openclaw/workspace/pinterest_posting_manifest.json');
const LOG_PATH = path.join(process.env.HOME, '.openclaw/workspace/pinterest_post_log.json');
const BROWSER_STATE = path.join(process.env.HOME, '.openclaw/data/browser/server-state.json');

const argv = process.argv.slice(2);
const DRY_RUN = argv.includes('--dry-run');
const BOARD_FILTER = argv.includes('--board') ? argv[argv.indexOf('--board') + 1] : null;
const PIN_FILTER = argv.includes('--pin') ? argv[argv.indexOf('--pin') + 1] : null;
const EDIT_PIN = argv.includes('--edit-pin') ? argv[argv.indexOf('--edit-pin') + 1] : null;
const PIN_URL = argv.includes('--pin-url') ? argv[argv.indexOf('--pin-url') + 1] : null;

const BOARD_NAMES = {
  ai_smart_home: 'AI & Smart Home Gadgets',
  home_office: 'Home Office & Desk Setup Essentials',
  audio_recording: 'Audio & Recording Gear',
  tech_gifts_dads: 'Tech Gifts for Dads',
  portable_power: 'Portable Power & On-the-Go Tech',
};

// ── Log helpers ───────────────────────────────────────────────────────────────

function loadLog() {
  try { return JSON.parse(fs.readFileSync(LOG_PATH, 'utf-8')); }
  catch { return { posted: [], failed: [], skipped: [] }; }
}

function saveLog(log) {
  fs.writeFileSync(LOG_PATH, JSON.stringify(log, null, 2));
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function delay(minSec, maxSec) {
  if (maxSec === undefined) maxSec = minSec;
  return sleep((minSec + Math.random() * (maxSec - minSec)) * 1000);
}

// ── Browser connection ────────────────────────────────────────────────────────

function readState() {
  try { return JSON.parse(fs.readFileSync(BROWSER_STATE, 'utf-8')); }
  catch { return null; }
}

async function connectBrowser() {
  const state = readState();
  if (!state || state.profileMode !== 'atlas') {
    throw new Error(
      `Atlas CDP session required. Current mode: ${state?.profileMode || 'none'}.\n` +
      'Run: node ~/.openclaw/scripts/browser_tool.js start --session atlas'
    );
  }
  if (!state.debugPort) {
    throw new Error('No debug port in atlas state. Restart: node browser_tool.js start --session atlas');
  }

  const browser = await chromium.connectOverCDP(`http://localhost:${state.debugPort}`);
  const contexts = browser.contexts();
  if (contexts.length === 0) throw new Error('No browser contexts in atlas Chrome');

  const ctx = contexts[0];
  const pages = ctx.pages();
  // Prefer an authenticated Pinterest tab over the login page
  let page = pages.find(p => p.url().includes('pinterest.com') && !p.url().includes('/login'));
  if (!page) page = await ctx.newPage();

  return { browser, page };
}

// ── File upload ───────────────────────────────────────────────────────────────

async function uploadFile(page, filePath) {
  // Pinterest's file input: id="storyboard-upload-input", hidden behind drag-drop UI.
  // Playwright's setInputFiles uses CDP DOM.setFileInputFiles — no OS file picker needed.
  await delay(1, 2);

  const fileInput = page.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"], input[type="file"]').first();
  if (await fileInput.count() === 0) throw new Error('Pinterest file input not found on page');
  await fileInput.setInputFiles(filePath);
}

// ── Field fill helpers ────────────────────────────────────────────────────────

async function fillFirst(page, selectors, text, timeoutMs = 6000) {
  for (const sel of selectors) {
    try {
      await page.waitForSelector(sel, { timeout: timeoutMs });
      await page.fill(sel, text);
      return true;
    } catch { continue; }
  }
  return false;
}

// ── Pin posting ───────────────────────────────────────────────────────────────

async function postPin(page, pin) {
  console.log(`\nPosting: ${pin.id} — "${pin.title}"`);
  const imagePath = pin.image_file.replace('~', process.env.HOME);
  if (!fs.existsSync(imagePath)) throw new Error(`Image not found: ${imagePath}`);

  // Navigate to pin builder
  console.log('  Navigating to pin creation tool...');
  await page.goto('https://www.pinterest.com/pin-creation-tool/', {
    waitUntil: 'domcontentloaded',
    timeout: 30000,
  });
  await delay(3, 5);

  // Upload image
  console.log('  Uploading image...');
  await uploadFile(page, imagePath);
  await delay(4, 6);

  // Title
  console.log('  Filling title...');
  const titleFilled = await fillFirst(page, [
    '[placeholder="Add a title"]',
    'input[placeholder*="title" i]',
    '[data-test-id="pin-draft-title"] input',
  ], pin.title);
  if (!titleFilled) throw new Error('Title field not found');
  await delay(0.5, 1);

  // Description
  console.log('  Filling description...');
  const fullDesc = pin.description + '\n\n' + pin.hashtags.join(' ');
  const descFilled = await fillFirst(page, [
    '[aria-label="Add a detailed description"]',
    '[data-test-id="storyboard-description-field-container"] [contenteditable]',
    '[contenteditable][role="combobox"]',
    'textarea',
  ], fullDesc);
  if (!descFilled) throw new Error('Description field not found');
  await delay(0.5, 1);

  // Scroll to reveal link + board selectors
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await delay(1, 2);

  // Affiliate link
  console.log('  Filling link...');
  const linkFilled = await fillFirst(page, [
    'input[type="url"]',
    'input[placeholder="Add a link"]',
    '[data-test-id="storyboard-selector-link"] input',
    'input[placeholder*="link" i]',
  ], pin.affiliate_url);
  if (!linkFilled) throw new Error('Link field not found');
  await delay(0.5, 1);

  // Board selection
  console.log('  Selecting board...');
  const boardName = BOARD_NAMES[pin.board_key] || pin.board_key;

  // Open board dropdown — scroll into view first to clear sticky header, then click
  const boardBtn = page.locator('[data-test-id="board-dropdown-select-button"]');
  if (await boardBtn.count() > 0) {
    // Scroll so the button is visible below the sticky header
    await boardBtn.scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -100)); // nudge up so header clears it
    await delay(0.5, 0.8);
    await boardBtn.click();
  } else {
    throw new Error('Board selector button not found');
  }
  await delay(1.5, 2);

  // Helper: open dropdown, search, and select board by name
  async function selectBoard(name) {
    const searchBox = page.locator('#pickerSearchField, input[aria-label="Search through your boards"]');

    // Wait for search field to become visible (dropdown just opened)
    try {
      await searchBox.first().waitFor({ state: 'visible', timeout: 5000 });
    } catch {
      // Search field not visible — dropdown may have closed; try scrolling into view
    }

    // Log all visible options before search
    const preOptions = await page.evaluate(() =>
      [...document.querySelectorAll('[role=option]')].map(el => el.textContent?.trim()?.slice(0,60))
    );
    console.log(`  [DEBUG] options before search: ${JSON.stringify(preOptions)}`);

    // If search box is visible, type board name to filter
    if (await searchBox.first().isVisible()) {
      // Use type() instead of fill() to trigger React event handlers properly
      await searchBox.first().click();
      await searchBox.first().fill('');
      await page.keyboard.type(name, { delay: 80 });
      await delay(2, 2.5); // wait for debounce + results
    }

    // Log options after search
    const postOptions = await page.evaluate(() =>
      [...document.querySelectorAll('[role=option]')].map(el => el.textContent?.trim()?.slice(0,60))
    );
    console.log(`  [DEBUG] options after search: ${JSON.stringify(postOptions)}`);

    // Look for the board option (partial text match)
    const option = page.locator('[role=option]').filter({ hasText: name });
    if (await option.count() > 0) {
      await option.first().click();
      return true;
    }
    return false;
  }

  if (!await selectBoard(boardName)) {
    // Board doesn't exist — create it
    console.log(`  NOTE: Board "${boardName}" not found — creating it`);
    const createBtn = page.locator('[data-test-id="create-board-button"], [data-test-id="create-board"]').first();
    if (await createBtn.count() === 0) throw new Error(`Board "${boardName}" not found and "Create board" button not found`);
    await createBtn.click();
    await delay(1, 2);

    const boardNameInput = page.locator('input[name="boardName"]').first();
    await boardNameInput.waitFor({ timeout: 8000 });
    await boardNameInput.fill(boardName);
    await delay(0.5, 1);

    const createSaveBtn = page.locator('[data-test-id="board-form-submit-button"]');
    if (await createSaveBtn.count() > 0) {
      await createSaveBtn.click();
    } else {
      const fallbackCreate = page.locator('button').filter({ hasText: /^create$/i });
      if (await fallbackCreate.count() > 0) await fallbackCreate.first().click();
      else throw new Error('Board create button not found in dialog');
    }

    // Wait for modal to close
    try {
      await page.waitForSelector('[role="dialog"]', { state: 'hidden', timeout: 6000 });
    } catch {
      const errorMsg = await page.evaluate(() => document.querySelector('[role="dialog"]')?.textContent || '');
      if (errorMsg.includes('already have a board')) {
        // Board exists but wasn't found in search — dismiss dialog and re-open dropdown
        await page.keyboard.press('Escape');
        await delay(2, 3); // wait for full dismiss animation
        await page.locator('[data-test-id="board-dropdown-select-button"]').click();
        await delay(1.5, 2);
        if (!await selectBoard(boardName)) {
          throw new Error(`Board "${boardName}" exists but could not be selected after re-open`);
        }
      } else {
        throw new Error(`Board creation modal did not close: ${errorMsg.slice(0, 100)}`);
      }
    }
    await delay(1, 1.5);
  }
  await delay(1, 2);

  // Dismiss any open dropdown overlay before publishing (prevents pointer-events interception)
  await page.keyboard.press('Escape').catch(() => {});
  await delay(0.5, 1);

  // Publish — set up URL watcher BEFORE clicking so we catch the /pin/ redirect
  console.log('  Publishing...');
  const pinUrlPromise = page.waitForURL(/\/pin\/\d+\//, { timeout: 15000 }).catch(() => null);

  const publishBtn = page.getByRole('button', { name: /^publish$/i });
  if (await publishBtn.count() > 0) {
    await publishBtn.click();
  } else {
    const fallback = page.locator('[data-test-id="board-dropdown-save-button"], [data-test-id="storyboard-creation-nav-done"]');
    if (await fallback.count() > 0) await fallback.click();
    else throw new Error('Publish button not found');
  }

  // Pinterest briefly lands on /pin/XXXXX/ then redirects to a fresh creation form
  const landed = await pinUrlPromise;
  if (landed !== null) {
    console.log(`  Published URL: ${page.url()}`);
    return true;
  }
  // Fallback: if redirect was too fast, check the current URL
  await delay(2, 3);
  const currentUrl = page.url();
  return currentUrl.includes('/pin/') || !currentUrl.includes('pin-creation-tool');
}

// ── Edit existing published pin ───────────────────────────────────────────────

async function editPin(page, pin, pinUrl) {
  console.log(`\nEditing: ${pin.id} — "${pin.title}"`);

  // Navigate to the edit page directly from the pin URL
  const editUrl = pinUrl.replace(/\/?$/, '/edit/');
  console.log(`  Navigating to ${editUrl}`);
  await page.goto(editUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(3, 4);

  // Confirm we're on an edit page (Pinterest redirects back to pin view if not owner)
  const currentUrl = page.url();
  if (!currentUrl.includes('/edit')) {
    throw new Error(`Edit page not reached — redirected to ${currentUrl}. Check pin ownership.`);
  }

  const fullDesc = pin.description + '\n\n' + pin.hashtags.join(' ');

  // Title
  console.log('  Updating title...');
  const titleFilled = await fillFirst(page, [
    '[data-test-id="pin-title-input"] input',
    'input[placeholder*="title" i]',
    'input[name="title"]',
  ], pin.title);
  if (!titleFilled) console.warn('  WARNING: title field not found — skipping');
  await delay(0.3, 0.5);

  // Description
  console.log('  Updating description...');
  const descFilled = await fillFirst(page, [
    '[data-test-id="pin-description-input"] [contenteditable]',
    '[data-test-id="pin-description-input"] textarea',
    '[aria-label*="description" i]',
    '[contenteditable][role="textbox"]',
    'textarea',
  ], fullDesc);
  if (!descFilled) console.warn('  WARNING: description field not found — skipping');
  await delay(0.3, 0.5);

  // Affiliate link
  console.log('  Updating link...');
  const linkFilled = await fillFirst(page, [
    '[data-test-id="pin-link-input"] input',
    'input[type="url"]',
    'input[placeholder*="link" i]',
    'input[name="link"]',
  ], pin.affiliate_url);
  if (!linkFilled) console.warn('  WARNING: link field not found — skipping');
  await delay(0.3, 0.5);

  // Save button
  console.log('  Saving...');
  const saveBtn = page.locator('button').filter({ hasText: /^save$/i });
  if (await saveBtn.count() > 0) {
    await saveBtn.first().click();
  } else {
    const fallback = page.locator('[data-test-id*="save"], [data-test-id*="done"]');
    if (await fallback.count() > 0) await fallback.first().click();
    else throw new Error('Save button not found on edit page');
  }
  await delay(3, 4);

  const afterUrl = page.url();
  return afterUrl.includes('/pin/') && !afterUrl.includes('/edit');
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
  let pins = manifest.pins.filter(p => p.status === 'ready');
  if (BOARD_FILTER) pins = pins.filter(p => p.board_key === BOARD_FILTER);
  if (PIN_FILTER || EDIT_PIN) pins = pins.filter(p => p.id === (PIN_FILTER || EDIT_PIN));

  const log = loadLog();

  console.log('\nPinterest Browser Poster (CDP mode)');

  // ── Edit mode ────────────────────────────────────────────────────────────────
  if (EDIT_PIN) {
    if (!PIN_URL) {
      console.error('--edit-pin requires --pin-url <pinterest_pin_url>');
      process.exit(1);
    }
    if (pins.length === 0) {
      console.error(`Pin ID not found in manifest: ${EDIT_PIN}`);
      process.exit(1);
    }
    const pin = pins[0];

    if (DRY_RUN) {
      console.log(`DRY RUN — would edit pin ${pin.id} at ${PIN_URL}`);
      console.log(`  Title: ${pin.title}`);
      console.log(`  Link:  ${pin.affiliate_url}`);
      return;
    }

    const state = readState();
    if (!state || state.profileMode !== 'atlas') {
      console.error('ABORT: Atlas CDP session required. Run: node browser_tool.js start --session atlas');
      process.exit(1);
    }

    console.log(`Editing pin: ${EDIT_PIN} at ${PIN_URL}`);
    const { browser, page } = await connectBrowser();
    try {
      const success = await editPin(page, pin, PIN_URL);
      if (success) {
        log.posted.push(pin.id);
        saveLog(log);
        console.log('  SAVED');
      } else {
        console.log('  WARNING: no confirmation — check Pinterest manually');
      }
    } finally {
      await browser.close();
    }
    return;
  }

  // ── Create mode ──────────────────────────────────────────────────────────────
  pins = pins.filter(p => !log.posted.includes(p.id));
  console.log(`Pins to post: ${pins.length}`);

  if (DRY_RUN) {
    console.log('DRY RUN — no pins will be posted\n');
    pins.forEach(p => console.log(`  [DRY] ${p.id}: ${p.title} -> ${p.board_key}`));
    return;
  }

  if (pins.length === 0) { console.log('Nothing to post.'); return; }

  // Atlas CDP guard — hard fail if not atlas mode
  const state = readState();
  if (!state || state.profileMode !== 'atlas') {
    console.error('ABORT: Atlas CDP session required. Current mode:', state?.profileMode || 'none');
    console.error('Run: node ~/.openclaw/scripts/browser_tool.js start --session atlas');
    process.exit(1);
  }

  console.log('Connecting to Atlas Chrome via CDP...');
  // Connect once — reconnect page per-pin since Pinterest closes the creation tab after publish
  const { browser } = await connectBrowser();
  const ctx = browser.contexts()[0];

  async function getFreshPage() {
    // Find an open Pinterest tab or open a new one
    const existing = ctx.pages().find(p => !p.isClosed() && p.url().includes('pinterest.com') && !p.url().includes('/login'));
    return existing || ctx.newPage();
  }

  let posted = 0, failed = 0;
  try {
    for (let i = 0; i < pins.length; i++) {
      const pin = pins[i];
      try {
        const page = await getFreshPage();
        const success = await postPin(page, pin);
        if (success) {
          log.posted.push(pin.id);
          posted++;
          console.log(`  POSTED (${posted}/${pins.length})`);
        } else {
          // "No confirmation" may still mean success — Pinterest closes the creation tab after publish
          // Log as posted but flag for manual verification
          log.posted.push(pin.id);
          posted++;
          console.log(`  POSTED (unconfirmed — verify on Pinterest manually)`);
        }
      } catch (err) {
        log.failed.push({ id: pin.id, reason: err.message, time: new Date().toISOString() });
        failed++;
        console.log(`  FAILED: ${err.message}`);
      }
      saveLog(log);
      if (i < pins.length - 1) {
        const wait = 30 + Math.random() * 30;
        console.log(`  Waiting ${Math.round(wait)}s before next pin...`);
        await delay(wait);
      }
    }
  } finally {
    await browser.close();
  }

  console.log(`\nDone. Posted: ${posted}, Failed: ${failed}`);
  console.log(`Log: ${LOG_PATH}`);
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
