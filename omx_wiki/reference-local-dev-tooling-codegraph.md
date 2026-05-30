# Reference: Local Dev Tooling - CodeGraph

Category: reference
Tags: tooling, codegraph, local-index, mcp, code-intelligence

## Purpose

This page records the local CodeGraph setup for this repo. CodeGraph is a
developer/agent assistance tool, not an application runtime dependency.

## Current Setup

- Installed binary: `/Users/mac/.local/bin/codegraph`
- Installed version: `0.9.7`
- Project index directory: `.codegraph/`
- `.codegraph/` is ignored by git and should not be committed.
- Codex MCP configuration is enabled globally via `/Users/mac/.codex/config.toml`
  with an absolute `codegraph` command path.

## Index Status At Setup

Initial index command:

```bash
/Users/mac/.local/bin/codegraph init -i
```

Initial status after indexing:

- Files: 227
- Nodes: 4,463
- Edges: 11,240
- Indexed source files: 212
- Backend: built-in `node:sqlite`

## Basic Commands

```bash
/Users/mac/.local/bin/codegraph status
/Users/mac/.local/bin/codegraph query AnalysisContextPack
/Users/mac/.local/bin/codegraph context "where is Alert Center built?"
/Users/mac/.local/bin/codegraph impact build_analysis_context_pack
```

Use CodeGraph for repository exploration, impact analysis, and planning before
cross-module changes. Keep authoritative implementation checks in source files
and tests.

## MCP Configuration

The active Codex MCP server entry is:

```toml
[mcp_servers.codegraph]
type = "stdio"
command = "/Users/mac/.local/bin/codegraph"
args = ["serve", "--mcp"]
enabled = true
startup_timeout_sec = 10
```

The MCP server is expected to be available in new Codex sessions after the
config is reloaded. Do not let tool-generated global instructions override this
repo's `AGENTS.md` or ASX wiki protocol.
