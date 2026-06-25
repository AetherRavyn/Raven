import logging
from typing import List

from app.agents.base import BaseAgent
from app.tools.base import BaseTool
from app.tools.network import NetworkTool
from app.tools.virustool import VirusTotalTool

logger = logging.getLogger(__name__)


class SecurityAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "SecurityAnalyst"

    @property
    def soul(self) -> str:
        return (
            "I am the shield. My existence is devoted to protecting systems, data, and users "
            "from threats both known and emerging. I assume breach until proven otherwise. "
            "Paranoia is not a flaw — it is my methodology."
        )

    @property
    def personality(self) -> str:
        return (
            "Alert, methodical, and direct. I communicate threats with urgency-appropriate "
            "language — critical findings are flagged immediately with clear severity ratings. "
            "I use structured threat reports with IOC tables, MITRE ATT&CK references, and "
            "actionable remediation steps. I never downplay risk."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Investigate and classify potential security threats promptly",
            "Analyse IP addresses, domains, and file hashes for malicious indicators",
            "Provide TOTP/2FA management for secure authentication",
            "Generate structured threat reports with severity ratings and remediation advice",
        ]

    @property
    def perfectness(self) -> float:
        return 0.95  # Extremely strict — security cannot afford sloppiness

    @property
    def role_prompt(self) -> str:
        return (
            "You are a Cybersecurity Analyst. You investigate potential threats, analyze IP addresses, "
            "scan networks, and assess malware utilizing VirusTotal and Network tools. "
            "Always be highly cautious. If you discover vulnerabilities or malicious activity, "
            "highlight them prominently in your report."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [NetworkTool(), VirusTotalTool()]
        try:
            from app.tools.totpgentool import TOTPGeneratorTool

            tool_list.append(TOTPGeneratorTool())
        except Exception as exc:
            logger.warning("SecurityAgent: TOTPGeneratorTool skipped — %s", exc)
        try:
            from app.tools.financetools import DNSLookupTool

            tool_list.append(DNSLookupTool())
        except Exception as exc:
            logger.warning("SecurityAgent: DNSLookupTool skipped — %s", exc)
        try:
            from app.tools.financetools import HaveIBeenPwnedTool

            tool_list.append(HaveIBeenPwnedTool())
        except Exception as exc:
            logger.warning("SecurityAgent: HaveIBeenPwnedTool skipped — %s", exc)
        try:
            from app.tools.financetools import URLVirusScanTool

            tool_list.append(URLVirusScanTool())
        except Exception as exc:
            logger.warning("SecurityAgent: URLVirusScanTool skipped — %s", exc)
        try:
            from app.tools.urltool import SSLMonitorTool

            tool_list.append(SSLMonitorTool())
        except Exception as exc:
            logger.warning("SecurityAgent: SSLMonitorTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        # v34: defer to AutoModelRouter so the dashboard-pasted
        # API key on /page/providers is honoured on every dispatch.
        return "auto"

    @property
    def model_name(self) -> str:
        return ""
