import path from 'node:path';
import fs from 'node:fs/promises';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const WORKSPACE = path.resolve(process.env.HOME, '.openclaw/workspace');

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
        path: p,
        size: stat.size,
        isDirectory: stat.isDirectory(),
        modified: stat.mtime,
        created: stat.birthtime
      }, null, 2) }] };
    });

  s.tool('move_file', 'Move or rename a file',
    { source: z.string(), destination: z.string() },
    async ({ source, destination }) => {
      await fs.rename(safePath(source), safePath(destination));
      return { content: [{ type: 'text', text: `Moved: ${source} -> ${destination}` }] };
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
          const full = path.join(d, e.name);
          if (re.test(e.name)) results.push(full.replace(WORKSPACE + '/', ''));
          if (e.isDirectory()) await walk(full, depth + 1);
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

const server = buildMcpServer();
const transport = new StdioServerTransport();
await server.connect(transport);
