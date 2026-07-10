#!/usr/bin/env node
/**
 * Pinterest Pin Link Audit — read-only.
 *
 * Uses Pinterest API v5 to list pins per board and extract the
 * destination `link` field. Matches each API pin to our manifest by title,
 * then by ASIN/description, and compares `link` to the expected affiliate_url.
 *
 * Does NOT navigate to or click any destination URL.
 *
 * Output: ~/.openclaw/workspace/pinterest_link_audit.json
 */
const fs = require('fs');
const path = require('path');
const https = require('https');

const TOKEN_PATH = path.join(process.env.HOME, '.openclaw', 'credentials', 'pinterest', 'token.json');
const MANIFEST_PATH = path.join(process.env.HOME, '.openclaw', 'workspace', 'pinterest_posting_manifest.json');
const OUTPUT_PATH = path.join(process.env.HOME, '.openclaw', 'workspace', 'pinterest_link_audit.json');

function apiGet(url, token) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { Authorization: `Bearer ${token}` } }, (res) => {
      let body = '';
      res.on('data', (c) => body += c);
      res.on('end', () => {
        try {
          const json = JSON.parse(body);
          if (res.statusCode >= 400) return reject(new Error(`HTTP ${res.statusCode}: ${body}`));
          resolve(json);
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function listBoardPins(boardId, token) {
  const pins = [];
  let bookmark = null;
  for (let i = 0; i < 10; i++) {
    const url = `https://api.pinterest.com/v5/boards/${boardId}/pins?page_size=100${bookmark ? `&bookmark=${encodeURIComponent(bookmark)}` : ''}`;
    const res = await apiGet(url, token);
    if (Array.isArray(res.items)) pins.push(...res.items);
    bookmark = res.bookmark;
    if (!bookmark) break;
  }
  return pins;
}

function norm(s) { return (s || '').trim().toLowerCase(); }

(async () => {
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')).access_token;
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));

  const boardIds = [...new Set(manifest.pins.map(p => p.board_id))];
  const pinsByBoard = {};
  for (const bid of boardIds) {
    try {
      pinsByBoard[bid] = await listBoardPins(bid, token);
      console.log(`board ${bid}: ${pinsByBoard[bid].length} pins fetched`);
    } catch (e) {
      console.error(`board ${bid} fetch failed:`, e.message);
      pinsByBoard[bid] = [];
    }
  }

  const report = [];
  let matches = 0, mismatches = 0, unchecked = 0;
  const claimed = new Set();

  // Pass 1: exact/contains title, desc, ASIN match
  const resolved = new Map();
  for (const m of manifest.pins) {
    const boardPins = pinsByBoard[m.board_id] || [];
    const titleNorm = norm(m.title);
    const descNorm = norm(m.description);
    let cand = boardPins.find(p => !claimed.has(p.id) && norm(p.title) === titleNorm);
    if (!cand) cand = boardPins.find(p => !claimed.has(p.id) && titleNorm && (norm(p.title).includes(titleNorm) || titleNorm.includes(norm(p.title))));
    if (!cand) cand = boardPins.find(p => !claimed.has(p.id) && norm(p.description) === descNorm);
    if (!cand && m.asin) cand = boardPins.find(p => !claimed.has(p.id) && (p.link || '').includes(m.asin));
    if (cand) { claimed.add(cand.id); resolved.set(m.id, cand); }
  }
  // Pass 2: leftover pins on same board → uncertain match (likely wrong destination)
  for (const m of manifest.pins) {
    if (resolved.has(m.id)) continue;
    const boardPins = pinsByBoard[m.board_id] || [];
    const leftover = boardPins.find(p => !claimed.has(p.id));
    if (leftover) { claimed.add(leftover.id); resolved.set(m.id, { ...leftover, __leftover: true }); }
  }

  for (const m of manifest.pins) {
    const candidate = resolved.get(m.id);

    const entry = {
      pin_id: m.id,
      expected_url: m.affiliate_url,
      actual_url: null,
      match: false,
      notes: ''
    };

    if (!candidate) {
      entry.notes = 'pin URL not found';
      unchecked++;
    } else {
      entry.actual_url = candidate.link || null;
      entry.pinterest_pin_id = candidate.id;
      entry.pinterest_pin_url = `https://www.pinterest.com/pin/${candidate.id}/`;
      entry.pin_title = candidate.title || null;
      if (candidate.__leftover) entry.notes = 'weak match: only leftover pin on this board — verify manually. ';
      if (!entry.actual_url) {
        entry.notes = 'pin has no destination link set';
        mismatches++;
      } else if (entry.actual_url === m.affiliate_url) {
        entry.match = true;
        matches++;
      } else {
        entry.match = false;
        mismatches++;
        const expectedAsin = m.asin;
        if (expectedAsin && entry.actual_url.includes(expectedAsin)) {
          entry.notes += 'ASIN matches but tag/query differs';
        } else if (!entry.actual_url.includes('amazon.com')) {
          entry.notes += 'destination is not amazon.com';
        } else {
          entry.notes += 'wrong product (ASIN mismatch)';
        }
      }
    }
    report.push(entry);
  }

  const out = {
    generated_at: new Date().toISOString(),
    total: manifest.pins.length,
    matches,
    mismatches,
    unchecked,
    pins: report
  };
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(out, null, 2));
  console.log(`\nAudit complete: ${matches} match, ${mismatches} mismatch, ${unchecked} unchecked (of ${manifest.pins.length})`);
  console.log(`Report: ${OUTPUT_PATH}`);
})().catch(e => { console.error(e); process.exit(1); });
