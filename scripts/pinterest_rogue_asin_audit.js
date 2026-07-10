#!/usr/bin/env node
/**
 * Pinterest Rogue ASIN Audit — read-only.
 *
 * Lists all pins on all 5 boards, extracts ASINs from destination URLs,
 * flags:
 *   - any occurrence of the rogue ASIN EXAMPLE_ASIN
 *   - any pin whose ASIN doesn't match a manifest entry
 *   - pins with no link or missing board
 */
const fs = require('fs');
const path = require('path');
const https = require('https');

const HOME = process.env.HOME;
const TOKEN_PATH = path.join(HOME, '.openclaw', 'credentials', 'pinterest', 'token.json');
const MANIFEST_PATH = path.join(HOME, '.openclaw', 'workspace', 'pinterest_posting_manifest.json');
const BOARDS_PATH = path.join(HOME, '.openclaw', 'credentials', 'pinterest', 'board_ids.json');
const OUTPUT_PATH = path.join(HOME, '.openclaw', 'workspace', 'pinterest_rogue_asin_audit.json');

const ROGUE_ASIN = 'EXAMPLE_ASIN';

function apiGet(url, token) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { Authorization: `Bearer ${token}` } }, (res) => {
      let body = '';
      res.on('data', c => body += c);
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

async function getPin(pinId, token) {
  return apiGet(`https://api.pinterest.com/v5/pins/${pinId}`, token);
}

function asinFromUrl(url) {
  if (!url) return null;
  const m = url.match(/\/dp\/([A-Z0-9]{10})/i);
  return m ? m[1].toUpperCase() : null;
}

(async () => {
  const token = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')).access_token;
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));
  const boardIds = JSON.parse(fs.readFileSync(BOARDS_PATH, 'utf8'));

  const manifestAsins = new Set(manifest.pins.map(p => p.asin).filter(Boolean));
  const manifestByAsin = Object.fromEntries(manifest.pins.map(p => [p.asin, p]));

  const allPins = [];
  for (const [boardKey, boardId] of Object.entries(boardIds)) {
    try {
      const pins = await listBoardPins(boardId, token);
      console.log(`board ${boardKey} (${boardId}): ${pins.length} pins`);
      for (const p of pins) {
        // Pin list endpoint may omit some fields — fetch full pin object for each.
        let full = p;
        try { full = await getPin(p.id, token); } catch (_) {}
        const asin = asinFromUrl(full.link);
        allPins.push({
          pinterest_pin_id: full.id,
          pinterest_pin_url: `https://www.pinterest.com/pin/${full.id}/`,
          board_key: boardKey,
          board_id: full.board_id || boardId,
          board_section_id: full.board_section_id || null,
          title: full.title || null,
          link: full.link || null,
          asin,
          is_rogue_target: asin === ROGUE_ASIN,
          asin_in_manifest: asin ? manifestAsins.has(asin) : false,
          expected_board_for_asin: asin && manifestByAsin[asin] ? manifestByAsin[asin].board_key : null,
          board_matches_manifest: asin && manifestByAsin[asin] ? manifestByAsin[asin].board_key === boardKey : null,
          has_board: Boolean(full.board_id),
          parent_pin_id: full.parent_pin_id || null,
          pin_metrics: full.pin_metrics || null,
          note: full.note || null,
          created_at: full.created_at || null,
        });
      }
    } catch (e) {
      console.error(`board ${boardKey} failed:`, e.message);
    }
  }

  const rogue_hits = allPins.filter(p => p.is_rogue_target);
  const asin_mismatches = allPins.filter(p => p.asin && !p.asin_in_manifest);
  const wrong_board = allPins.filter(p => p.asin && p.asin_in_manifest && p.board_matches_manifest === false);
  const no_link = allPins.filter(p => !p.link);
  const no_asin = allPins.filter(p => p.link && !p.asin);

  const out = {
    generated_at: new Date().toISOString(),
    rogue_asin_searched: ROGUE_ASIN,
    totals: {
      pins: allPins.length,
      rogue_asin_hits: rogue_hits.length,
      asin_not_in_manifest: asin_mismatches.length,
      wrong_board_for_asin: wrong_board.length,
      pins_with_no_link: no_link.length,
      pins_with_link_but_no_asin: no_asin.length,
    },
    rogue_hits,
    asin_mismatches,
    wrong_board,
    no_link,
    no_asin,
    all_pins: allPins,
  };
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(out.totals, null, 2));
  console.log(`\nReport: ${OUTPUT_PATH}`);
})().catch(e => { console.error(e); process.exit(1); });
