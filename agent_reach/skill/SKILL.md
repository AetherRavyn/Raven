---
name: agent-reach
description: >
  Give your AI agent eyes to see the entire internet.
  Search and read 16 platforms plus any web page: Twitter/X, Reddit, YouTube,
  GitHub, Bilibili, Xiaohongshu, Douyin, Weibo, WeChat Articles, Xiaoyuzhou Podcast,
  LinkedIn, V2EX, Xueqiu, RSS, and Exa web search.
  Zero-config for 8 channels. Use when the user asks to search, read, or interact
  with any supported platform, shares a URL, or asks for web search.
  Triggers: "search Twitter", "search Xiaohongshu", "watch a video", "search",
  "search the web", "look this up", "Bilibili", "Douyin videos", "WeChat articles",
  "official account", "Weibo", "V2EX", "Xiaoyuzhou", "podcast", "Xueqiu",
  "stock quote", "web search", "research", "help me install".
metadata:
  openclaw:
    homepage: https://github.com/Panniantong/Agent-Reach
---

# Agent Reach Usage Guide

Upstream tools for 16 platforms plus any web page. Call them directly.

Run `agent-reach doctor` to check which channels are available.

## ⚠️ Workspace Rules

**Never create files in the agent workspace.** Use `/tmp/` for temporary output and `~/.agent-reach/` for persistent data.

## Web - Any URL

```bash
curl -s "https://r.jina.ai/URL"
```

## Web Search (Exa)

```bash
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'
mcporter call 'exa.get_code_context_exa(query: "code question", tokensNum: 3000)'
```

## Twitter/X (bird)

```bash
bird search "query" -n 10                  # search
bird read URL_OR_ID                        # read a post (supports /status/ and /article/ URLs)
bird user-tweets @username -n 20           # user timeline
bird thread URL_OR_ID                      # full thread
```

## YouTube (yt-dlp)

```bash
yt-dlp --dump-json "URL"                     # video metadata
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "URL"
                                              # download subtitles, then read the .vtt file
yt-dlp --dump-json "ytsearch5:query"         # search
```

## Bilibili (yt-dlp)

```bash
yt-dlp --dump-json "https://www.bilibili.com/video/BVxxx"
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --convert-subs vtt --skip-download -o "/tmp/%(id)s" "URL"
```

> Server IPs may get 412. Use `--cookies-from-browser chrome` or configure a proxy.

## Reddit

```bash
curl -s "https://www.reddit.com/r/SUBREDDIT/hot.json?limit=10" -H "User-Agent: agent-reach/1.0"
curl -s "https://www.reddit.com/search.json?q=QUERY&limit=10" -H "User-Agent: agent-reach/1.0"
```

> Server IPs may get 403. Use Exa for search instead, or configure a proxy.

## GitHub (gh CLI)

```bash
gh search repos "query" --sort stars --limit 10
gh repo view owner/repo
gh search code "query" --language python
gh issue list -R owner/repo --state open
gh issue view 123 -R owner/repo
```

## Xiaohongshu (mcporter)

```bash
mcporter call 'xiaohongshu.search_feeds(keyword: "query")'
mcporter call 'xiaohongshu.get_feed_detail(feed_id: "xxx", xsec_token: "yyy")'
mcporter call 'xiaohongshu.get_feed_detail(feed_id: "xxx", xsec_token: "yyy", load_all_comments: true)'
mcporter call 'xiaohongshu.publish_content(title: "title", content: "body", images: ["/path/img.jpg"], tags: ["tag"])'
```

> Requires login. Use Cookie-Editor to import cookies.

> **Tip: Clean bloated output.** The XHS API returns large JSON with many unused fields.
> Pipe it through the formatter to save context:
> ```bash
> mcporter call 'xiaohongshu.search_feeds(keyword: "query")' | agent-reach format xhs
> ```
> This keeps only: title, content, author, engagement counts, image URLs, and tags.

