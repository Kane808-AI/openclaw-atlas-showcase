import { randomUUID, createHash, randomBytes } from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs/promises';
import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createMcpExpressApp } from '@modelcontextprotocol/sdk/server/express.js';
import { z } from 'zod';

const WORKSPACE = path.resolve(process.env.HOME, '.openclaw/workspace');
const TOKEN = process.env.VAULT_MCP_AUTH_TOKEN;
const CLIENT_ID = process.env.VAULT_MCP_CLIENT_ID;
const CLIENT_SECRET = process.env.VAULT_MCP_CLIENT_SECRET;
const PORT = 13337;
const PUBLIC_HOST = process.env.VAULT_MCP_PUBLIC_HOST || 'chriss-mac-mini.tailnet.example.ts.net';
// The OAuth authorization server lives at the domain root — claude.ai's MCP
// connector constructs /authorize and /oauth/token from the hostname only,
// ignoring any path component in the metadata. So we host OAuth at root and
// the MCP resource under /vault-mcp.
const AUTH_SERVER_URL = `https://${PUBLIC_HOST}`;
const RESOURCE_URL = `${AUTH_SERVER_URL}/vault-mcp`;
const PUBLIC_URL = RESOURCE_URL; // back-compat for existing log lines

if (!TOKEN || !CLIENT_ID || !CLIENT_SECRET) {
  console.error('FATAL: VAULT_MCP_AUTH_TOKEN, VAULT_MCP_CLIENT_ID, VAULT_MCP_CLIENT_SECRET must all be set');
  process.exit(1);
}

// Reject any path that escapes the workspace root
function safePath(p) {
  const full = path.resolve(WORKSPACE, p);
  if (full !== WORKSPACE && !full.startsWith(WORKSPACE + '/')) {
    throw new Error(`Path outside workspace: ${p}`);
  }
  return full;
}

function buildMcpServer() {
  const s = new McpServer({ name: 'vault', version: '1.0.0' });

  s.tool('read_file', 'Read a file from the workspace',
    { path: z.string().describe('Path relative to workspace root') },
    async ({ path: p }) => {
      const content = await fs.readFile(safePath(p), 'utf-8');
      return { content: [{ type: 'text', text: content }] };
    });

  s.tool('write_file', 'Write content to a workspace file (creates parent dirs)',
    { path: z.string(), content: z.string() },
    async ({ path: p, content }) => {
      const full = safePath(p);
      await fs.mkdir(path.dirname(full), { recursive: true });
      await fs.writeFile(full, content, 'utf-8');
      return { content: [{ type: 'text', text: `Written: ${p}` }] };
    });

  s.tool('list_directory', 'List workspace directory contents',
    { path: z.string().default('.') },
    async ({ path: p }) => {
      const entries = await fs.readdir(safePath(p), { withFileTypes: true });
      const lines = entries.map(e => `${e.isDirectory() ? '[dir] ' : '[file]'} ${e.name}`);
      return { content: [{ type: 'text', text: lines.join('\n') || '(empty)' }] };
    });

  s.tool('create_directory', 'Create a directory (and parents)',
    { path: z.string() },
    async ({ path: p }) => {
      await fs.mkdir(safePath(p), { recursive: true });
      return { content: [{ type: 'text', text: `Created: ${p}` }] };
    });

  s.tool('get_file_info', 'Get file/directory metadata',
    { path: z.string() },
    async ({ path: p }) => {
      const stat = await fs.stat(safePath(p));
      return { content: [{ type: 'text', text: JSON.stringify({
        path: p, size: stat.size, isDirectory: stat.isDirectory(),
        modified: stat.mtime, created: stat.birthtime
      }, null, 2) }] };
    });

  s.tool('move_file', 'Move or rename a file',
    { source: z.string(), destination: z.string() },
    async ({ source, destination }) => {
      await fs.rename(safePath(source), safePath(destination));
      return { content: [{ type: 'text', text: `Moved: ${source} → ${destination}` }] };
    });

  s.tool('delete_file', 'Delete a file or empty directory',
    { path: z.string() },
    async ({ path: p }) => {
      const full = safePath(p);
      const stat = await fs.stat(full);
      if (stat.isDirectory()) {
        await fs.rmdir(full);
      } else {
        await fs.unlink(full);
      }
      return { content: [{ type: 'text', text: `Deleted: ${p}` }] };
    });

  s.tool('search_files', 'Search for files/directories matching a name pattern (regex)',
    { directory: z.string().default('.'), pattern: z.string() },
    async ({ directory, pattern }) => {
      const base = safePath(directory);
      const re = new RegExp(pattern, 'i');
      const results = [];
      async function walk(d, depth) {
        if (depth > 5 || results.length >= 100) return;
        const entries = await fs.readdir(d, { withFileTypes: true }).catch(() => []);
        for (const e of entries) {
          if (e.name.startsWith('.')) continue;
          if (re.test(e.name)) results.push(path.join(d, e.name).replace(WORKSPACE + '/', ''));
          if (e.isDirectory()) await walk(path.join(d, e.name), depth + 1);
        }
      }
      await walk(base, 0);
      return { content: [{ type: 'text', text: results.join('\n') || 'No matches' }] };
    });

  s.tool('read_multiple_files', 'Read several workspace files at once',
    { paths: z.array(z.string()).max(20) },
    async ({ paths }) => {
      const parts = await Promise.all(paths.map(async p => {
        try {
          const content = await fs.readFile(safePath(p), 'utf-8');
          return `=== ${p} ===\n${content}`;
        } catch (e) {
          return `=== ${p} === ERROR: ${e.message}`;
        }
      }));
      return { content: [{ type: 'text', text: parts.join('\n\n') }] };
    });

  return s;
}

