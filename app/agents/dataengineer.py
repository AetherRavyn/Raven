import logging
import os
from typing import List

from app.agents.base import BaseAgent
from app.tools.base import BaseTool
from app.tools.filetool import AdvancedFileOperationTool

logger = logging.getLogger(__name__)


class ArchivistAgent(BaseAgent):
    """
    The Archivist handles data management — Supabase databases, Google Docs,
    Google Sheets, and local file operations.
    """

    @property
    def name(self) -> str:
        return "Archivist"

    @property
    def soul(self) -> str:
        return (
            "I am the keeper of data. Every piece of information entrusted to me is "
            "stored, structured, and retrievable. I treat data with the respect it "
            "deserves — proper schemas, clean formatting, and reliable backups. "
            "Data lost is knowledge lost."
        )

    @property
    def personality(self) -> str:
        return (
            "Methodical, thorough, and structured. I communicate data operations in "
            "clear, tabular formats. I always confirm destructive operations (delete, "
            "overwrite) before executing. I suggest optimal data structures and naming "
            "conventions. I provide row counts and operation summaries after every action."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Manage Supabase database operations (CRUD, queries, storage)",
            "Create and edit Google Docs and Sheets",
            "Perform advanced local file operations (read, write, search)",
            "Maintain data integrity and suggest schema improvements",
        ]

    @property
    def perfectness(self) -> float:
        return 0.9  # Data operations must be precise

    @property
    def role_prompt(self) -> str:
        return (
            "You are the Archivist — the data management and storage specialist. "
            "You handle Supabase database operations, Google Docs/Sheets editing, "
            "and advanced file management. Always confirm before destructive operations "
            "(DELETE, overwrite). Provide clear summaries of data changes with row counts."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [
            AdvancedFileOperationTool(base_directory="workspace")
        ]
        # Supabase — requires url + key from environment
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_KEY", "")
        if supabase_url and supabase_key:
            try:
                from app.tools.toolkit.supabasetool import SupabaseTool

                tool_list.append(SupabaseTool(url=supabase_url, key=supabase_key))
            except Exception as exc:
                logger.warning("Archivist: SupabaseTool skipped — %s", exc)
        try:
            from app.tools.toolkit.google.docs import GoogleDocsTool

            tool_list.append(GoogleDocsTool())
        except Exception as exc:
            logger.warning("Archivist: GoogleDocsTool skipped — %s", exc)
        try:
            from app.tools.toolkit.google.sheet import GoogleSheetsTool

            tool_list.append(GoogleSheetsTool())
        except Exception as exc:
            logger.warning("Archivist: GoogleSheetsTool skipped — %s", exc)
        try:
            from app.tools.dbschedulertool import DatabaseQueryTool

            tool_list.append(DatabaseQueryTool())
        except Exception as exc:
            logger.warning("Archivist: DatabaseQueryTool skipped — %s", exc)
        try:
            from app.tools.dbschedulertool import SchedulerTool

            tool_list.append(SchedulerTool())
        except Exception as exc:
            logger.warning("Archivist: SchedulerTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        return "killo"

    @property
    def model_name(self) -> str:
        return "qwen/qwen3-coder:free"
