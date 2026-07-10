#!/usr/bin/env node
/**
 * Browser Tool — General-purpose Playwright browser for OpenClaw agents
 *
 * Architecture:
 *   - "start" launches Chromium via Playwright with a persistent user data dir
 *     and --remote-debugging-port. Chrome owns all contexts/pages — they persist
 *     between tool calls because each action connects via CDP, does its work,
 *     and disconnects. Chrome stays running.
 *   - "stop" kills the Chrome process
 *   - Every action returns JSON to stdout
 *
 * Usage (agents call via exec):
 *   node browser_tool.js start [--headless] [--session <name>]   # Named sessions persist logins
 *   node browser_tool.js sessions                               # List saved sessions
 *   node browser_tool.js navigate --url "https://example.com"
 *   node browser_tool.js read [--selector "div.content"] [--limit 5]
 *   node browser_tool.js click --selector "button.submit"
 *   node browser_tool.js type --selector "input[name=email]" --text "hello@brand75.com"
 *   node browser_tool.js screenshot [--path /tmp/shot.png] [--selector "div.main"]
 *   node browser_tool.js scroll [--direction down] [--amount 500]
 *   node browser_tool.js extract --selector "a" --attribute "href" [--limit 20]
 *   node browser_tool.js eval --js "document.title"
 *   node browser_tool.js tabs
 *   node browser_tool.js tab --index 1
 *   node browser_tool.js wait --selector "div.loaded" [--timeout 10000]
 *   node browser_tool.js stop
 *   node browser_tool.js status
 */

const { chromium } = require('playwright');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const net = require('net');
const http = require('http');

const STATE_DIR = path.join(process.env.HOME, '.openclaw/data/browser');
const STATE_FILE = path.join(STATE_DIR, 'server-state.json');
const PROFILE_DIR = path.join(process.env.HOME, '.openclaw/data/browser/profiles');
const ATLAS_PROFILE_DIR = 'Profile 9';
const SCREENSHOT_DIR = path.join(process.env.HOME, '.openclaw/workspace/browser_screenshots');
// Named sessions persist logins. Use: --session facebook, --session brand75
// First launch requires manual login. After that, cookies persist across restarts.

// Ensure directories exist
[STATE_DIR, PROFILE_DIR, SCREENSHOT_DIR].forEach(d => {
  fs.mkdirSync(d, { recursive: true });
});

function out(data) {
  console.log(JSON.stringify(data, null, 2));
}

function fail(msg, details) {
  out({ ok: false, error: msg, ...(details || {}) });
  process.exit(1);
}

function parseArgs(argv) {
  const args = { _action: argv[0] };
  for (let i = 1; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith('--')) {
        args[key] = true;
      } else {
        args[key] = next;
        i++;
      }
    }
  }
  return args;
}

function readState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8')); } catch { return null; }
}

function writeState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function clearState() {
  try { fs.unlinkSync(STATE_FILE); } catch {}
}

function isAlive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

// Wait for Chrome's debugging port to respond
function waitForDebugPort(port, timeoutMs = 10000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    function check() {
      if (Date.now() - start > timeoutMs) return reject(new Error('Chrome debug port timeout'));
      const req = http.get(`http://127.0.0.1:${port}/json/version`, (res) => {
        let body = '';
        res.on('data', d => body += d);
        res.on('end', () => {
          try {
            const info = JSON.parse(body);
            resolve(info);
          } catch { setTimeout(check, 200); }
        });
      });
      req.on('error', () => setTimeout(check, 200));
      req.end();
    }
    check();
  });
}

// Connect to running Chrome via CDP
async function connectBrowser() {
  const state = readState();
  if (!state || !state.debugPort) {
    fail('Browser not running. Start it first: node browser_tool.js start');
  }
  if (state.pid && !isAlive(state.pid)) {
    clearState();
    fail('Chrome process died. Restart with: node browser_tool.js start');
  }
  try {
    const browser = await chromium.connectOverCDP(`http://127.0.0.1:${state.debugPort}`);
    // Mark as externally-connected so Playwright won't send Browser.close on exit
    browser._isConnectedOverCDP = true;
    browser._shouldCloseOnDisconnect = false;
    return { browser, state };
  } catch (e) {
    fail('Cannot connect to Chrome. It may have crashed.', { detail: e.message });
  }
}

// Get the active page (last page of default context)
async function getActivePage(browser) {
  const contexts = browser.contexts();
  if (contexts.length === 0) {
    fail('No browser context available');
  }
  // Use the default context (first one — this is Chrome's main profile context)
  const ctx = contexts[0];
  const pages = ctx.pages();
  if (pages.length === 0) {
    return await ctx.newPage();
  }
  return pages[pages.length - 1];
}

