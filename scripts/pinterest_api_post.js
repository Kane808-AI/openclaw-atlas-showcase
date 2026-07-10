#!/usr/bin/env node
/**
 * Pinterest API poster — v5 API, OAuth 2.0
 *
 * One-time auth:
 *   node pinterest_api_post.js --auth
 * Post all pending pins:
 *   node pinterest_api_post.js
 * Post a single pin:
 *   node pinterest_api_post.js --pin board3_product5
 * Dry run:
 *   node pinterest_api_post.js --dry-run
 */
const fs = require('fs');
const path = require('path');
const http = require('http');
const { exec } = require('child_process');

const CLIENT_ID = 'SHOWCASE_PINTEREST_CLIENT_ID';
const CLIENT_SECRET = 'REDACTED_SET_VIA_ENV';
const REDIRECT_URI = 'http://localhost:8085/callback';
const SCOPES = 'boards:read,boards:write,pins:read,pins:write,user_accounts:read';
const TOKEN_PATH = path.join(__dirname, '..', 'credentials', 'pinterest', 'token.json');
const MANIFEST_PATH = path.join(__dirname, '..', 'workspace', 'pinterest_posting_manifest.json');
const LOG_PATH = path.join(__dirname, '..', 'workspace', 'pinterest_post_log.json');

// ── OAuth flow ────────────────────────────────────────────────────────────────

async function runOAuthFlow() {
  const authUrl = `https://www.pinterest.com/oauth/?response_type=code&client_id=${CLIENT_ID}&redirect_uri=${encodeURIComponent(REDIRECT_URI)}&scope=${encodeURIComponent(SCOPES)}&state=openclaw`;

  const codePromise = new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const u = new URL(req.url, 'http://localhost:8085');
      if (u.pathname !== '/callback') { res.writeHead(404); res.end(); return; }
      const code = u.searchParams.get('code');
      const error = u.searchParams.get('error');
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(`<html><body style="font-family:sans-serif;padding:40px"><h2>${code ? 'Success! You can close this tab.' : 'Error: ' + error}</h2></body></html>`);
      server.close();
      code ? resolve(code) : reject(new Error('OAuth error: ' + error));
    });
    server.listen(8085, () => console.log('Waiting for OAuth callback on http://localhost:8085/callback...'));
    setTimeout(() => { server.close(); reject(new Error('OAuth timeout')); }, 300000);
  });

  console.log('\nOpen this URL in atlas Chrome (the one logged into your Pinterest account):\n');
  console.log(authUrl);
  console.log('\nAttempting to open automatically...\n');
  exec(`open -a "Google Chrome" "${authUrl}"`);

  const code = await codePromise;
  console.log('Got authorization code. Exchanging for token...');

  const auth = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
  const body = `grant_type=authorization_code&code=${code}&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`;
  const res = await fetch('https://api.pinterest.com/v5/oauth/token', {
    method: 'POST',
    headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const token = await res.json();
  if (!token.access_token) throw new Error('Token exchange failed: ' + JSON.stringify(token));
  token.client_id = CLIENT_ID;
  token.obtained_at = new Date().toISOString();
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(token, null, 2));
  console.log(`Token saved. Scopes: ${token.scope}`);
  return token;
}

