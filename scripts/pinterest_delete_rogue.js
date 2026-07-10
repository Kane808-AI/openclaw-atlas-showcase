#!/usr/bin/env node
/**
 * Delete 6 rogue Pinterest pins — safety-gated by ASIN match.
 * For each pin:
 *   1. GET /v5/pins/{id}
 *   2. Verify the link contains the expected rogue ASIN
 *   3. DELETE /v5/pins/{id}
 *   4. Log result
 * Finally, list board pin counts to confirm return to 25 total.
 */
const fs = require('fs');
const path = require('path');
const https = require('https');

const HOME = process.env.HOME;
const TOKEN_PATH = path.join(HOME, '.openclaw', 'credentials', 'pinterest', 'token.json');
const BOARDS_PATH = path.join(HOME, '.openclaw', 'credentials', 'pinterest', 'board_ids.json');
const LOG_PATH = path.join(HOME, '.openclaw', 'workspace', 'pinterest_rogue_deletion_log.json');

const ROGUES = [
  { pin_id: '502644008433308860', board: 'ai_smart_home',   asin: 'B07D3H6W2P', title: 'Peace of Mind: Smart Sensors for Every Home!' },
  { pin_id: '502644008433308967', board: 'audio_recording', asin: 'B01M0LIEF3', title: 'Budget Mic Kit: Your Recording Journey Starts Here!' },
  { pin_id: '502644008433309025', board: 'tech_gifts_dads', asin: 'B08J62283Q', title: 'Never Lose Anything Again! Tile Mate for Dad' },
  { pin_id: '502644008433309060', board: 'portable_power',  asin: 'B0BZV8V12K', title: 'Tidy Tech Travel: Alpaka Organizer Case!' },
  { pin_id: '502644008433309044', board: 'portable_power',  asin: 'B07D2R2B6S', title: 'Off-Grid Power: BigBlue Solar Panel Charger!' },
  { pin_id: '502644008433309040', board: 'portable_power',  asin: 'B08LH2WCN2', title: 'Power on the Go: Anker Slim 10K Power Bank!' },
];

function request(method, urlStr, token) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const req = https.request({
      method, hostname: u.hostname, path: u.pathname + u.search,
      headers: { Authorization: `Bearer ${token}` }
    }, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => {
        let json = null;
        try { json = body ? JSON.parse(body) : null; } catch (_) {}
        resolve({ status: res.statusCode, body, json });
      });
    });
    req.on('error', reject);
    req.end();
  });
}

(async () => {
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')).access_token;
  const boardIds = JSON.parse(fs.readFileSync(BOARDS_PATH, 'utf8'));
  const log = { started_at: new Date().toISOString(), deletions: [], board_counts_after: {}, summary: {} };

  let ok = 0, skipped = 0, failed = 0;

  for (const r of ROGUES) {
    const entry = { ...r, asin_confirmed: null, get_status: null, delete_status: null, result: null, error: null };
    try {
      const got = await request('GET', `https://api.pinterest.com/v5/pins/${r.pin_id}`, token);
      entry.get_status = got.status;
      if (got.status === 404) {
        entry.result = 'already_deleted';
        entry.asin_confirmed = false;
        skipped++;
        log.deletions.push(entry);
        console.log(`[skip] pin ${r.pin_id} — already gone (404)`);
        continue;
      }
      if (got.status >= 400 || !got.json) {
        entry.result = 'get_failed';
        entry.error = got.body;
        failed++;
        log.deletions.push(entry);
        console.log(`[fail] pin ${r.pin_id} GET ${got.status}`);
        continue;
      }
      const link = got.json.link || '';
      const asinMatch = link.toUpperCase().includes(`/DP/${r.asin.toUpperCase()}`);
      entry.actual_link = link;
      entry.asin_confirmed = asinMatch;
      if (!asinMatch) {
        entry.result = 'safety_abort_asin_mismatch';
        skipped++;
        log.deletions.push(entry);
        console.log(`[abort] pin ${r.pin_id} — ASIN ${r.asin} not in link (${link})`);
        continue;
      }
      const del = await request('DELETE', `https://api.pinterest.com/v5/pins/${r.pin_id}`, token);
      entry.delete_status = del.status;
      if (del.status === 204 || del.status === 200) {
        entry.result = 'deleted';
        ok++;
        console.log(`[ok]   pin ${r.pin_id} deleted (ASIN ${r.asin})`);
      } else {
        entry.result = 'delete_failed';
        entry.error = del.body;
        failed++;
        console.log(`[fail] pin ${r.pin_id} DELETE ${del.status}: ${del.body}`);
      }
    } catch (e) {
      entry.result = 'exception';
      entry.error = e.message;
      failed++;
      console.log(`[err]  pin ${r.pin_id}: ${e.message}`);
    }
    log.deletions.push(entry);
  }

  // Confirm board counts
  console.log('\nRe-checking board counts...');
  let total = 0;
  for (const [key, bid] of Object.entries(boardIds)) {
    const res = await request('GET', `https://api.pinterest.com/v5/boards/${bid}/pins?page_size=100`, token);
    const count = res.json?.items?.length ?? 0;
    log.board_counts_after[key] = count;
    total += count;
    console.log(`  ${key}: ${count}`);
  }
  log.board_counts_after._total = total;
  log.summary = { attempted: ROGUES.length, deleted: ok, skipped, failed, total_pins_after: total };
  log.finished_at = new Date().toISOString();
  fs.writeFileSync(LOG_PATH, JSON.stringify(log, null, 2));
  console.log(`\nSummary: ${ok} deleted, ${skipped} skipped, ${failed} failed. Total pins now: ${total}`);
  console.log(`Log: ${LOG_PATH}`);
})().catch(e => { console.error(e); process.exit(1); });
