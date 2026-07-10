#!/usr/bin/env python3
"""
pattern_search.py — TF-IDF search over Atlas pattern and memory sources.
Zero external dependencies — stdlib only (re, math, collections, pathlib).

Sources indexed:
  1. ~/.openclaw/workspace/memory/PATTERNS.md  — primary pattern store (## [date] Pattern: blocks)
  2. ~/.openclaw/workspace/memory/MEMORY.md    — workspace free-text memory (### sections)
  3. ~/.claude/projects/.../memory/MEMORY.md   — Claude Code auto-memory index + linked files

Usage:
    python3 pattern_search.py "ElevenLabs TikTok transcription failure"
    python3 pattern_search.py "Claude Code session handoff memory"
"""

import sys
import re
import math
from pathlib import Path
from collections import Counter

# Source paths
WORKSPACE_MEMORY = Path.home() / ".openclaw/workspace/memory"
PROCEDURAL_ROOT = WORKSPACE_MEMORY / "procedural"
CLAUDE_MEMORY = Path.home() / ".claude/projects/-Users-chriskaneshiro--openclaw/memory"

TOP_K = 5


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list:
    """Lowercase word tokenizer. Skips tokens under 3 chars."""
    return re.findall(r"\b[a-z][a-z0-9]{2,}\b", text.lower())


# ---------------------------------------------------------------------------
# Parsers — each returns list of (label, full_text) tuples
# ---------------------------------------------------------------------------

def parse_patterns_md(path: Path) -> list:
    """Split on ## headings. Each block becomes a searchable document."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    raw = re.split(r"\n(?=## )", text)
    blocks = []
    for chunk in raw:
        chunk = chunk.strip()
        if not chunk or chunk.startswith("# "):
            continue
        first_line = chunk.split("\n", 1)[0]
        title = first_line.lstrip("#").strip()
        if title:
            blocks.append((f"[PATTERNS] {title}", chunk))
    return blocks


def parse_workspace_memory_md(path: Path) -> list:
    """
    Parse the workspace MEMORY.md (free-text, ### section headings).
    Each ### section becomes a searchable document.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    # Split on ## or ### headings
    raw = re.split(r"\n(?=#{2,3} )", text)
    blocks = []
    for chunk in raw:
        chunk = chunk.strip()
        if not chunk:
            continue
        first_line = chunk.split("\n", 1)[0]
        title = first_line.lstrip("#").strip()
        if title and len(chunk) > 50:
            blocks.append((f"[WORKSPACE-MEM] {title}", chunk))
    return blocks


def parse_procedural_store(root: Path) -> list:
    """ABOS §7 procedural memory: workspace/memory/procedural/<agent>/<task>.md"""
    if not root.exists():
        return []
    blocks = []
    for f in sorted(root.glob("*/*.md")):
        text = f.read_text(encoding="utf-8")
        # Strip frontmatter for indexing but keep agent/task in label
        body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL).strip()
        agent = f.parent.name
        task = f.stem
        label = f"[PROCEDURAL] {agent}/{task}"
        blocks.append((label, f"{agent} {task}\n\n{body}"))
    return blocks


def parse_claude_memory_md(memory_dir: Path) -> list:
    """
    Parse Claude Code auto-memory: reads MEMORY.md index, then loads each
    linked .md file for full content.
    """
    index_path = memory_dir / "MEMORY.md"
    if not index_path.exists():
        return []

    index_text = index_path.read_text(encoding="utf-8")
    blocks = []

    for line in index_text.split("\n"):
        line = line.strip()
        if not line.startswith("- ["):
            continue
        m = re.match(r"- \[([^\]]+)\]\(([^\)]+)\) — (.+)", line)
        if not m:
            continue
        title, filename, summary = m.group(1), m.group(2), m.group(3)

        # Try loading the linked memory file for full content
        mem_file = memory_dir / filename
        if mem_file.exists():
            raw = mem_file.read_text(encoding="utf-8")
            # ABOS §7: exclude source: inference entries from default results
            fm_match = re.match(r"^---\n(.*?)\n---\n", raw, re.DOTALL)
            if fm_match:
                fm = fm_match.group(1)
                src_m = re.search(r"^source:\s*(.+)$", fm, re.MULTILINE)
                if src_m and src_m.group(1).strip() == "inference":
                    continue
            # Strip YAML frontmatter
            content = re.sub(r"^---\n.*?---\n", "", raw, flags=re.DOTALL).strip()
        else:
            content = summary

        label = f"[AUTO-MEM] {title}"
        full_text = f"{title}: {summary}\n\n{content}"
        blocks.append((label, full_text))

    return blocks


