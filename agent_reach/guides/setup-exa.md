# Exa Search Setup Guide

## What It Does
Exa is an AI semantic search engine. Through MCP integration, it is **free and requires no API key**. Once configured, it unlocks:
- Web-wide semantic search
- Reddit search (via site:reddit.com)
- Twitter search (via site:x.com)

## Steps the agent can do automatically

`agent-reach install --env=auto` completes the following steps automatically in most cases, so manual setup is usually unnecessary.

### 1. Install mcporter
```bash
npm install -g mcporter
```

### 2. Register the Exa MCP
```bash
mcporter config add exa https://mcp.exa.ai/mcp
```

### 3. Verify
```bash
agent-reach doctor | grep "Search"
mcporter call 'exa.web_search_exa(query: "test", numResults: 1)'
```

## Steps the user must do manually

**None.** Exa connects through MCP and is free, requires no signup, and no API key.

If `agent-reach install` could not configure Exa automatically because of network issues, run the two commands above manually.

## Common Questions

**Q: Is there a search limit?**
A: The MCP endpoint is served directly by Exa (mcp.exa.ai). It is currently free and unlimited. If that changes in the future, agent-reach will adapt in a later update.

**Q: What is mcporter?**
A: It is a command-line bridge for the MCP protocol used to call MCP servers. Agent Reach uses it to connect to Exa and Xiaohongshu.