## Douyin (mcporter)

```bash
mcporter call 'douyin.parse_douyin_video_info(share_link: "https://v.douyin.com/xxx/")'
mcporter call 'douyin.get_douyin_download_link(share_link: "https://v.douyin.com/xxx/")'
```

> No login needed.

## WeChat Articles

**Search** (miku_ai):
```bash
# miku_ai is installed inside the agent-reach Python environment.
# Use the same interpreter that runs agent-reach (handles pipx / venv installs):
AGENT_REACH_PYTHON=$(python3 -c "import agent_reach, sys; print(sys.executable)" 2>/dev/null || echo python3)
$AGENT_REACH_PYTHON -c "
import asyncio
from miku_ai import get_wexin_article
async def s():
    for a in await get_wexin_article('query', 5):
        print(f'{a["title"]} | {a["url"]}')
asyncio.run(s())
"
```

**Read** (Camoufox - bypasses WeChat anti-bot):
```bash
cd ~/.agent-reach/tools/wechat-article-for-ai && python3 main.py "https://mp.weixin.qq.com/s/ARTICLE_ID"
```

> WeChat articles cannot be read with Jina Reader or curl. Camoufox is required.

## Weibo (mcporter)

```bash
# Trending topics
mcporter call 'weibo.get_trendings(limit: 20)'

# Search users
mcporter call 'weibo.search_users(keyword: "Lei Jun", limit: 10)'

# Get user profile
mcporter call 'weibo.get_profile(uid: "1195230310")'

# Get user feeds
mcporter call 'weibo.get_feeds(uid: "1195230310", limit: 20)'

# Get hot user posts
mcporter call 'weibo.get_hot_feeds(uid: "1195230310", limit: 10)'

# Search posts
mcporter call 'weibo.search_content(keyword: "artificial intelligence", limit: 20)'

# Search topics
mcporter call 'weibo.search_topics(keyword: "AI", limit: 10)'

# Get comments
mcporter call 'weibo.get_comments(mid: "5099916367123456", limit: 50)'

# Get fans list
mcporter call 'weibo.get_fans(uid: "1195230310", limit: 20)'

# Get following list
mcporter call 'weibo.get_followers(uid: "1195230310", limit: 20)'
```

> Zero config. No login needed. Uses the mobile API with auto visitor cookies.

## Xiaoyuzhou Podcast (groq-whisper + ffmpeg)

```bash
# Transcribe a single episode (outputs text to /tmp/)
~/.agent-reach/tools/xiaoyuzhou/transcribe.sh "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID"
```

> Requires ffmpeg + Groq API key (free).  
> Set the key: `agent-reach configure groq-key YOUR_KEY`  
> First run installs the tool: `agent-reach install --env=auto`  
> Run `agent-reach doctor` to check status.  
> Markdown output is saved to `/tmp/` by default.

## LinkedIn (mcporter)

```bash
mcporter call 'linkedin.get_person_profile(linkedin_url: "https://linkedin.com/in/username")'
mcporter call 'linkedin.search_people(keyword: "AI engineer", limit: 10)'
```

Fallback: `curl -s "https://r.jina.ai/https://linkedin.com/in/username"`

## V2EX (public API)

```bash
# Hot topics
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"

# Node topics (node_name such as python, tech, jobs, qna)
curl -s "https://www.v2ex.com/api/topics/show.json?node_name=python&page=1" -H "User-Agent: agent-reach/1.0"

# Topic details (topic_id from URL, e.g. https://www.v2ex.com/t/1234567)
curl -s "https://www.v2ex.com/api/topics/show.json?id=TOPIC_ID" -H "User-Agent: agent-reach/1.0"

# Replies
curl -s "https://www.v2ex.com/api/replies/show.json?topic_id=TOPIC_ID&page=1" -H "User-Agent: agent-reach/1.0"

# User info
curl -s "https://www.v2ex.com/api/members/show.json?username=USERNAME" -H "User-Agent: agent-reach/1.0"
```