// Session map: sessionId → StreamableHTTPServerTransport
const sessions = new Map();

const TAILSCALE_HOST = 'chriss-mac-mini.tailnet.example.ts.net';
const app = createMcpExpressApp({
  host: '127.0.0.1',
  allowedHosts: ['127.0.0.1', `127.0.0.1:${PORT}`, 'localhost', TAILSCALE_HOST]
});

// Parse application/x-www-form-urlencoded for the OAuth token endpoint
// (createMcpExpressApp only adds express.json(), not urlencoded)
app.use(express.urlencoded({ extended: false }));

// CORS + OPTIONS preflight handling. Must come BEFORE the auth middleware
// AND before app.all('/mcp') — otherwise OPTIONS reaches the MCP transport,
// which only handles GET/POST/DELETE and returns 405 for everything else.
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers',
    'Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID');
  res.setHeader('Access-Control-Expose-Headers',
    'Mcp-Session-Id, WWW-Authenticate');
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Max-Age', '86400');
  if (req.method === 'OPTIONS') {
    res.status(204).end();
    return;
  }
  next();
});

// OAuth 2.0 Authorization Server metadata — RFC 8414 discovery.
// Issuer + endpoints are at the DOMAIN ROOT, not /vault-mcp — claude.ai
// ignores path components when constructing OAuth URLs from the hostname.
app.get('/.well-known/oauth-authorization-server', (req, res) => {
  res.json({
    issuer: AUTH_SERVER_URL,
    authorization_endpoint: `${AUTH_SERVER_URL}/authorize`,
    token_endpoint: `${AUTH_SERVER_URL}/oauth/token`,
    grant_types_supported: ['authorization_code'],
    response_types_supported: ['code'],
    code_challenge_methods_supported: ['S256'],
    token_endpoint_auth_methods_supported: ['client_secret_post', 'client_secret_basic'],
    scopes_supported: ['mcp']
  });
});

// RFC 9728 — Protected Resource Metadata.
// The resource (MCP server) is at /vault-mcp; the auth server is at root.
// RFC 9728 §3.1 says clients MAY form the metadata URL by appending the
// resource's path to /.well-known/oauth-protected-resource. Claude.ai uses
// the full MCP URL (/vault-mcp/mcp) as the resource, so serve all variants.
function protectedResourceMetadata(req, res) {
  res.json({
    resource: RESOURCE_URL,
    authorization_servers: [AUTH_SERVER_URL],
    bearer_methods_supported: ['header']
  });
}
app.get('/.well-known/oauth-protected-resource', protectedResourceMetadata);
app.get('/.well-known/oauth-protected-resource/vault-mcp', protectedResourceMetadata);
app.get('/.well-known/oauth-protected-resource/vault-mcp/mcp', protectedResourceMetadata);

// ------------------------------------------------------------
// OAuth 2.1 Authorization Code + PKCE flow
// ------------------------------------------------------------
// Single-user setup: only Chris's claude.ai instance will ever authorize here.
// We skip the consent screen and silently issue a code on /authorize — PKCE
// plus the pre-registered client_secret are what keep this safe.

// In-memory one-time authorization codes: code -> { code_challenge, redirect_uri, expires, client_id }
const authCodes = new Map();
const AUTH_CODE_TTL_MS = 10 * 60 * 1000; // 10 minutes per OAuth 2.1 §4.1.3

// Reject any redirect_uri that isn't HTTPS on a claude domain — defense in depth.
function isAllowedRedirect(uri) {
  try {
    const u = new URL(uri);
    if (u.protocol !== 'https:') return false;
    return u.hostname === 'claude.ai'
        || u.hostname === 'claude.com'
        || u.hostname.endsWith('.claude.ai')
        || u.hostname.endsWith('.claude.com')
        || u.hostname.endsWith('.anthropic.com');
  } catch { return false; }
}

