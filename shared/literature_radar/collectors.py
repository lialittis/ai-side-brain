"""API/RSS collectors for Shared Literature Radar.

Collectors in this module target stable public APIs or official metadata feeds.
They return product-neutral radar paper dictionaries and do not write to any
Personal or Team storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .core import create_radar_paper, normalize_spaces


ARXIV_API_URL = "https://export.arxiv.org/api/query"
DBLP_PUBLICATION_SEARCH_URL = "https://dblp.org/search/publ/api"
DEFAULT_ARXIV_CATEGORIES = ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"]
DEFAULT_TIMEOUT_SECONDS = 30

Fetcher = Callable[[str], bytes]


def fetch_url(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    request = Request(url, headers={"User-Agent": "AI-Side-Brain-Literature-Radar/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def collect_arxiv(
    *,
    query_terms: list[str],
    categories: list[str] | None = None,
    max_results: int = 50,
    start: int = 0,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_arxiv_query_url(
        query_terms=query_terms,
        categories=categories or DEFAULT_ARXIV_CATEGORIES,
        max_results=max_results,
        start=start,
    )
    content = (fetcher or fetch_url)(url)
    return parse_arxiv_atom(content, query_url=url, collected_at=now)


def build_arxiv_query_url(
    *,
    query_terms: list[str],
    categories: list[str] | None = None,
    max_results: int = 50,
    start: int = 0,
) -> str:
    category_query = " OR ".join(f"cat:{category}" for category in categories or DEFAULT_ARXIV_CATEGORIES)
    term_query = " OR ".join(f'all:"{term}"' for term in query_terms if term.strip())
    search_query = f"({category_query})"
    if term_query:
        search_query = f"{search_query} AND ({term_query})"
    params = {
        "search_query": search_query,
        "start": str(max(0, start)),
        "max_results": str(max(1, max_results)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_arxiv_atom(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers = []
    for entry in root.findall("atom:entry", namespace):
        arxiv_url = text_of(entry, "atom:id", namespace)
        arxiv_id = arxiv_id_from_url(arxiv_url)
        title = text_of(entry, "atom:title", namespace)
        abstract = text_of(entry, "atom:summary", namespace)
        published = text_of(entry, "atom:published", namespace)
        authors = [text_of(author, "atom:name", namespace) for author in entry.findall("atom:author", namespace)]
        authors = [author for author in authors if author]
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall("atom:category", namespace)
            if category.attrib.get("term")
        ]
        primary_category = ""
        primary = entry.find("arxiv:primary_category", namespace)
        if primary is not None:
            primary_category = primary.attrib.get("term", "")
        pdf_url = ""
        landing_url = arxiv_url
        for link in entry.findall("atom:link", namespace):
            link_href = link.attrib.get("href", "")
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link_href
            elif link.attrib.get("rel") == "alternate":
                landing_url = link_href
        papers.append(
            create_radar_paper(
                source_id="arxiv",
                source_paper_id=arxiv_id,
                title=title,
                authors=authors,
                abstract=abstract,
                year=year_from_iso_date(published),
                venue="arXiv",
                identifiers={"arxiv_id": arxiv_id},
                links={"arxiv": landing_url, "landing": landing_url, "pdf": pdf_url},
                discovered_at=collected_at,
                source_record={
                    "source_id": "arxiv",
                    "source_paper_id": arxiv_id,
                    "query_url": query_url,
                    "published": published,
                    "updated": text_of(entry, "atom:updated", namespace),
                    "primary_category": primary_category,
                    "categories": categories,
                },
            )
        )
    return papers


def collect_dblp_publications(
    *,
    query: str,
    max_results: int = 50,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_dblp_publication_search_url(query=query, max_results=max_results)
    content = (fetcher or fetch_url)(url)
    return parse_dblp_publication_search(content, query_url=url, collected_at=now)


def build_dblp_publication_search_url(*, query: str, max_results: int = 50) -> str:
    params = {"q": query, "format": "xml", "h": str(max(1, max_results))}
    return f"{DBLP_PUBLICATION_SEARCH_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_dblp_publication_search(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    papers = []
    for hit in root.findall(".//hit"):
        info = hit.find("info")
        if info is None:
            continue
        key = hit.attrib.get("id") or text_of(info, "key")
        title = text_of(info, "title")
        if not title:
            continue
        authors_node = info.find("authors")
        authors = []
        if authors_node is not None:
            authors = [normalize_spaces(author.text or "") for author in authors_node.findall("author")]
            authors = [author for author in authors if author]
        year = int_or_none(text_of(info, "year"))
        venue = text_of(info, "venue")
        doi = text_of(info, "doi")
        ee_url = text_of(info, "ee")
        landing_url = text_of(info, "url") or ee_url
        papers.append(
            create_radar_paper(
                source_id="dblp",
                source_paper_id=key or title,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                identifiers={"doi": doi} if doi else {},
                links={"landing": landing_url, "doi": doi_url(doi), "publisher": ee_url},
                discovered_at=collected_at,
                source_record={
                    "source_id": "dblp",
                    "source_paper_id": key or title,
                    "query_url": query_url,
                    "type": text_of(info, "type"),
                    "venue": venue,
                },
            )
        )
    return papers


def text_of(node: ET.Element, path: str, namespace: dict[str, str] | None = None) -> str:
    selected = node.find(path, namespace or {})
    return normalize_spaces(selected.text or "") if selected is not None else ""


def arxiv_id_from_url(value: str) -> str:
    return value.rstrip("/").split("/")[-1].removesuffix(".pdf")


def year_from_iso_date(value: str) -> int | None:
    if not value:
        return None
    return int_or_none(value[:4])


def int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""