Python example (V2EXChannel):

```python
from agent_reach.channels.v2ex import V2EXChannel

ch = V2EXChannel()

# Get hot topics (default 20)
# Returned fields: id, title, url, replies, node_name, node_title, content (first 200 chars), created
topics = ch.get_hot_topics(limit=10)
for t in topics:
    print(f"[{t['node_title']}] {t['title']} ({t['replies']} replies) {t['url']}")
    print(f"  id={t['id']} created={t['created']}")

# Get the latest topics for a node
# Returned fields: id, title, url, replies, node_name, node_title, content (first 200 chars), created
node_topics = ch.get_node_topics("python", limit=5)
for t in node_topics:
    print(t["id"], t["title"], t["url"])

# Get a single topic's details + replies
# Returned fields: id, title, url, content, replies_count, node_name, node_title,
#           author, created, replies (list of {author, content, created})
topic = ch.get_topic(1234567)
print(topic["title"], "—", topic["author"])
for r in topic["replies"]:
    print(f"  {r['author']}: {r['content'][:80]}")

# Get user info
# Returned fields: id, username, url, website, twitter, psn, github, btc, location, bio, avatar, created
user = ch.get_user("Livid")
print(user["username"], user["bio"], user["github"])

# Search (the V2EX public API does not support search, so this returns an explanation)
result = ch.search("asyncio")
print(result[0]["error"])  # suggests on-site search or the Exa channel
```

> No auth required. Results are public JSON. V2EX node names are listed at https://www.v2ex.com/planes

## Xueqiu (public API)

```python
from agent_reach.channels.xueqiu import XueqiuChannel

ch = XueqiuChannel()

# Get a stock quote (symbol format: SH600519 for Shanghai, SZ000858 for Shenzhen, AAPL for US, 00700 for Hong Kong)
# Returned fields: symbol, name, current, percent, chg, high, low, open, last_close,
#                  volume, amount, market_capital, turnover_rate, pe_ttm, timestamp
quote = ch.get_stock_quote("SH600519")
print(f"{quote['name']} ({quote['symbol']}): {quote['current']} ({quote['percent']}%)")

# Search stocks
# Returned fields: symbol, name, exchange
stocks = ch.search_stock("Maotai", limit=5)
for s in stocks:
    print(f"{s['name']} ({s['symbol']}) - {s['exchange']}")

# Hot posts
# Returned fields: id, title, text (first 200 chars), author, likes, url
posts = ch.get_hot_posts(limit=10)
for p in posts:
    print(f"{p['author']}: {p['text'][:50]}... ({p['likes']} likes)")

# Hot stocks (stock_type=10 popularity ranking, stock_type=12 follow ranking)
# Returned fields: symbol, name, current, percent, rank
hot = ch.get_hot_stocks(limit=10, stock_type=10)
for s in hot:
    print(f"#{s['rank']} {s['name']} ({s['symbol']}): {s['current']} ({s['percent']}%)")
```

> No login required. Session cookies are obtained automatically, and all public APIs can be used directly.

## RSS (feedparser)

## RSS

```python
python3 -c "
import feedparser
for e in feedparser.parse('FEED_URL').entries[:5]:
    print(f'{e.title} — {e.link}')
"
```

## Troubleshooting

- **Channel not working?** Run `agent-reach doctor` to see status and fix instructions.
- **Twitter fetch failed?** Make sure `undici` is installed: `npm install -g undici`. Configure a proxy: `agent-reach configure proxy URL`.

## Setting Up a Channel ("help me configure XXX")

If a channel needs setup (cookies, Docker, etc.), fetch the installation guide:
https://raw.githubusercontent.com/Panniantong/agent-reach/main/docs/install.md

The user only provides cookies. Everything else is handled by the agent.