# ---------------------------------------------------------------------------
# TF-IDF index + search
# ---------------------------------------------------------------------------

def build_index(docs: list) -> tuple:
    """
    Build TF-IDF index from a list of document strings.
    Returns (vocab, idf, normalized_matrix).
    """
    N = len(docs)
    tokenized = [tokenize(doc) for doc in docs]

    vocab: dict = {}
    for tokens in tokenized:
        for t in tokens:
            if t not in vocab:
                vocab[t] = len(vocab)
    V = len(vocab)

    # Document frequency
    df = [0] * V
    for tokens in tokenized:
        for t in set(tokens):
            if t in vocab:
                df[vocab[t]] += 1

    # Smoothed IDF
    idf = [math.log((N + 1) / (df[i] + 1)) + 1.0 for i in range(V)]

    # TF-IDF vectors, L2-normalized
    matrix = []
    for tokens in tokenized:
        vec = [0.0] * V
        if tokens:
            counts = Counter(tokens)
            total = len(tokens)
            for t, cnt in counts.items():
                if t in vocab:
                    vec[vocab[t]] = (cnt / total) * idf[vocab[t]]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        matrix.append(vec)

    return vocab, idf, matrix


def search(query: str, vocab: dict, idf: list, matrix: list, top_k: int = TOP_K) -> list:
    """Cosine similarity search. Returns [(doc_index, score), ...] descending."""
    V = len(vocab)
    tokens = tokenize(query)
    if not tokens:
        return []

    q_vec = [0.0] * V
    counts = Counter(tokens)
    total = len(tokens)
    for t, cnt in counts.items():
        if t in vocab:
            q_vec[vocab[t]] = (cnt / total) * idf[vocab[t]]

    norm = math.sqrt(sum(x * x for x in q_vec))
    if norm > 0:
        q_vec = [x / norm for x in q_vec]

    scores = []
    for i, doc_vec in enumerate(matrix):
        score = sum(a * b for a, b in zip(q_vec, doc_vec))
        if score > 0:
            scores.append((i, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: pattern_search.py \"your query here\"", file=sys.stderr)
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    # Load all sources
    pattern_blocks = parse_patterns_md(WORKSPACE_MEMORY / "PATTERNS.md")
    workspace_mem_blocks = parse_workspace_memory_md(WORKSPACE_MEMORY / "MEMORY.md")
    procedural_blocks = parse_procedural_store(PROCEDURAL_ROOT)
    claude_mem_blocks = parse_claude_memory_md(CLAUDE_MEMORY)

    all_blocks = pattern_blocks + workspace_mem_blocks + procedural_blocks + claude_mem_blocks

    if not all_blocks:
        print("No patterns or memory entries found.")
        sys.exit(0)

    docs = [content for _, content in all_blocks]
    vocab, idf, matrix = build_index(docs)
    results = search(query, vocab, idf, matrix, top_k=TOP_K)

    n_patterns = len(pattern_blocks)
    n_ws_mem = len(workspace_mem_blocks)
    n_procedural = len(procedural_blocks)
    n_claude = len(claude_mem_blocks)

    if not results:
        print(f"## Pattern Search Results\n\n**Query:** `{query}`\n\nNo relevant patterns found.")
        sys.exit(0)

    print(f"## Pattern Search Results\n\n**Query:** `{query}`\n")
    print(f"*Searched {n_patterns} pattern blocks + {n_ws_mem} workspace memory sections + {n_procedural} procedural recipes + {n_claude} auto-memory entries*\n")
    print("---\n")

    for rank, (idx, score) in enumerate(results, 1):
        title, content = all_blocks[idx]
        print(f"### Result {rank} — {title}")
        print(f"*Relevance: {score:.3f}*\n")
        # Trim very long blocks to stay readable
        if len(content) > 1200:
            content = content[:1200] + "\n\n*[truncated — full content in source file]*"
        print(content)
        print("\n---\n")


if __name__ == "__main__":
    main()