function truncate(text, maxLen = 500) {
  if (!text) return '';
  text = text.trim().replace(/\s+/g, ' ');
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

// ============ ACTIONS ============

async function actionStart(args) {
  const existing = readState();
  if (existing && existing.pid && isAlive(existing.pid)) {
    out({ ok: true, action: 'start', message: 'Browser already running', pid: existing.pid, session: existing.session });
    return;
  }

  const sessionName = args.session || 'atlas';
  if (sessionName === 'atlas-live' || args.profile === 'atlas-live') {
    fail('atlas-live mode removed. Use --session atlas (isolated profile at data/browser/profiles/atlas-host-chrome).');
  }
  const headless = !!args.headless;
  const requestedProfile = args.profile || (sessionName === 'atlas' ? 'atlas' : 'isolated');

  let browserPath, profilePath;

  if (requestedProfile === 'atlas') {
    browserPath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
    profilePath = path.join(PROFILE_DIR, 'atlas-host-chrome');
    fs.mkdirSync(profilePath, { recursive: true });
  } else {
    browserPath = chromium.executablePath();
    profilePath = path.join(PROFILE_DIR, sessionName);
    fs.mkdirSync(profilePath, { recursive: true });
  }

  const debugPort = await findFreePort();

  const chromeArgs = [
    `--remote-debugging-port=${debugPort}`,
    '--disable-blink-features=AutomationControlled',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
  ];

  chromeArgs.push(`--user-data-dir=${profilePath}`);
  if (requestedProfile === 'atlas') {
    chromeArgs.push(`--profile-directory=${ATLAS_PROFILE_DIR}`);
    chromeArgs.push(`--disk-cache-dir=${path.join(STATE_DIR, 'cache-atlas')}`);
  }

  if (headless) chromeArgs.push('--headless=new');

  // Launch browser as detached process
  const child = spawn(browserPath, chromeArgs, {
    detached: true,
    stdio: 'ignore',
  });
  child.unref();

  // Wait for debug port to be ready
  try {
    const info = await waitForDebugPort(debugPort, 15000);
    const stateData = {
      pid: child.pid,
      debugPort,
      session: sessionName,
      headless,
      profilePath,
      profileMode: requestedProfile,
      profileDirectory: requestedProfile === 'atlas' ? ATLAS_PROFILE_DIR : null,
      startedAt: new Date().toISOString(),
      browser: info.Browser || 'Chromium',
    };
    writeState(stateData);
    out({ ok: true, action: 'start', ...stateData });
  } catch (e) {
    try { process.kill(child.pid, 'SIGTERM'); } catch {}
    fail('Browser failed to start', { detail: e.message });
  }
}

async function actionSessions() {
  const sessions = {};
  if (fs.existsSync(PROFILE_DIR)) {
    for (const dir of fs.readdirSync(PROFILE_DIR)) {
      const fullPath = path.join(PROFILE_DIR, dir);
      if (fs.statSync(fullPath).isDirectory()) {
        const hasCookies = fs.existsSync(path.join(fullPath, 'Default', 'Cookies')) || fs.existsSync(path.join(fullPath, 'Cookies'));
        sessions[dir] = { path: fullPath, hasLoginData: hasCookies };
      }
    }
  }
  out({ ok: true, action: 'sessions', sessions, usage: 'node browser_tool.js start --session <name>' });
}

async function actionStop() {
  const state = readState();
  if (!state || !state.pid) {
    clearState();
    out({ ok: true, action: 'stop', message: 'No browser running' });
    return;
  }

  try { process.kill(state.pid, 'SIGTERM'); } catch {}
  clearState();
  out({ ok: true, action: 'stop', message: 'Browser stopped', session: state.session });
}

async function actionStatus() {
  const state = readState();
  if (!state || !state.pid) {
    out({ ok: true, action: 'status', running: false });
    return;
  }
  if (!isAlive(state.pid)) {
    clearState();
    out({ ok: true, action: 'status', running: false, message: 'Chrome process dead, state cleaned up' });
    return;
  }
  try {
    const browser = await chromium.connectOverCDP(`http://127.0.0.1:${state.debugPort}`);
    const contexts = browser.contexts();
    const allPages = [];
    for (const ctx of contexts) {
      for (const page of ctx.pages()) {
        const title = await page.title().catch(() => '');
        allPages.push({ url: page.url(), title });
      }
    }
    /* CDP detach — intentionally no browser.close() */
    out({
      ok: true, action: 'status', running: true,
      pid: state.pid, session: state.session, headless: state.headless,
      startedAt: state.startedAt, tabs: allPages.length, pages: allPages,
    });
  } catch (e) {
    out({ ok: true, action: 'status', running: true, pid: state.pid, error: e.message });
  }
}

async function actionNavigate(args) {
  if (!args.url) fail('--url required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const timeout = parseInt(args.timeout) || 30000;
  await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout });
  const title = await page.title();
  const url = page.url();
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'navigate', url, title });
}

async function actionRead(args) {
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const selector = args.selector || 'body';
  const limit = parseInt(args.limit) || 10;

  try { await page.waitForSelector(selector, { timeout: 5000 }); } catch {}

  const elements = await page.$$(selector);
  const results = [];
  const count = Math.min(elements.length, limit);

  for (let i = 0; i < count; i++) {
    const text = await elements[i].innerText().catch(() => '');
    const tag = await elements[i].evaluate(el => el.tagName.toLowerCase()).catch(() => '');
    results.push({ index: i, tag, text: truncate(text, 300) });
  }

  const url = page.url();
  const title = await page.title();
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'read', url, title, selector, count: elements.length, showing: count, results });
}

