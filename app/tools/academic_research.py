"""Academic Research — search papers on arXiv and Semantic Scholar with proper citations.

Provides tools for:
- Paper search by keywords, author, or topic
- Paper metadata (abstract, authors, citations)
- Citation network exploration
- Research summary generation
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ArxivSearchTool(BaseTool):
    """Search academic papers on arXiv."""

    def get_name(self) -> str:
        return "arxiv_search"

    def get_description(self) -> str:
        return (
            "Search arXiv for academic papers by keywords, author, or topic. "
            "Returns paper titles, authors, abstracts, dates, and URLs."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (keywords, title, author)"},
                "max_results": {"type": "integer", "description": "Max results (default 5)"},
                "sort_by": {"type": "string", "enum": ["relevance", "date", "rating"], "description": "Sort order"},
                "category": {"type": "string", "description": "arXiv category filter (e.g., cs.AI, cs.CL, math.CO)"},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)
        category = kwargs.get("category", "")

        if not query:
            return {"error": "query is required"}

        if category:
            pass

        try:
            import httpx
            url = f"http://export.arxiv.org/api/query?search_query=all:{query}"
            if category:
                url = f"http://export.arxiv.org/api/query?search_query=cat:{category}+AND+all:{query}"
            url += f"&max_results={min(max_results, 20)}&sortBy=relevance"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)

            # Parse Atom XML
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            papers = []
            for entry in root.findall("atom:entry", ns):
                title = entry.find("atom:title", ns).text.strip().replace("\n", " ") if entry.find("atom:title", ns) is not None else ""
                abstract = entry.find("atom:summary", ns).text.strip()[:500] if entry.find("atom:summary", ns) is not None else ""
                published = entry.find("atom:published", ns).text if entry.find("atom:published", ns) is not None else ""
                link = entry.find("atom:id", ns).text if entry.find("atom:id", ns) is not None else ""

                authors = []
                for author in entry.findall("atom:author", ns):
                    name_el = author.find("atom:name", ns)
                    if name_el is not None:
                        authors.append(name_el.text)

                categories = []
                for cat in entry.findall("atom:category", ns):
                    categories.append(cat.get("term", ""))

                papers.append({
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "published": published[:10],
                    "url": link,
                    "arxiv_id": link.split("/abs/")[-1] if "/abs/" in link else "",
                    "categories": categories,
                    "citation_url": f"https://arxiv.org/abs/{link.split('/abs/')[-1]}" if "/abs/" in link else "",
                })

            return {"success": True, "papers": papers, "count": len(papers), "query": query}

        except ImportError:
            return {"error": "httpx not installed"}
        except Exception as e:
            return {"error": str(e)[:500]}


class SemanticScholarTool(BaseTool):
    """Search Semantic Scholar for papers with citation data."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def get_name(self) -> str:
        return "semantic_scholar"

    def get_description(self) -> str:
        return (
            "Search Semantic Scholar for papers with full citation data. "
            "Get paper details, citation counts, influential citations, and recommendations."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["search", "paper", "citations", "recommendations"],
                    "description": "search=paper search, paper=get paper details, citations=get citations of a paper",
                },
                "query": {"type": "string", "description": "Search query"},
                "paper_id": {"type": "string", "description": "Semantic Scholar paper ID or DOI"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "search")

        try:
            import httpx

            if operation == "search":
                query = kwargs.get("query", "")
                limit = kwargs.get("limit", 5)
                if not query:
                    return {"error": "query is required"}

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{self.BASE_URL}/paper/search",
                        params={"query": query, "limit": min(limit, 20),
                                "fields": "title,abstract,authors,year,citationCount,influentialCitationCount,url,externalIds"},
                    )
                    data = resp.json()

                papers = []
                for p in data.get("data", []):
                    papers.append({
                        "title": p.get("title", ""),
                        "abstract": (p.get("abstract") or "")[:500],
                        "authors": [a.get("name", "") for a in p.get("authors", [])],
                        "year": p.get("year"),
                        "citation_count": p.get("citationCount", 0),
                        "influential_citations": p.get("influentialCitationCount", 0),
                        "url": p.get("url", ""),
                        "doi": p.get("externalIds", {}).get("DOI", ""),
                        "arxiv_id": p.get("externalIds", {}).get("ArXiv", ""),
                    })

                return {"success": True, "papers": papers, "count": len(papers)}

            elif operation == "paper":
                paper_id = kwargs.get("paper_id", "")
                if not paper_id:
                    return {"error": "paper_id is required"}

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{self.BASE_URL}/paper/{paper_id}",
                        params={"fields": "title,abstract,authors,year,citationCount,influentialCitationCount,references,citations,url,externalIds,tldr"},
                    )
                    paper = resp.json()

                return {
                    "success": True,
                    "title": paper.get("title", ""),
                    "abstract": (paper.get("abstract") or "")[:1000],
                    "authors": [a.get("name", "") for a in paper.get("authors", [])],
                    "year": paper.get("year"),
                    "citation_count": paper.get("citationCount", 0),
                    "url": paper.get("url", ""),
                    "tldr": paper.get("tldr", {}).get("text", "") if paper.get("tldr") else "",
                    "reference_count": len(paper.get("references", []) or []),
                    "top_citations": [
                        {"title": c.get("title", ""), "year": c.get("year")}
                        for c in (paper.get("citations") or [])[:5]
                    ],
                }

            elif operation == "citations":
                paper_id = kwargs.get("paper_id", "")
                limit = kwargs.get("limit", 10)
                if not paper_id:
                    return {"error": "paper_id is required"}

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{self.BASE_URL}/paper/{paper_id}/citations",
                        params={"fields": "title,year,citationCount,url", "limit": min(limit, 50)},
                    )
                    data = resp.json()

                citations = [
                    {"title": c.get("citingPaper", {}).get("title", ""),
                     "year": c.get("citingPaper", {}).get("year"),
                     "citation_count": c.get("citingPaper", {}).get("citationCount", 0),
                     "url": c.get("citingPaper", {}).get("url", "")}
                    for c in data.get("data", []) if c.get("citingPaper", {}).get("title")
                ]

                return {"success": True, "citations": citations, "count": len(citations)}

            elif operation == "recommendations":
                paper_id = kwargs.get("paper_id", "")
                limit = kwargs.get("limit", 5)
                if not paper_id:
                    return {"error": "paper_id is required"}

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{self.BASE_URL}/recommendations/v1/papers/forpaper/{paper_id}",
                        params={"fields": "title,year,citationCount,url", "limit": min(limit, 20)},
                    )
                    data = resp.json()

                papers = [
                    {"title": p.get("title", ""), "year": p.get("year"),
                     "citation_count": p.get("citationCount", 0), "url": p.get("url", "")}
                    for p in data.get("recommendedPapers", []) if p.get("title")
                ]

                return {"success": True, "recommendations": papers, "count": len(papers)}

            return {"error": f"Unknown operation: {operation}"}

        except ImportError:
            return {"error": "httpx not installed"}
        except Exception as e:
            return {"error": str(e)[:500]}