async function refreshToken(creds) {
  const auth = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64');
  const res = await fetch('https://api.pinterest.com/v5/oauth/token', {
    method: 'POST',
    headers: { 'Authorization': `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `grant_type=refresh_token&refresh_token=${encodeURIComponent(creds.refresh_token)}`,
  });
  const token = await res.json();
  if (!token.access_token) return null;
  const merged = { ...creds, ...token, obtained_at: new Date().toISOString() };
  fs.writeFileSync(TOKEN_PATH, JSON.stringify(merged, null, 2));
  return merged;
}

async function getValidToken() {
  let creds;
  try { creds = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf-8')); }
  catch { return await runOAuthFlow(); }

  // Quick probe: try /user_account
  const probe = await fetch('https://api.pinterest.com/v5/user_account', {
    headers: { 'Authorization': `Bearer ${creds.access_token}` }
  });
  if (probe.ok) return creds;

  // Try refresh
  const refreshed = await refreshToken(creds);
  if (refreshed) return refreshed;

  // Fall back to fresh OAuth
  return await runOAuthFlow();
}

// ── Pinterest API ─────────────────────────────────────────────────────────────

async function api(token, method, endpoint, body) {
  const res = await fetch(`https://api.pinterest.com/v5${endpoint}`, {
    method,
    headers: {
      'Authorization': `Bearer ${token.access_token}`,
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`API ${method} ${endpoint} → ${res.status}: ${JSON.stringify(json)}`);
  return json;
}

async function listBoards(token) {
  const all = [];
  let bookmark;
  do {
    const q = bookmark ? `?bookmark=${bookmark}&page_size=50` : '?page_size=50';
    const r = await api(token, 'GET', `/boards${q}`);
    all.push(...r.items);
    bookmark = r.bookmark;
  } while (bookmark);
  return all;
}

async function findOrCreateBoard(token, boardName) {
  const boards = await listBoards(token);
  const found = boards.find(b => b.name.toLowerCase() === boardName.toLowerCase());
  if (found) return found.id;
  console.log(`  Board "${boardName}" not found — creating`);
  const created = await api(token, 'POST', '/boards', { name: boardName });
  return created.id;
}

function imageToBase64(imgPath) {
  const abs = imgPath.replace('~', process.env.HOME);
  const buf = fs.readFileSync(abs);
  const ext = path.extname(abs).slice(1).toLowerCase();
  const mime = ext === 'jpg' ? 'image/jpeg' : `image/${ext}`;
  return { mime, data: buf.toString('base64') };
}

async function createPin(token, boardId, pin) {
  const img = imageToBase64(pin.image_file);
  const body = {
    board_id: boardId,
    title: pin.title.slice(0, 100),
    description: [pin.description, '', (pin.hashtags || []).join(' ')].join('\n').slice(0, 800),
    link: pin.affiliate_url,
    media_source: {
      source_type: 'image_base64',
      content_type: img.mime,
      data: img.data,
    },
  };
  return await api(token, 'POST', '/pins', body);
}

// ── Log helpers ───────────────────────────────────────────────────────────────

function loadLog() {
  try { return JSON.parse(fs.readFileSync(LOG_PATH, 'utf-8')); }
  catch { return { posted: [], failed: [], skipped: [] }; }
}
function saveLog(log) { fs.writeFileSync(LOG_PATH, JSON.stringify(log, null, 2)); }

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--auth')) { await runOAuthFlow(); console.log('Auth complete.'); return; }

  const pinFilter = args.includes('--pin') ? args[args.indexOf('--pin') + 1] : null;
  const dryRun = args.includes('--dry-run');

  const token = await getValidToken();
  console.log('Token valid. Scopes:', token.scope);

  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
  const log = loadLog();
  const posted = new Set(log.posted);

  let pins = manifest.pins.filter(p => !posted.has(p.id));
  if (pinFilter) pins = pins.filter(p => p.id === pinFilter);
  console.log(`Pins to post: ${pins.length}`);

  if (dryRun) { pins.forEach(p => console.log(`  [DRY] ${p.id}: ${p.title.slice(0, 60)}`)); return; }

  const BOARD_NAMES = {
    ai_smart_home: 'AI & Smart Home Gadgets',
    home_office: 'Home Office & Desk Setup Essentials',
    audio_recording: 'Audio & Recording Gear',
    tech_gifts_dads: 'Tech Gifts for Dads',
    portable_power: 'Portable Power & On-the-Go Tech',
  };
  const boardIdCache = {};

  for (const pin of pins) {
    console.log(`\nPosting: ${pin.id} — ${pin.title.slice(0, 60)}`);
    try {
      const boardName = BOARD_NAMES[pin.board_key] || pin.board_key;
      if (!boardIdCache[boardName]) boardIdCache[boardName] = await findOrCreateBoard(token, boardName);
      const result = await createPin(token, boardIdCache[boardName], pin);
      console.log(`  ✓ Posted: ${result.id}`);
      log.posted.push(pin.id);
      log.failed = (log.failed || []).filter(f => (f.id || f) !== pin.id);
      saveLog(log);
      await new Promise(r => setTimeout(r, 2000));
    } catch (e) {
      console.error(`  ✗ FAILED: ${e.message.slice(0, 200)}`);
      log.failed = log.failed || [];
      log.failed.push({ id: pin.id, reason: e.message, time: new Date().toISOString() });
      saveLog(log);
    }
  }
  console.log(`\nDone. Posted: ${log.posted.length}, Failed: ${(log.failed || []).length}`);
}

main().catch(e => { console.error('Fatal:', e.message); process.exit(1); });
