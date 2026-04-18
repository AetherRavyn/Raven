# Xiaohongshu Setup Guide

## What It Does
Read and search Xiaohongshu notes through [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) (over 9K stars, Go-based, with a built-in Chrome browser).

## Prerequisites
- Docker, for running the xiaohongshu-mcp service
- mcporter CLI, the MCP bridge tool

## Steps the agent can do automatically

### 1. Install mcporter
```bash
npm install -g mcporter
```

### 2. Start the xiaohongshu-mcp service
```bash
docker run -d \
  --name xiaohongshu-mcp \
  -p 18060:18060 \
  xpzouying/xiaohongshu-mcp
```

> If you need a proxy (recommended for server deployments):
> ```bash
> docker run -d \
>   --name xiaohongshu-mcp \
>   -p 18060:18060 \
>   -e XHS_PROXY=http://user:pass@ip:port \
>   xpzouying/xiaohongshu-mcp
> ```

### 3. Register it with mcporter
```bash
mcporter config add xiaohongshu http://localhost:18060/mcp
```

### 4. Verify
```bash
agent-reach doctor
```

You should see Xiaohongshu reported as ✅ or ⚠️ (MCP connected but not logged in).

## Steps the user must do manually

If `doctor` shows "MCP connected but not logged in":

> Xiaohongshu requires a one-time login (it will remember the session afterward).
>
> Open http://localhost:18060 and use the Xiaohongshu mobile app to scan the QR code and log in.
> After login, cookies are saved automatically inside the Docker container and usually stay valid for 1 to 3 months.

## Common Questions

**Q: Cookies disappeared after restarting the Docker container?**
A: Mount a volume for persistence:
```bash
docker run -d \
  --name xiaohongshu-mcp \
  -p 18060:18060 \
  -v xhs-data:/app/data \
  xpzouying/xiaohongshu-mcp
```

**Q: Xiaohongshu shows IP risk on a server?**
A: Add a proxy with `-e XHS_PROXY=http://user:pass@ip:port`. A residential proxy is recommended.

**Q: Does the Docker image support ARM64 / Apple Silicon?**
A: The upstream image does not yet have ARM64 support. Two options:

Option 1: Run with Rosetta emulation (recommended, easiest)
```bash
docker run -d \
  --name xiaohongshu-mcp \
  -p 18060:18060 \
  --platform linux/amd64 \
  xpzouying/xiaohongshu-mcp
```

Option 2: Build a native ARM64 image from source
```bash
git clone https://github.com/xpzouying/xiaohongshu-mcp
cd xiaohongshu-mcp
docker build -t xiaohongshu-mcp .
docker run -d --name xiaohongshu-mcp -p 18060:18060 xiaohongshu-mcp
```

**Q: I do not want to use Docker?**
A: You can build from source: https://github.com/xpzouying/xiaohongshu-mcp
