# Clyan — AI-driven Disk Cleaner

A command-line disk cleaning tool designed to be driven by AI agents via CLI or MCP protocol.

## Features

- **26+ cache providers**: npm, pip, cargo, Go, Docker, IDE caches, browser caches, Windows system caches
- **Duplicate file detection**: 3-phase (size → partial hash → full hash)
- **Windows deep cleaning**: WinSxS, Windows.old, Driver Store, Delivery Optimization, DISM
- **Three-tier safety**: Safe / Caution / Unsafe classification with protected path system
- **Recycle bin + undo**: All deletions go to recycle bin by default, with SQLite history
- **MCP server**: AI agents can call tools directly via Model Context Protocol
- **Parallel fast mode**: ThreadPoolExecutor for concurrent deletion

## Quick Start

```bash
pip install -e .
clyan scan quick C:\
clyan scan dev-garbage C:\ --min-size-mb 100
clyan clean --items items.json --dry-run
clyan clean --items items.json --fast
```

## Commands

| Command | Description |
|---------|-------------|
| `scan space <path>` | Directory space analysis |
| `scan dev-garbage <path>` | Developer cache garbage |
| `scan browsers` | Browser caches |
| `scan system` | Windows temp + recycle bin |
| `scan duplicates <path>` | Duplicate file detection |
| `scan quick <path>` | All scans combined |
| `clean --items <file>` | Preview or execute cleanup |
| `history` | View cleanup history |
| `undo <id>` | Mark operation as undone |
| `mcp` | Start MCP server |

## MCP Server

Start the MCP server for AI agent integration:

```bash
clyan mcp
```

The server exposes all scan and clean operations as MCP tools via stdio transport.
