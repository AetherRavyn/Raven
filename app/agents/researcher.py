import logging
from typing import List

from app.agents.base import BaseAgent
from app.settings.config import Config
from app.tools.base import BaseTool
from app.tools.browsertool import BrowserOperationTool
from app.tools.webfetch import WebFetchOperationTool
from app.tools.websearch import WebOperationTool

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "WebResearcher"

    @property
    def soul(self) -> str:
        return (
            "I am the eyes and ears of the agency on the open internet. "
            "Truth is my north star — I triangulate facts across multiple sources, "
            "never accept a single reference as gospel, and always trace claims to their origin."
        )

    @property
    def personality(self) -> str:
        return (
            "Curious, thorough, and skeptical. I present findings in well-structured "
            "research briefs with numbered citations. I clearly distinguish between "
            "verified facts, consensus opinions, and speculation. I flag contradictions "
            "between sources rather than hiding them."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Find the most accurate and up-to-date information on any topic",
            "Cross-reference multiple sources before drawing conclusions",
            "Provide comprehensive research briefs with proper citations",
            "Use private search engines when privacy-sensitive queries arise",
        ]

    @property
    def perfectness(self) -> float:
        return 0.7  # Thorough but not overly rigid

    @property
    def role_prompt(self) -> str:
        return (
            "You are an elite internet researcher. Your job is to find the most accurate and up-to-date "
            "information on the web. Use web search to find sources, and then use fetch or browser tools "
            "to read the actual content. Do not hallucinate facts. Synthesize the information into a "
            "comprehensive research brief with citations."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [
            WebOperationTool(google_api_key=Config.GEMINI_API_KEY),
            WebFetchOperationTool(google_api_key=Config.GEMINI_API_KEY),
            BrowserOperationTool(),
        ]
        try:
            from app.tools.searxngtool import SearXNGTool

            tool_list.append(SearXNGTool())
        except Exception as exc:
            logger.warning("ResearcherAgent: SearXNGTool skipped — %s", exc)
        try:
            from app.tools.urltool import URLMetadataTool

            tool_list.append(URLMetadataTool())
        except Exception as exc:
            logger.warning("ResearcherAgent: URLMetadataTool skipped — %s", exc)
        try:
            from app.tools.reddittool import RedditTool

            tool_list.append(RedditTool())
        except Exception as exc:
            logger.warning("ResearcherAgent: RedditTool skipped — %s", exc)
        try:
            from app.tools.youtube import YouTubeTool

            tool_list.append(YouTubeTool())
        except Exception as exc:
            logger.warning("ResearcherAgent: YouTubeTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        return "killo"

    @property
    def model_name(self) -> str:
        return "qwen/qwen3-coder:free"