async function actionClick(args) {
  if (!args.selector) fail('--selector required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const timeout = parseInt(args.timeout) || 10000;
  await page.waitForSelector(args.selector, { timeout });
  await page.click(args.selector);
  await page.waitForTimeout(1000);

  const url = page.url();
  const title = await page.title();
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'click', selector: args.selector, url, title });
}

async function actionType(args) {
  if (!args.selector) fail('--selector required');
  if (!args.text) fail('--text required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const timeout = parseInt(args.timeout) || 10000;
  await page.waitForSelector(args.selector, { timeout });

  if (args.clear) {
    await page.click(args.selector, { clickCount: 3 });
  }
  await page.type(args.selector, args.text, { delay: parseInt(args.delay) || 50 });
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'type', selector: args.selector, typed: args.text.length + ' chars' });
}

async function actionScreenshot(args) {
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const filePath = args.path || path.join(SCREENSHOT_DIR, `screenshot-${timestamp}.png`);

  if (args.selector) {
    const el = await page.$(args.selector);
    if (!el) fail('Selector not found: ' + args.selector);
    await el.screenshot({ path: filePath });
  } else {
    await page.screenshot({ path: filePath, fullPage: !!args.fullpage });
  }

  const url = page.url();
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'screenshot', path: filePath, url });
}

async function actionScroll(args) {
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const amount = parseInt(args.amount) || 500;
  const direction = args.direction || 'down';
  const delta = direction === 'up' ? -amount : amount;

  await page.mouse.wheel(0, delta);
  await page.waitForTimeout(500);
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'scroll', direction, amount });
}

async function actionExtract(args) {
  if (!args.selector) fail('--selector required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const attribute = args.attribute || 'textContent';
  const limit = parseInt(args.limit) || 20;

  const elements = await page.$$(args.selector);
  const results = [];
  const count = Math.min(elements.length, limit);

  for (let i = 0; i < count; i++) {
    let value;
    if (attribute === 'textContent' || attribute === 'text') {
      value = await elements[i].innerText().catch(() => '');
      value = truncate(value, 200);
    } else {
      value = await elements[i].getAttribute(attribute).catch(() => null);
    }
    results.push({ index: i, [attribute]: value });
  }
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'extract', selector: args.selector, attribute, count: elements.length, showing: count, results });
}

async function actionEval(args) {
  if (!args.js) fail('--js required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const result = await page.evaluate(args.js);
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'eval', result });
}

async function actionTabs() {
  const { browser } = await connectBrowser();
  const contexts = browser.contexts();
  const tabs = [];
  for (const ctx of contexts) {
    for (const page of ctx.pages()) {
      const title = await page.title().catch(() => '');
      tabs.push({ url: page.url(), title });
    }
  }
  /* CDP detach — intentionally no browser.close() */
  out({ ok: true, action: 'tabs', tabs });
}

async function actionTab(args) {
  const index = parseInt(args.index);
  if (isNaN(index)) fail('--index required (number)');
  const { browser } = await connectBrowser();
  const pages = [];
  for (const ctx of browser.contexts()) {
    pages.push(...ctx.pages());
  }
  if (index < 0 || index >= pages.length) fail(`Tab index ${index} out of range (0-${pages.length - 1})`);

  await pages[index].bringToFront();
  const url = pages[index].url();
  const title = await pages[index].title();
  /* CDP detach — intentionally no browser.close() */

  out({ ok: true, action: 'tab', index, url, title });
}

async function actionWait(args) {
  if (!args.selector) fail('--selector required');
  const { browser } = await connectBrowser();
  const page = await getActivePage(browser);

  const timeout = parseInt(args.timeout) || 10000;
  try {
    await page.waitForSelector(args.selector, { timeout });
    /* CDP detach — intentionally no browser.close() */
    out({ ok: true, action: 'wait', selector: args.selector, found: true });
  } catch {
    /* CDP detach — intentionally no browser.close() */
    out({ ok: true, action: 'wait', selector: args.selector, found: false, message: `Selector not found within ${timeout}ms` });
  }
}

// ============ MAIN ============

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0) {
    fail('No action specified. Use: start, stop, status, navigate, read, click, type, screenshot, scroll, extract, eval, tabs, tab, wait, sessions');
  }

  const args = parseArgs(argv);
  const action = args._action;

  const actions = {
    start: actionStart, stop: actionStop, status: actionStatus,
    navigate: actionNavigate, read: actionRead, click: actionClick,
    type: actionType, screenshot: actionScreenshot, scroll: actionScroll,
    extract: actionExtract, eval: actionEval, tabs: actionTabs,
    tab: actionTab, wait: actionWait, sessions: actionSessions,
  };

  if (!actions[action]) {
    fail(`Unknown action: ${action}. Available: ${Object.keys(actions).join(', ')}`);
  }

  try {
    await actions[action](args);
    process.exit(0);
  } catch (e) {
    fail(`Action "${action}" failed: ${e.message}`);
  }
}

main();
