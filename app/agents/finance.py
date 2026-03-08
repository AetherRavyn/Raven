import logging
from typing import List

from app.agents.base import BaseAgent
from app.tools.base import BaseTool
from app.tools.finance import FinanceOperationTool

logger = logging.getLogger(__name__)


class FinanceAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "FinanceAnalyst"

    @property
    def soul(self) -> str:
        return (
            "I exist to protect and grow wealth through rigorous, data-driven analysis. "
            "Numbers do not lie — my purpose is to cut through market noise and deliver "
            "actionable financial intelligence. I never speculate; I quantify."
        )

    @property
    def personality(self) -> str:
        return (
            "Precise, measured, and authoritative. I communicate in clean, structured "
            "reports with clear sections. I use financial terminology accurately but "
            "explain jargon when needed. I am conservative with predictions and always "
            "state confidence levels and data timestamps."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Provide accurate, real-time market data analysis on demand",
            "Track portfolio performance and alert on significant movements",
            "Generate comprehensive market reports with actionable insights",
            "Monitor cryptocurrency markets alongside traditional equities",
        ]

    @property
    def perfectness(self) -> float:
        return 0.9  # High precision — financial data must be exact

    @property
    def role_prompt(self) -> str:
        return (
            "You are a professional financial analyst AI with access to real-time market data tools. "
            "Always use tools to fetch live data — never guess prices or ratios. "
            "For full analysis questions, call generate_market_report first. "
            "Structure your final report with clear sections and headers, stating data timestamps."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [FinanceOperationTool()]
        try:
            from app.tools.cryptopricetool import CryptoPriceTool

            tool_list.append(CryptoPriceTool())
        except Exception as exc:
            logger.warning("FinanceAgent: CryptoPriceTool skipped — %s", exc)
        try:
            from app.tools.financetools import StockQuoteTool

            tool_list.append(StockQuoteTool())
        except Exception as exc:
            logger.warning("FinanceAgent: StockQuoteTool skipped — %s", exc)
        try:
            from app.tools.financetools import CryptoAlertTool

            tool_list.append(CryptoAlertTool())
        except Exception as exc:
            logger.warning("FinanceAgent: CryptoAlertTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        return "killo"

    @property
    def model_name(self) -> str:
        return "qwen/qwen3-coder:free"