// GET /authorize — step 1 of the auth code flow.
// Tailscale strips /vault-mcp, so external /vault-mcp/authorize -> /authorize here.
app.get('/authorize', (req, res) => {
  const {
    response_type, client_id, redirect_uri, state,
    code_challenge, code_challenge_method
  } = req.query;

  if (response_type !== 'code') {
    return res.status(400).json({ error: 'unsupported_response_type' });
  }
  if (client_id !== CLIENT_ID) {
    return res.status(400).json({ error: 'invalid_client' });
  }
  if (!redirect_uri || !isAllowedRedirect(redirect_uri)) {
    // Don't redirect for invalid redirect_uri — per RFC 6749 §4.1.2.1
    return res.status(400).json({ error: 'invalid_request', error_description: 'invalid redirect_uri' });
  }
  if (!code_challenge || code_challenge_method !== 'S256') {
    const u = new URL(redirect_uri);
    u.searchParams.set('error', 'invalid_request');
    u.searchParams.set('error_description', 'S256 PKCE code_challenge required');
    if (state) u.searchParams.set('state', state);
    return res.redirect(302, u.toString());
  }

  // Mint a code and stash the challenge so /token can verify the verifier.
  const code = randomBytes(32).toString('base64url');
  authCodes.set(code, {
    code_challenge,
    redirect_uri,
    client_id,
    expires: Date.now() + AUTH_CODE_TTL_MS
  });

  const u = new URL(redirect_uri);
  u.searchParams.set('code', code);
  if (state) u.searchParams.set('state', state);
  console.log(`Issued auth code for ${client_id} -> ${u.hostname}`);
  res.redirect(302, u.toString());
});

// POST /oauth/token — supports authorization_code (primary) + client_credentials (legacy/curl testing)
// Supports client_secret_post (body) and client_secret_basic (header) auth.
app.post('/oauth/token', (req, res) => {
  const body = req.body || {};
  let { client_id, client_secret } = body;
  const grant_type = body.grant_type;

  // Fall back to Basic auth header if credentials not in body
  const authHeader = req.headers['authorization'] || '';
  if ((!client_id || !client_secret) && authHeader.startsWith('Basic ')) {
    try {
      const decoded = Buffer.from(authHeader.slice(6), 'base64').toString('utf-8');
      const idx = decoded.indexOf(':');
      if (idx > -1) {
        client_id = decodeURIComponent(decoded.slice(0, idx));
        client_secret = decodeURIComponent(decoded.slice(idx + 1));
      }
    } catch { /* ignore */ }
  }

  if (client_id !== CLIENT_ID || client_secret !== CLIENT_SECRET) {
    return res.status(401).json({ error: 'invalid_client' });
  }

  if (grant_type === 'authorization_code') {
    const { code, code_verifier, redirect_uri } = body;
    if (!code || !code_verifier) {
      return res.status(400).json({ error: 'invalid_request', error_description: 'code and code_verifier required' });
    }
    const entry = authCodes.get(code);
    if (!entry || entry.expires < Date.now()) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'code expired or unknown' });
    }
    // Single-use — delete regardless of outcome
    authCodes.delete(code);
    if (redirect_uri && redirect_uri !== entry.redirect_uri) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'redirect_uri mismatch' });
    }
    // PKCE S256 verify: base64url(sha256(code_verifier)) must equal code_challenge
    const expected = createHash('sha256').update(code_verifier).digest('base64url');
    if (expected !== entry.code_challenge) {
      return res.status(400).json({ error: 'invalid_grant', error_description: 'PKCE verification failed' });
    }
    return res.json({ access_token: TOKEN, token_type: 'Bearer', expires_in: 86400 });
  }

  // Kept for curl-based smoke tests. Not advertised in discovery metadata.
  if (grant_type === 'client_credentials') {
    return res.json({ access_token: TOKEN, token_type: 'Bearer', expires_in: 86400 });
  }

  return res.status(400).json({ error: 'unsupported_grant_type' });
});

// Opportunistic cleanup of expired auth codes (cheap, in-memory)
setInterval(() => {
  const now = Date.now();
  for (const [code, entry] of authCodes) {
    if (entry.expires < now) authCodes.delete(code);
  }
}, 60 * 1000).unref();

// Bearer auth on all remaining routes (OPTIONS already short-circuited above)
app.use((req, res, next) => {
  const auth = req.headers['authorization'];
  if (!auth || auth !== `Bearer ${TOKEN}`) {
    // Include WWW-Authenticate so OAuth clients know where to get a token
    res.setHeader('WWW-Authenticate',
      `Bearer realm="${PUBLIC_URL}", error="unauthorized", ` +
      `error_description="Bearer token required"` );
    res.status(401).json({ error: 'Unauthorized' });
    return;
  }
  next();
});

// MCP endpoint — all methods
app.all('/mcp', async (req, res) => {
  try {
    const sessionId = req.headers['mcp-session-id'];

    if (sessionId) {
      const transport = sessions.get(sessionId);
      if (!transport) { res.status(404).json({ error: 'Session not found' }); return; }
      await transport.handleRequest(req, res, req.body);
      return;
    }

    // New session
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (id) => {
        sessions.set(id, transport);
        transport.onclose = () => {
          sessions.delete(id);
          console.log(`Session closed: ${id} (active: ${sessions.size})`);
        };
        console.log(`Session opened: ${id} (active: ${sessions.size})`);
      }
    });

    const mcpServer = buildMcpServer();
    await mcpServer.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error('Request error:', err.message);
    if (!res.headersSent) res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, '127.0.0.1', () => {
  console.log(`vault-mcp listening on http://127.0.0.1:${PORT}/mcp`);
  console.log(`workspace: ${WORKSPACE}`);
});
