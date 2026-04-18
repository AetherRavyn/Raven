import logging
from typing import List

from app.agents.base import BaseAgent
from app.settings.config import Config
from app.tools.base import BaseTool
from app.tools.internetinteltool import InternetIntelTool
from app.tools.news.hackernews import HackerNewsTool
from app.tools.websearch import WebOperationTool

logger = logging.getLogger(__name__)


class NewsAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "TrendAnalyst"

    @property
    def soul(self) -> str:
        return (
            "I am the pulse-reader. I exist to keep the user ahead of the curve — "
            "monitoring the information firehose and distilling it into the signal that "
            "matters. I connect dots across industries, technologies, and geopolitics."
        )

    @property
    def personality(self) -> str:
        return (
            "Sharp, concise, and editorial. I write like a top-tier analyst — executive "
            "summaries first, deep dives on request. I always cite sources with links. "
            "I distinguish between breaking news, developing stories, and background context. "
            "I flag high-impact items with urgency markers."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Monitor tech trends, global news, and industry developments",
            "Compile concise daily briefings with executive summaries",
            "Track RSS feeds for continuous intelligence gathering",
            "Provide deep-dive analysis on specific topics when requested",
        ]

    @property
    def perfectness(self) -> float:
        return 0.7  # Accurate but fast-moving

    @property
    def role_prompt(self) -> str:
        return (
            "You are an expert Trend Analyst and News Curator. "
            "Your job is to monitor global news and tech trends, utilizing sources like HackerNews. "
            "Compile daily briefings or analyze specific news topics when requested. "
            "Always cite your sources and provide concise, executive-level summaries."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [
            HackerNewsTool(),
            WebOperationTool(google_api_key=Config.GEMINI_API_KEY),
            InternetIntelTool(),
        ]
        try:
            from app.tools.rssreadertool import RSSReaderTool

            tool_list.append(RSSReaderTool())
        except Exception as exc:
            logger.warning("NewsAgent: RSSReaderTool skipped — %s", exc)
        try:
            from app.tools.twittertool import TwitterTool

            tool_list.append(TwitterTool())
        except Exception as exc:
            logger.warning("NewsAgent: TwitterTool skipped — %s", exc)
        try:
            from app.tools.reddittool import RedditTool

            tool_list.append(RedditTool())
        except Exception as exc:
            logger.warning("NewsAgent: RedditTool skipped — %s", exc)
        try:
            from app.tools.youtube import YouTubeTool

            tool_list.append(YouTubeTool())
        except Exception as exc:
            logger.warning("NewsAgent: YouTubeTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        return "killo"

    @property
    def model_name(self) -> str:
        return "qwen/qwen3-coder:free"
