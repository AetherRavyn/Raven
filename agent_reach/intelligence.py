# -*- coding: utf-8 -*-
"""Free-first internet intelligence helpers for Agent Reach.

The goal is broad, low-cost coverage without paid APIs:
- DuckDuckGo HTML search for general discovery
- Jina Reader for readable page fetches
- GitHub via gh CLI
- YouTube via yt-dlp and transcript extraction
- Reddit via public JSON endpoints (with DDG fallback)
- Xueqiu and V2EX via public APIs / site search

The helpers are intentionally best-effort and fail closed. If a source is not
available locally, it is skipped rather than breaking the whole workflow.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from socket import gethostbyname
from typing import Any, Callable, Iterable, Optional

from agent_reach.config import Config

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    feedparser = None

from agent_reach.channels.v2ex import V2EXChannel
from agent_reach.channels.xueqiu import XueqiuChannel

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class IntelItem:
    source: str
    title: str
    url: str = ""
    snippet: str = ""
    score: float = 0.0
    kind: str = "search"
    author: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FreeInternetIntel:
    """Broad, free-first internet search and reading layer."""

    def __init__(self, config: Config | None = None):
        if config is None:
            self.config = Config()
        else:
            self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a structured coverage report."""
        from agent_reach.doctor import check_all

        channel_status = check_all(self.config)
        free_sources = self._free_sources()
        available = [
            name for name, info in channel_status.items() if info["status"] == "ok"
        ]
        return {
            "success": True,
            "available_channels": available,
            "channels": channel_status,
            "free_sources": free_sources,
            "report": self.coverage_report(channel_status, free_sources),
        }

    def coverage_report(
        self,
        channel_status: dict[str, Any] | None = None,
        free_sources: dict[str, str] | None = None,
    ) -> str:
        from agent_reach.doctor import check_all, format_report

        if channel_status is None:
            channel_status = check_all(self.config)
        if free_sources is None:
            free_sources = self._free_sources()

        lines = [format_report(channel_status), "", "[Free Internet Coverage]"]
        for key, value in free_sources.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def search(
        self,
        query: str,
        limit: int = 8,
        sources: str | Iterable[str] | None = None,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"success": False, "error": "query is required"}

        source_plan = self._resolve_sources(query, sources)
        tasks: list[tuple[str, Callable[[], list[IntelItem]]]] = []

        for source in source_plan:
            if source == "web":
                tasks.append(
                    (source, lambda q=query, l=limit: self._duckduckgo_search(q, l))
                )
            elif source == "exa":
                tasks.append((source, lambda q=query, l=limit: self._exa_search(q, l)))
            elif source == "github":
                tasks.append(
                    (source, lambda q=query, l=limit: self._github_search(q, l))
                )
            elif source == "youtube":
                tasks.append(
                    (source, lambda q=query, l=limit: self._youtube_search(q, l))
                )
            elif source == "reddit":
                tasks.append(
                    (source, lambda q=query, l=limit: self._reddit_search(q, l))
                )
            elif source == "v2ex":
                tasks.append(
                    (
                        source,
                        lambda q=query, l=limit: self._site_search(
                            "v2ex.com", q, l, "v2ex"
                        ),
                    )
                )
            elif source == "xueqiu":
                tasks.append(
                    (source, lambda q=query, l=limit: self._xueqiu_search(q, l))
                )
            elif source == "rss":
                tasks.append(
                    (
                        source,
                        lambda q=query, l=limit: self._site_search(
                            "feedly.com", q, l, "rss"
                        ),
                    )
                )

        collected: list[IntelItem] = []
        if tasks:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(6, len(tasks))
            ) as pool:
                future_map = {pool.submit(func): source for source, func in tasks}
                for future in concurrent.futures.as_completed(future_map):
                    source = future_map[future]
                    try:
                        collected.extend(future.result())
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug(
                            "AgentReach search source failed (%s): %s", source, exc
                        )

        merged = self._rank_and_dedupe(collected, query, limit)
        summary = self._build_summary(query, merged)

        return {
            "success": True,
            "operation": "search",
            "query": query,
            "sources_used": source_plan,
            "count": len(merged),
            "summary": summary,
            "results": [item.to_dict() for item in merged],
            "status": self.status(),
        }

    def discover(
        self,
        query: str,
        limit: int = 8,
        sources: str | Iterable[str] | None = None,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """Search, then read the most relevant pages for deeper context."""
        result = self.search(query=query, limit=limit, sources=sources)
        if not result.get("success"):
            return result

        top_urls = []
        for item in result.get("results", [])[:3]:
            url = (item or {}).get("url") or ""
            if url and url not in top_urls:
                top_urls.append(url)

        reads: list[dict[str, Any]] = []
        for url in top_urls:
            read = self.read(url, max_chars=max_chars)
            if read.get("success"):
                reads.append(read)

        result.update(
            {
                "operation": "discover",
                "reads": reads,
                "summary": self._build_discovery_summary(
                    result.get("results", []), reads
                ),
            }
        )
        return result

    def read(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        url = (url or "").strip()
        if not url:
            return {"success": False, "error": "url is required"}

        parsed = urllib.parse.urlparse(url)
        domain = (parsed.netloc or "").lower()

        if self._is_private_url(url):
            return {
                "success": False,
                "error": f"Blocked private or local URL: {url}",
            }

        if "youtube.com" in domain or "youtu.be" in domain:
            return self._read_youtube(url, max_chars=max_chars)
        if "reddit.com" in domain or "redd.it" in domain:
            return self._read_reddit(url, max_chars=max_chars)
        if "github.com" in domain:
            return self._read_github(url, max_chars=max_chars)
        if "xueqiu.com" in domain:
            return self._read_xueqiu(url, max_chars=max_chars)
        if "v2ex.com" in domain:
            return self._read_v2ex(url, max_chars=max_chars)
        if self._looks_like_feed(url):
            return self._read_rss(url, max_chars=max_chars)

        return self._read_jina(url, max_chars=max_chars)

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    def _resolve_sources(
        self,
        query: str,
        sources: str | Iterable[str] | None,
    ) -> list[str]:
        if sources is None:
            return self._auto_sources(query)

        if isinstance(sources, str):
            raw = re.split(r"[\s,]+", sources.strip())
        else:
            raw = list(sources)

        resolved = [self._normalize_source_token(token) for token in raw]
        resolved = [s for s in resolved if s]
        if not resolved or resolved == ["auto"]:
            return self._auto_sources(query)
        if "all" in resolved:
            return self._auto_sources(query, broad=True)
        return self._unique(resolved)

    def _auto_sources(self, query: str, broad: bool = False) -> list[str]:
        q = query.lower()
        sources = ["web"]

        if self._command_exists("mcporter"):
            sources.insert(0, "exa")

        if broad or any(
            term in q
            for term in (
                "github",
                "repo",
                "code",
                "commit",
                "issue",
                "pr",
                "pull request",
            )
        ):
            sources.append("github")
        if broad or any(
            term in q for term in ("video", "youtube", "watch", "podcast", "episode")
        ):
            sources.append("youtube")
        if broad or any(
            term in q for term in ("reddit", "forum", "thread", "discussion")
        ):
            sources.append("reddit")
        if broad or any(
            term in q
            for term in ("stock", "market", "shares", "ticker", "earnings", "finance")
        ):
            sources.append("xueqiu")
        if broad or any(
            term in q
            for term in ("v2ex", "developer forum", "tech forum", "china tech")
        ):
            sources.append("v2ex")
        if broad or any(term in q for term in ("feed", "rss", "atom", "news", "blog")):
            sources.append("rss")

        return self._unique(sources)

    @staticmethod
    def _normalize_source_token(token: str) -> str | None:
        value = (token or "").strip().lower()
        aliases = {
            "duckduckgo": "web",
            "ddg": "web",
            "web": "web",
            "search": "web",
            "exa": "exa",
            "github": "github",
            "gh": "github",
            "youtube": "youtube",
            "yt": "youtube",
            "reddit": "reddit",
            "rss": "rss",
            "v2ex": "v2ex",
            "xueqiu": "xueqiu",
            "auto": "auto",
            "all": "all",
        }
        return aliases.get(value)

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    # ------------------------------------------------------------------
    # Search providers
    # ------------------------------------------------------------------

    def _duckduckgo_search(
        self, query: str, limit: int, source_name: str = "web"
    ) -> list[IntelItem]:
        # Primary: ddgs package (handles bot challenges automatically)
        try:
            from ddgs import DDGS  # type: ignore

            results = DDGS().text(query, max_results=limit)
            items = [
                IntelItem(
                    source=source_name,
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=self._trim(r.get("body", ""), 300),
                    kind="search",
                )
                for r in results
                if r.get("title") and r.get("href")
            ]
            if items:
                return items[:limit]
        except Exception:
            pass

        # Fallback: raw HTML scraping
        html = self._fetch_text(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=20,
        )
        if not html:
            html = self._fetch_text(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                timeout=20,
            )
        if not html:
            return []

        items: list[IntelItem] = []
        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "html.parser")

            # DDG lite — result links are a.result-link
            for anchor in soup.select("a.result-link"):
                href = self._normalize_result_url(anchor.get("href", ""))
                title = anchor.get_text(" ", strip=True)
                if not href or not title or "duckduckgo.com" in href:
                    continue
                items.append(
                    IntelItem(
                        source=source_name,
                        title=title,
                        url=href,
                        snippet="",
                        kind="search",
                    )
                )
                if len(items) >= limit:
                    break

            # DDG HTML — results in div.result blocks
            if not items:
                for block in soup.select("div.result, div.result__body, .web-result"):
                    anchor = block.select_one("a.result__a, a.result-link, a[href]")
                    if not anchor:
                        continue
                    href_raw = (
                        str(anchor.attrs.get("href", ""))
                        if getattr(anchor, "attrs", None)
                        else ""
                    )
                    href = self._normalize_result_url(href_raw)
                    title = anchor.get_text(" ", strip=True)
                    if not href or not title or "duckduckgo.com" in href:
                        continue
                    snippet_node = block.select_one(
                        ".result__snippet, .snippet, .result-snippet"
                    )
                    snippet = (
                        snippet_node.get_text(" ", strip=True)
                        if snippet_node
                        else ""
                    )
                    items.append(
                        IntelItem(
                            source=source_name,
                            title=title,
                            url=href,
                            snippet=self._trim(snippet, 300),
                            kind="search",
                        )
                    )
                    if len(items) >= limit:
                        break

            # Generic — any <a> with http(s) href
            if not items:
                for anchor in soup.select("a[href]"):
                    href = anchor.get("href", "")
                    if not href.startswith("http") or "duckduckgo.com" in href:
                        continue
                    title = anchor.get_text(" ", strip=True)
                    if not title:
                        continue
                    items.append(
                        IntelItem(
                            source=source_name,
                            title=self._trim(title, 120),
                            url=href,
                            snippet="",
                            kind="search",
                        )
                    )
                    if len(items) >= limit:
                        break

        return items[:limit]

    def _site_search(
        self, domain: str, query: str, limit: int, source_name: str
    ) -> list[IntelItem]:
        return self._duckduckgo_search(
            f"site:{domain} {query}", limit, source_name=source_name
        )

    def _exa_search(self, query: str, limit: int) -> list[IntelItem]:
        if not self._command_exists("mcporter"):
            return []

        call_expr = (
            f"exa.web_search_exa(query: {json.dumps(query)}, numResults: {int(limit)})"
        )
        try:
            proc = subprocess.run(
                ["mcporter", "call", call_expr],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Exa search failed to run: %s", exc)
            return []

        text = (proc.stdout or proc.stderr or "").strip()
        if not text:
            return []

        try:
            payload = json.loads(text)
        except Exception:
            payload = None

        items: list[IntelItem] = []
        if isinstance(payload, list):
            for entry in payload[:limit]:
                if not isinstance(entry, dict):
                    continue
                items.append(
                    IntelItem(
                        source="exa",
                        title=str(
                            entry.get("title") or entry.get("name") or "Exa result"
                        ),
                        url=str(entry.get("url") or entry.get("source_url") or ""),
                        snippet=self._trim(
                            str(entry.get("snippet") or entry.get("description") or ""),
                            300,
                        ),
                        kind="search",
                        metadata={
                            k: v
                            for k, v in entry.items()
                            if k
                            not in {
                                "title",
                                "name",
                                "url",
                                "source_url",
                                "snippet",
                                "description",
                            }
                        },
                    )
                )

        if not items:
            # Best-effort text parsing. If Exa changes output format, still return
            # the raw text as a structured item so the model can inspect it.
            items.append(
                IntelItem(
                    source="exa",
                    title="Exa search results",
                    snippet=self._trim(text, 2000),
                    kind="search",
                    metadata={"raw": self._trim(text, 4000)},
                )
            )

        return items[:limit]

    def _github_search(self, query: str, limit: int) -> list[IntelItem]:
        if not self._command_exists("gh"):
            return self._site_search("github.com", query, limit, "github")

        try:
            proc = subprocess.run(
                [
                    "gh",
                    "search",
                    "repos",
                    query,
                    "--limit",
                    str(limit),
                    "--json",
                    "name,description,url,stargazersCount,updatedAt,language",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("GitHub search failed to run: %s", exc)
            return self._site_search("github.com", query, limit, "github")

        items = self._parse_json_search_results(proc.stdout, source="github")
        if not items:
            return self._site_search("github.com", query, limit, "github")
        return items[:limit]

    def _youtube_search(self, query: str, limit: int) -> list[IntelItem]:
        yt_dlp = shutil.which("yt-dlp")
        if not yt_dlp:
            return self._site_search("youtube.com", query, limit, "youtube")

        try:
            proc = subprocess.run(
                [yt_dlp, "--dump-json", f"ytsearch{limit}:{query}"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("YouTube search failed to run: %s", exc)
            return self._site_search("youtube.com", query, limit, "youtube")

        items = self._parse_ytdlp_json_output(proc.stdout)
        if not items:
            return self._site_search("youtube.com", query, limit, "youtube")
        return items[:limit]

    def _reddit_search(self, query: str, limit: int) -> list[IntelItem]:
        proxy = self._config_get("reddit_proxy") or self._config_get("proxy")
        url = "https://www.reddit.com/search.json"
        params = {
            "q": query,
            "limit": str(limit),
            "sort": "relevance",
            "t": "all",
            "raw_json": "1",
        }
        try:
            text = self._fetch_text(url, params=params, timeout=20, proxy=proxy)
            data = json.loads(text)
            children = (((data or {}).get("data") or {}).get("children") or [])[:limit]
            items: list[IntelItem] = []
            for child in children:
                post = (child or {}).get("data") or {}
                title = str(post.get("title") or "Reddit result")
                permalink = str(post.get("permalink") or "")
                items.append(
                    IntelItem(
                        source="reddit",
                        title=title,
                        url=f"https://www.reddit.com{permalink}"
                        if permalink
                        else str(post.get("url") or ""),
                        snippet=self._trim(
                            str(post.get("selftext") or post.get("snippet") or ""), 300
                        ),
                        author=post.get("author"),
                        published_at=self._reddit_timestamp(post.get("created_utc")),
                        kind="search",
                        metadata={
                            "subreddit": post.get("subreddit"),
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                        },
                    )
                )
            if items:
                return items
        except Exception:
            pass

        return self._site_search("reddit.com", query, limit, "reddit")

    def _xueqiu_search(self, query: str, limit: int) -> list[IntelItem]:
        items: list[IntelItem] = []
        channel = XueqiuChannel()
        try:
            stock_results = channel.search_stock(query, limit=limit)
            for row in stock_results[:limit]:
                symbol = str(row.get("symbol") or row.get("code") or "")
                title = f"{row.get('name') or symbol}".strip()
                snippet = f"{symbol} {row.get('exchange') or ''}".strip()
                items.append(
                    IntelItem(
                        source="xueqiu",
                        title=title or symbol or "Xueqiu result",
                        url=f"https://xueqiu.com/S/{symbol}" if symbol else "",
                        snippet=snippet,
                        kind="search",
                        metadata={"symbol": symbol, "exchange": row.get("exchange")},
                    )
                )
        except Exception as exc:
            logger.debug("Xueqiu stock search failed: %s", exc)

        try:
            hot = channel.get_hot_posts(limit=min(3, limit))
            for row in hot:
                items.append(
                    IntelItem(
                        source="xueqiu",
                        title=str(row.get("title") or row.get("text") or "Hot post"),
                        url=str(row.get("url") or ""),
                        snippet=self._trim(str(row.get("text") or ""), 300),
                        author=row.get("author"),
                        kind="trend",
                        metadata={"likes": row.get("likes")},
                    )
                )
        except Exception as exc:
            logger.debug("Xueqiu hot posts failed: %s", exc)

        if not items:
            items = self._site_search("xueqiu.com", query, limit, "xueqiu")
        return items[:limit]

    # ------------------------------------------------------------------
    # Reading helpers
    # ------------------------------------------------------------------

    def _read_jina(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        reader_url = self._jina_url(url)
        text = self._fetch_text(reader_url, timeout=30)
        if not text:
            return {"success": False, "error": f"Unable to fetch {url}"}

        title = self._infer_title_from_text(text, url)
        content = self._trim(text, max_chars)
        return {
            "success": True,
            "source": "jina",
            "url": url,
            "title": title,
            "content": content,
            "summary": self._summarize_text(content),
            "metadata": {"reader_url": reader_url},
        }

    def _read_github(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        repo = self._github_repo_from_url(url)
        if repo and self._command_exists("gh"):
            try:
                proc = subprocess.run(
                    [
                        "gh",
                        "repo",
                        "view",
                        repo,
                        "--json",
                        "name,description,url,stargazerCount,forkCount,updatedAt,licenseInfo,primaryLanguage",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout)
                    content = json.dumps(data, ensure_ascii=False, indent=2)
                    return {
                        "success": True,
                        "source": "github",
                        "url": url,
                        "title": data.get("name") or repo,
                        "content": self._trim(content, max_chars),
                        "summary": self._summarize_text(content),
                        "metadata": data,
                    }
            except Exception as exc:
                logger.debug("GitHub read via gh failed: %s", exc)
        return self._read_jina(url, max_chars=max_chars)

    def _read_reddit(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        proxy = self._config_get("reddit_proxy") or self._config_get("proxy")
        json_url = self._reddit_json_url(url)
        if json_url:
            try:
                text = self._fetch_text(json_url, timeout=25, proxy=proxy)
                data = json.loads(text)
                if isinstance(data, list) and data:
                    post = (
                        ((data[0] or {}).get("data") or {}).get("children") or [{}]
                    )[0].get("data") or {}
                    comments = []
                    if len(data) > 1:
                        comments = self._flatten_reddit_comments(
                            (((data[1] or {}).get("data") or {}).get("children") or []),
                            limit=8,
                        )
                    parts = [
                        str(post.get("title") or ""),
                        str(post.get("selftext") or ""),
                    ]
                    if comments:
                        parts.append("Top comments:")
                        parts.extend(f"- {c}" for c in comments)
                    content = "\n".join(p for p in parts if p).strip()
                    return {
                        "success": True,
                        "source": "reddit",
                        "url": url,
                        "title": str(post.get("title") or "Reddit post"),
                        "content": self._trim(content, max_chars),
                        "summary": self._summarize_text(content),
                        "metadata": {
                            "subreddit": post.get("subreddit"),
                            "author": post.get("author"),
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                        },
                    }
            except Exception as exc:
                logger.debug("Reddit JSON read failed: %s", exc)
        return self._read_jina(url, max_chars=max_chars)

    def _read_youtube(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        yt_dlp = shutil.which("yt-dlp")
        if not yt_dlp:
            return self._read_jina(url, max_chars=max_chars)

        try:
            proc = subprocess.run(
                [yt_dlp, "--dump-json", url],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return self._read_jina(url, max_chars=max_chars)

            info = json.loads(proc.stdout.splitlines()[0])
            transcript = self._read_youtube_transcript(
                info.get("id") or self._youtube_video_id(url)
            )
            parts = [
                str(info.get("title") or "YouTube video"),
                str(info.get("description") or ""),
            ]
            if transcript:
                parts.append("Transcript excerpt:")
                parts.append(transcript)
            content = "\n".join(p for p in parts if p).strip()
            metadata = {
                "channel": info.get("channel"),
                "duration": info.get("duration"),
                "view_count": info.get("view_count"),
                "upload_date": info.get("upload_date"),
                "video_id": info.get("id"),
            }
            return {
                "success": True,
                "source": "youtube",
                "url": url,
                "title": str(info.get("title") or "YouTube video"),
                "content": self._trim(content, max_chars),
                "summary": self._summarize_text(content),
                "metadata": metadata,
            }
        except Exception as exc:
            logger.debug("YouTube read failed: %s", exc)
            return self._read_jina(url, max_chars=max_chars)

    def _read_rss(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        if feedparser is None:
            return self._read_jina(url, max_chars=max_chars)
        try:
            feed = feedparser.parse(url)
            entries: list[Any] = []
            feed_entries = list(feed.entries or [])
            for entry in feed_entries[:10]:
                entries.append(
                    {
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "summary": self._trim(str(entry.get("summary") or ""), 300),
                        "published": entry.get("published", ""),
                    }
                )
            content = json.dumps(
                {"feed": getattr(feed.feed, "title", ""), "entries": entries},
                ensure_ascii=False,
                indent=2,
            )
            return {
                "success": True,
                "source": "rss",
                "url": url,
                "title": getattr(feed.feed, "title", "RSS feed") or "RSS feed",
                "content": self._trim(content, max_chars),
                "summary": self._summarize_text(content),
                "metadata": {"entry_count": len(entries)},
            }
        except Exception as exc:
            logger.debug("RSS read failed: %s", exc)
            return self._read_jina(url, max_chars=max_chars)

    def _read_v2ex(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        try:
            topic_id = self._v2ex_topic_id(url)
            if topic_id:
                channel = V2EXChannel()
                topic = channel.get_topic(topic_id)
                content = json.dumps(topic, ensure_ascii=False, indent=2)
                return {
                    "success": True,
                    "source": "v2ex",
                    "url": url,
                    "title": topic.get("title") or "V2EX topic",
                    "content": self._trim(content, max_chars),
                    "summary": self._summarize_text(content),
                    "metadata": {"topic_id": topic_id, "author": topic.get("author")},
                }
        except Exception as exc:
            logger.debug("V2EX read failed: %s", exc)
        return self._read_jina(url, max_chars=max_chars)

    def _read_xueqiu(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        try:
            symbol = self._xueqiu_symbol(url)
            if symbol:
                channel = XueqiuChannel()
                quote = channel.get_stock_quote(symbol)
                content = json.dumps(quote, ensure_ascii=False, indent=2)
                return {
                    "success": True,
                    "source": "xueqiu",
                    "url": url,
                    "title": quote.get("name") or symbol,
                    "content": self._trim(content, max_chars),
                    "summary": self._summarize_text(content),
                    "metadata": quote,
                }
        except Exception as exc:
            logger.debug("Xueqiu read failed: %s", exc)
        return self._read_jina(url, max_chars=max_chars)

    # ------------------------------------------------------------------
    # Parsing and ranking
    # ------------------------------------------------------------------

    def _rank_and_dedupe(
        self, items: list[IntelItem], query: str, limit: int
    ) -> list[IntelItem]:
        unique: dict[str, IntelItem] = {}
        for item in items:
            key = self._dedupe_key(item)
            if key not in unique:
                unique[key] = item
            else:
                existing = unique[key]
                # Keep the richer item when the same URL appears from different sources.
                if len(item.snippet) + len(item.title) > len(existing.snippet) + len(
                    existing.title
                ):
                    unique[key] = item

        scored: list[IntelItem] = []
        for item in unique.values():
            item.score = self._score_item(query, item)
            scored.append(item)

        scored.sort(key=lambda x: (x.score, len(x.snippet), len(x.title)), reverse=True)
        return scored[:limit]

    def _score_item(self, query: str, item: IntelItem) -> float:
        q_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        text = f"{item.title} {item.snippet} {item.author or ''}".lower()
        matches = sum(1 for token in q_tokens if token in text)
        base = matches / max(len(q_tokens), 1)
        source_boost = {
            "exa": 0.95,
            "github": 0.85,
            "youtube": 0.75,
            "reddit": 0.7,
            "xueqiu": 0.65,
            "v2ex": 0.65,
            "web": 0.6,
            "rss": 0.6,
            "jina": 0.5,
        }.get(item.source, 0.5)
        return round(base + source_boost + min(len(item.snippet) / 2000, 0.2), 4)

    def _dedupe_key(self, item: IntelItem) -> str:
        if item.url:
            return self._canonical_url(item.url)
        return re.sub(r"\s+", " ", f"{item.title} {item.snippet}".strip().lower())

    def _parse_json_search_results(self, stdout: str, source: str) -> list[IntelItem]:
        try:
            payload = json.loads(stdout)
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        items: list[IntelItem] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("name") or entry.get("title") or "Result")
            url = str(entry.get("url") or "")
            snippet = str(entry.get("description") or entry.get("snippet") or "")
            items.append(
                IntelItem(
                    source=source,
                    title=title,
                    url=url,
                    snippet=self._trim(snippet, 300),
                    metadata={
                        k: v
                        for k, v in entry.items()
                        if k not in {"name", "title", "url", "description", "snippet"}
                    },
                )
            )
        return items

    def _parse_ytdlp_json_output(self, stdout: str) -> list[IntelItem]:
        items: list[IntelItem] = []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue
            items.append(
                IntelItem(
                    source="youtube",
                    title=str(entry.get("title") or "YouTube video"),
                    url=str(
                        entry.get("webpage_url")
                        or self._youtube_web_url(entry.get("id") or "")
                    ),
                    snippet=self._trim(str(entry.get("description") or ""), 300),
                    metadata={
                        "channel": entry.get("channel"),
                        "duration": entry.get("duration"),
                        "view_count": entry.get("view_count"),
                        "upload_date": entry.get("upload_date"),
                    },
                )
            )
        return items

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _build_summary(self, query: str, items: list[IntelItem]) -> str:
        if not items:
            return f"No search results found for: {query}"
        chunks = [
            f"{idx + 1}. {item.title} ({item.source})"
            for idx, item in enumerate(items[:3])
        ]
        return textwrap.shorten(" | ".join(chunks), width=500, placeholder=" ...")

    def _build_discovery_summary(
        self, results: list[dict[str, Any]], reads: list[dict[str, Any]]
    ) -> str:
        if not results:
            return "No discovery results found."
        top_lines = []
        for idx, item in enumerate(results[:3], 1):
            top_lines.append(
                f"{idx}. {item.get('title', 'Result')} ({item.get('source', 'web')})"
            )
        if reads:
            top_lines.append(f"Deep reads: {len(reads)}")
        return textwrap.shorten(" | ".join(top_lines), width=600, placeholder=" ...")

    def _read_youtube_transcript(self, video_id: str | None) -> str:
        if not video_id:
            return ""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

            transcript_fn = getattr(YouTubeTranscriptApi, "get_transcript", None)
            if transcript_fn is None:
                return ""
            transcript = transcript_fn(
                video_id, languages=["en", "en-US", "zh-Hans", "zh-CN"]
            )
            text = " ".join(
                part.get("text", "") for part in transcript if part.get("text")
            )
            return self._trim(text, 1500)
        except Exception:
            return ""

    def _flatten_reddit_comments(
        self, comments: list[Any], limit: int = 8
    ) -> list[str]:
        out: list[str] = []
        stack = list(comments)
        while stack and len(out) < limit:
            node = stack.pop(0)
            if not isinstance(node, dict):
                continue
            data = node.get("data") or {}
            body = str(data.get("body") or "").strip()
            author = str(data.get("author") or "")
            if body:
                out.append(
                    f"{author}: {self._trim(body, 180)}"
                    if author
                    else self._trim(body, 180)
                )
            replies = (
                (((data.get("replies") or {}).get("data") or {}).get("children") or [])
                if isinstance(data.get("replies"), dict)
                else []
            )
            if replies:
                stack.extend(replies)
        return out[:limit]

    def _summarize_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        return self._trim(" ".join(lines[:4]), 700)

    def _trim(self, text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _fetch_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int = 20,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> str:
        full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
        req = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                **(headers or {}),
            },
        )
        opener = urllib.request.build_opener()
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
        try:
            with opener.open(req, timeout=timeout) as resp:
                charset = (
                    getattr(resp.headers, "get_content_charset", lambda: None)()
                    or "utf-8"
                )
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            logger.debug("HTTP %s from %s", exc.code, url)
            return ""
        except urllib.error.URLError as exc:
            logger.debug("URL error for %s: %s", url, exc.reason)
            return ""
        except OSError as exc:
            logger.debug("Network error for %s: %s", url, exc)
            return ""

    def _jina_url(self, url: str) -> str:
        url = url.strip()
        if url.startswith("http://"):
            return f"https://r.jina.ai/http://{url[len('http://') :]}"
        if url.startswith("https://"):
            return f"https://r.jina.ai/https://{url[len('https://') :]}"
        return f"https://r.jina.ai/http://{url}"

    def _is_private_url(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return True
        host = parsed.hostname or ""
        if not host:
            return True
        try:
            addr = ip_address(gethostbyname(host))
            return addr.is_private or addr.is_loopback or addr.is_link_local
        except Exception:
            return False

    def _looks_like_feed(self, url: str) -> bool:
        url = url.lower()
        return any(token in url for token in ("/feed", "/rss", ".xml", "atom"))

    def _command_exists(self, command: str) -> bool:
        return shutil.which(command) is not None

    def _free_sources(self) -> dict[str, str]:
        return {
            "web": "DuckDuckGo HTML + Jina Reader",
            "exa": "mcporter/Exa MCP (free, no API key)",
            "github": "gh CLI search",
            "youtube": "yt-dlp search + transcript",
            "reddit": "public JSON + DDG fallback",
            "rss": "feedparser",
            "v2ex": "public API + DDG site search",
            "xueqiu": "public API + DDG site search",
        }

    def _config_get(self, key: str, default: Any = None) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _canonical_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(self._normalize_result_url(url))
        cleaned = parsed._replace(fragment="")
        return urllib.parse.urlunparse(cleaned).rstrip("/")

    def _normalize_result_url(self, url: str) -> str:
        if not url:
            return url
        parsed = urllib.parse.urlparse(url)
        if parsed.path.startswith("/l/") and parsed.query:
            query = urllib.parse.parse_qs(parsed.query)
            if "uddg" in query and query["uddg"]:
                return urllib.parse.unquote(query["uddg"][0])
        if "uddg=" in parsed.query:
            query = urllib.parse.parse_qs(parsed.query)
            if "uddg" in query and query["uddg"]:
                return urllib.parse.unquote(query["uddg"][0])
        return url

    def _infer_title_from_text(self, text: str, fallback_url: str) -> str:
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return self._trim(line, 120)
        return fallback_url

    def _parse_url_path(self, url: str) -> str:
        return urllib.parse.urlparse(url).path.strip("/")

    def _reddit_json_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if not parsed.netloc:
            return ""
        path = parsed.path.rstrip("/")
        if "/comments/" not in path:
            return ""
        return f"https://www.reddit.com{path}.json?raw_json=1&limit=200"

    def _reddit_timestamp(self, ts: Any) -> str | None:
        try:
            value = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            return value.isoformat()
        except Exception:
            return None

    def _github_repo_from_url(self, url: str) -> str | None:
        parsed = urllib.parse.urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return None

    def _youtube_video_id(self, url: str) -> str | None:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("youtu.be"):
            return parsed.path.strip("/") or None
        query = urllib.parse.parse_qs(parsed.query)
        if "v" in query and query["v"]:
            return query["v"][0]
        match = re.search(r"/shorts/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)
        return None

    def _youtube_web_url(self, video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

    def _v2ex_topic_id(self, url: str) -> int | None:
        match = re.search(r"/t/(\d+)", url)
        if match:
            return int(match.group(1))
        return None

    def _xueqiu_symbol(self, url: str) -> str | None:
        match = re.search(r"/S/([A-Za-z0-9_.-]+)", url)
        if match:
            return match.group(1)
        return None


__all__ = ["FreeInternetIntel", "IntelItem"]
