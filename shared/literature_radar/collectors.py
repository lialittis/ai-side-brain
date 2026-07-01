"""API/RSS collectors for Shared Literature Radar.

Collectors in this module target stable public APIs or official metadata feeds.
They return product-neutral radar paper dictionaries and do not write to any
Personal or Team storage.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable
from html.parser import HTMLParser
from urllib.parse import quote, quote_plus, urlencode, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .core import create_radar_paper, normalize_spaces


ARXIV_API_URL = "https://export.arxiv.org/api/query"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
DBLP_PUBLICATION_SEARCH_URL = "https://dblp.org/search/publ/api"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENREVIEW_API2_NOTES_URL = "https://api2.openreview.net/notes"
OPENREVIEW_WEB_URL = "https://openreview.net"
SEMANTIC_SCHOLAR_PAPER_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
UNPAYWALL_API_URL = "https://api.unpaywall.org/v2"
USENIX_BASE_URL = "https://www.usenix.org"
NDSS_BASE_URL = "https://www.ndss-symposium.org"
OPENALEX_SELECT_FIELDS = [
    "id",
    "ids",
    "doi",
    "display_name",
    "title",
    "abstract_inverted_index",
    "publication_year",
    "publication_date",
    "type",
    "authorships",
    "primary_location",
    "best_oa_location",
    "open_access",
    "cited_by_count",
    "concepts",
    "topics",
]
SEMANTIC_SCHOLAR_FIELDS = [
    "paperId",
    "corpusId",
    "externalIds",
    "url",
    "title",
    "abstract",
    "authors",
    "year",
    "venue",
    "publicationDate",
    "publicationTypes",
    "fieldsOfStudy",
    "s2FieldsOfStudy",
    "isOpenAccess",
    "openAccessPdf",
]
DEFAULT_ARXIV_CATEGORIES = ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"]
DEFAULT_TIMEOUT_SECONDS = 30

Fetcher = Callable[[str], bytes]


def fetch_url(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
) -> bytes:
    request_headers = {"User-Agent": "AI-Side-Brain-Literature-Radar/0.1"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
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


def collect_crossref_works(
    *,
    query_terms: list[str],
    max_results: int = 50,
    mailto: str | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_crossref_works_url(
        query_terms=query_terms,
        max_results=max_results,
        mailto=mailto,
    )
    content = (fetcher or fetch_url)(url)
    return parse_crossref_works(content, query_url=url, collected_at=now)


def build_crossref_works_url(
    *,
    query_terms: list[str],
    max_results: int = 50,
    mailto: str | None = None,
) -> str:
    query = " ".join(term.strip() for term in query_terms if term.strip())
    params = {
        "query.bibliographic": query,
        "rows": str(max(1, min(100, max_results))),
        "sort": "published",
        "order": "desc",
    }
    if mailto:
        params["mailto"] = mailto
    return f"{CROSSREF_WORKS_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_crossref_works(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    papers = []
    for record in (payload.get("message") or {}).get("items") or []:
        doi = clean_doi_identifier(record.get("DOI") or "")
        title = first_crossref_value(record, "title")
        if not title or not doi:
            continue
        landing_url = normalize_spaces(record.get("URL") or doi_url(doi))
        license_record = first_mapping(record.get("license") or [])
        link_record = first_mapping(record.get("link") or [])
        pdf_url = normalize_spaces(link_record.get("URL") or "")
        source_record = {
            "source_id": "crossref",
            "source_paper_id": doi,
            "query_url": query_url,
            "type": normalize_spaces(record.get("type") or ""),
            "publisher": normalize_spaces(record.get("publisher") or ""),
            "published": crossref_date_parts(record),
            "license": license_record,
            "subjects": [str(value) for value in record.get("subject") or []],
            "reference_count": int_or_none(record.get("reference-count")),
            "is_referenced_by_count": int_or_none(record.get("is-referenced-by-count")),
        }
        papers.append(
            create_radar_paper(
                source_id="crossref",
                source_paper_id=doi,
                title=title,
                authors=crossref_authors(record),
                abstract=strip_markup(first_crossref_value(record, "abstract")),
                year=crossref_year(record),
                venue=first_crossref_value(record, "container-title"),
                identifiers={"doi": doi, "issn": first_crossref_value(record, "ISSN")},
                links={
                    "landing": landing_url,
                    "doi": doi_url(doi),
                    "publisher": landing_url,
                    "pdf": pdf_url,
                    "license": normalize_spaces(license_record.get("URL") or license_record.get("content-version") or ""),
                },
                discovered_at=collected_at,
                source_record=source_record,
            )
        )
    return papers


def first_crossref_value(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if isinstance(value, list):
        return normalize_spaces(value[0] if value else "")
    return normalize_spaces(value or "")


def crossref_authors(record: dict[str, Any]) -> list[str]:
    authors = []
    for author in record.get("author") or []:
        name = normalize_spaces(author.get("name") or " ".join(
            part for part in [author.get("given"), author.get("family")] if part
        ))
        if name:
            authors.append(name)
    return authors


def crossref_year(record: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        date = record.get(key) or {}
        date_parts = date.get("date-parts") or []
        if date_parts and date_parts[0]:
            return int_or_none(date_parts[0][0])
    return None


def crossref_date_parts(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("published-print", "published-online", "published", "issued")
        if key in record
    }


def first_mapping(records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if isinstance(record, dict):
            return record
    return {}


def strip_markup(value: str) -> str:
    return normalize_spaces(re.sub(r"<[^>]+>", " ", value or ""))


def collect_usenix_security_accepted_papers(
    *,
    year: int,
    cycle: int = 1,
    max_results: int = 200,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_usenix_security_accepted_papers_url(year=year, cycle=cycle)
    content = (fetcher or fetch_url)(url)
    return parse_usenix_security_accepted_papers(
        content,
        year=year,
        cycle=cycle,
        page_url=url,
        collected_at=now,
    )[:max_results]


def build_usenix_security_accepted_papers_url(*, year: int, cycle: int = 1) -> str:
    short_year = str(year)[-2:]
    return f"{USENIX_BASE_URL}/conference/usenixsecurity{short_year}/cycle{int(cycle)}-accepted-papers"


def parse_usenix_security_accepted_papers(
    content: bytes | str,
    *,
    year: int,
    cycle: int = 1,
    page_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    venue = f"USENIX Security {year}"
    return parse_accepted_paper_page(
        content,
        source_id="usenix_security",
        venue=venue,
        year=year,
        page_url=page_url or build_usenix_security_accepted_papers_url(year=year, cycle=cycle),
        collected_at=collected_at,
        source_context={"cycle": cycle},
    )


def collect_ndss_accepted_papers(
    *,
    year: int,
    max_results: int = 300,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_ndss_accepted_papers_url(year=year)
    content = (fetcher or fetch_url)(url)
    return parse_ndss_accepted_papers(
        content,
        year=year,
        page_url=url,
        collected_at=now,
    )[:max_results]


def build_ndss_accepted_papers_url(*, year: int) -> str:
    return f"{NDSS_BASE_URL}/ndss{int(year)}/accepted-papers/"


def parse_ndss_accepted_papers(
    content: bytes | str,
    *,
    year: int,
    page_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    return parse_accepted_paper_page(
        content,
        source_id="ndss",
        venue=f"NDSS {year}",
        year=year,
        page_url=page_url or build_ndss_accepted_papers_url(year=year),
        collected_at=collected_at,
    )


def parse_accepted_paper_page(
    content: bytes | str,
    *,
    source_id: str,
    venue: str,
    year: int,
    page_url: str,
    collected_at: datetime | None = None,
    source_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parser = AcceptedPaperHTMLParser()
    parser.feed(content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content)
    blocks = parser.blocks
    papers = []
    for index, block in enumerate(blocks):
        if block["tag"] not in {"h2", "h3", "h4"}:
            continue
        title = normalize_accepted_paper_title(block["text"])
        if not accepted_paper_title_candidate(title, venue):
            continue
        following = []
        for next_block in blocks[index + 1:]:
            if next_block["tag"] in {"h2", "h3", "h4"}:
                break
            text = normalize_spaces(next_block["text"])
            if accepted_page_noise(text):
                continue
            following.append(text)
        authors_text = following[0] if following else ""
        abstract = " ".join(following[1:]) if len(following) > 1 else ""
        link = urljoin(page_url, block.get("href") or "")
        source_paper_id = link or f"{page_url}#{index}"
        source_record = {
            "source_id": source_id,
            "source_paper_id": source_paper_id,
            "source_page": page_url,
            "venue": venue,
            "authors_text": authors_text,
            **(source_context or {}),
        }
        papers.append(
            create_radar_paper(
                source_id=source_id,
                source_paper_id=source_paper_id,
                title=title,
                authors=split_author_text(authors_text),
                abstract=abstract,
                year=year,
                venue=venue,
                links={"landing": link or page_url, "source_page": page_url},
                discovered_at=collected_at,
                source_record=source_record,
            )
        )
    return papers


class AcceptedPaperHTMLParser(HTMLParser):
    block_tags = {"h1", "h2", "h3", "h4", "p", "li", "div"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict[str, str]] = []
        self._stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        selected_tag = tag.lower()
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if selected_tag in self.block_tags:
            self._stack.append({"tag": selected_tag, "parts": [], "href": ""})
        if selected_tag == "a" and self._stack and attrs_dict.get("href"):
            for block in reversed(self._stack):
                if block["tag"] in {"h1", "h2", "h3", "h4"} and not block.get("href"):
                    block["href"] = attrs_dict["href"]
                    break

    def handle_endtag(self, tag: str) -> None:
        selected_tag = tag.lower()
        if selected_tag not in self.block_tags:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == selected_tag:
                block = self._stack.pop(index)
                text = normalize_spaces(" ".join(block["parts"]))
                if text:
                    self.blocks.append({"tag": selected_tag, "text": text, "href": block.get("href") or ""})
                break

    def handle_data(self, data: str) -> None:
        text = normalize_spaces(data)
        if not text:
            return
        if self._stack:
            self._stack[-1]["parts"].append(text)


def normalize_accepted_paper_title(value: str) -> str:
    return normalize_spaces(value.removeprefix("Paper:").strip())


def accepted_paper_title_candidate(title: str, venue: str) -> bool:
    if not title or len(title) < 8:
        return False
    lowered = title.lower()
    blocked_fragments = [
        "accepted papers",
        "submission cycle",
        "view mode",
        "program",
        "sponsorship",
        "leadership",
        "previous events",
        venue.lower(),
    ]
    return not any(fragment and fragment in lowered for fragment in blocked_fragments)


def accepted_page_noise(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    return lowered in {
        "available media",
        "image",
        "view mode:",
        "condensed",
        "standard",
        "expanded",
        "search for:",
        "search button",
    }


def split_author_text(value: str) -> list[str]:
    if not value:
        return []
    cleaned = re.sub(r"\([^)]*\)", "", value)
    if ";" in cleaned:
        parts = []
        for segment in cleaned.split(";"):
            names_part = segment.split(",")[0]
            parts.extend(re.split(r"\s+and\s+", names_part))
    else:
        parts = re.split(r",\s+|\s+ and \s+", cleaned)
    authors = []
    for part in parts:
        candidate = normalize_spaces(part)
        if not candidate or candidate.lower().startswith(("university", "institute", "school", "department", "lab")):
            continue
        authors.append(candidate)
    return authors[:30]


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


def collect_openalex_works(
    *,
    query_terms: list[str],
    max_results: int = 50,
    page: int = 1,
    mailto: str | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_openalex_works_url(
        query_terms=query_terms,
        max_results=max_results,
        page=page,
        mailto=mailto,
    )
    content = (fetcher or fetch_url)(url)
    return parse_openalex_works(content, query_url=url, collected_at=now)


def build_openalex_works_url(
    *,
    query_terms: list[str],
    max_results: int = 50,
    page: int = 1,
    mailto: str | None = None,
    select_fields: list[str] | None = None,
) -> str:
    query = " ".join(term.strip() for term in query_terms if term.strip())
    params = {
        "search": query,
        "per-page": str(max(1, min(200, max_results))),
        "page": str(max(1, page)),
        "sort": "publication_date:desc",
        "select": ",".join(select_fields or OPENALEX_SELECT_FIELDS),
    }
    if mailto:
        params["mailto"] = mailto
    return f"{OPENALEX_WORKS_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_openalex_works(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    papers = []
    for record in payload.get("results") or []:
        title = normalize_spaces(record.get("display_name") or record.get("title") or "")
        openalex_id = openalex_id_from_url(record.get("id") or "")
        if not title or not openalex_id:
            continue
        identifiers = openalex_identifiers(record)
        primary_location = record.get("primary_location") or {}
        best_oa_location = record.get("best_oa_location") or {}
        open_access = record.get("open_access") or {}
        doi = identifiers.get("doi", "")
        landing_url = openalex_landing_url(record, primary_location)
        pdf_url = openalex_pdf_url(best_oa_location, primary_location)
        oa_status = normalize_spaces(open_access.get("oa_status") or "")
        source_record = {
            "source_id": "openalex",
            "source_paper_id": openalex_id,
            "query_url": query_url,
            "publication_date": normalize_spaces(record.get("publication_date") or ""),
            "type": normalize_spaces(record.get("type") or ""),
            "open_access": open_access,
            "cited_by_count": int_or_none(record.get("cited_by_count")),
            "concepts": record.get("concepts") or [],
            "topics": record.get("topics") or [],
        }
        papers.append(
            create_radar_paper(
                source_id="openalex",
                source_paper_id=openalex_id,
                title=title,
                authors=openalex_authors(record),
                abstract=abstract_from_openalex_index(record.get("abstract_inverted_index") or {}),
                year=int_or_none(record.get("publication_year")),
                venue=openalex_venue(primary_location),
                identifiers=identifiers,
                links={
                    "landing": landing_url,
                    "openalex": record.get("id") or "",
                    "doi": doi_url(doi),
                    "pdf": pdf_url,
                    "oa_pdf": pdf_url,
                    "oa_status": oa_status,
                },
                discovered_at=collected_at,
                source_record=source_record,
            )
        )
    return papers


def openalex_identifiers(record: dict[str, Any]) -> dict[str, str]:
    ids = record.get("ids") or {}
    doi = clean_doi_identifier(record.get("doi") or ids.get("doi") or "")
    identifiers = {
        "openalex_id": openalex_id_from_url(record.get("id") or ids.get("openalex") or ""),
        "doi": doi,
        "mag_id": normalize_spaces(ids.get("mag") or ""),
        "pmid": normalize_spaces(ids.get("pmid") or ""),
        "pmcid": normalize_spaces(ids.get("pmcid") or ""),
    }
    return {key: value for key, value in identifiers.items() if value}


def openalex_authors(record: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in record.get("authorships") or []:
        author = authorship.get("author") or {}
        name = normalize_spaces(author.get("display_name") or "")
        if name:
            authors.append(name)
    return authors


def openalex_venue(primary_location: dict[str, Any]) -> str:
    source = primary_location.get("source") or {}
    return normalize_spaces(source.get("display_name") or "")


def openalex_landing_url(record: dict[str, Any], primary_location: dict[str, Any]) -> str:
    return normalize_spaces(
        primary_location.get("landing_page_url")
        or record.get("doi")
        or record.get("id")
        or ""
    )


def openalex_pdf_url(best_oa_location: dict[str, Any], primary_location: dict[str, Any]) -> str:
    return normalize_spaces(
        best_oa_location.get("pdf_url")
        or primary_location.get("pdf_url")
        or ""
    )


def abstract_from_openalex_index(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    positioned_words = []
    for word, positions in index.items():
        for position in positions:
            selected_position = int_or_none(position)
            if selected_position is not None:
                positioned_words.append((selected_position, word))
    return normalize_spaces(" ".join(word for _, word in sorted(positioned_words)))


def openalex_id_from_url(value: str) -> str:
    return normalize_spaces(str(value or "").rstrip("/").split("/")[-1])


def collect_openreview_notes(
    *,
    invitations: list[str],
    max_results: int = 50,
    offset: int = 0,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    papers = []
    for invitation in invitations:
        selected_invitation = normalize_spaces(invitation)
        if not selected_invitation:
            continue
        url = build_openreview_notes_url(
            invitation=selected_invitation,
            max_results=max_results,
            offset=offset,
        )
        content = (fetcher or fetch_url)(url)
        papers.extend(
            parse_openreview_notes(
                content,
                invitation=selected_invitation,
                query_url=url,
                collected_at=now,
            )
        )
    return papers


def build_openreview_notes_url(
    *,
    invitation: str,
    max_results: int = 50,
    offset: int = 0,
) -> str:
    params = {
        "invitation": invitation,
        "limit": str(max(1, min(1000, max_results))),
        "offset": str(max(0, offset)),
        "sort": "tcdate:desc",
    }
    return f"{OPENREVIEW_API2_NOTES_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_openreview_notes(
    content: bytes | str,
    *,
    invitation: str = "",
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    notes = payload.get("notes") or payload.get("results") or []
    papers = []
    for note in notes:
        note_id = normalize_spaces(note.get("id") or "")
        if not note_id:
            continue
        note_content = note.get("content") or {}
        title = openreview_content_text(note_content, "title")
        if not title:
            continue
        abstract = openreview_content_text(note_content, "abstract")
        authors = openreview_content_list(note_content, "authors")
        keywords = openreview_content_list(note_content, "keywords")
        pdf_url = openreview_pdf_url(note_id, openreview_content_text(note_content, "pdf"))
        venue = openreview_content_text(note_content, "venue") or openreview_venue_from_invitation(
            invitation or normalize_spaces(note.get("invitation") or "")
        )
        forum_id = normalize_spaces(note.get("forum") or note_id)
        source_record = {
            "source_id": "openreview",
            "source_paper_id": note_id,
            "query_url": query_url,
            "invitation": normalize_spaces(note.get("invitation") or invitation),
            "forum": forum_id,
            "number": note.get("number"),
            "venue": venue,
            "keywords": keywords,
            "tl_dr": openreview_content_text(note_content, "TL;DR"),
            "decision": openreview_content_text(note_content, "decision"),
            "cdate": note.get("cdate"),
            "tcdate": note.get("tcdate"),
            "pdate": note.get("pdate"),
        }
        paper = create_radar_paper(
            source_id="openreview",
            source_paper_id=note_id,
            title=title,
            authors=authors,
            abstract=abstract,
            year=openreview_note_year(note),
            venue=venue,
            identifiers=openreview_identifiers(note_content),
            links={
                "landing": f"{OPENREVIEW_WEB_URL}/forum?id={forum_id}",
                "openreview": f"{OPENREVIEW_WEB_URL}/forum?id={forum_id}",
                "pdf": pdf_url,
            },
            discovered_at=collected_at,
            source_record=source_record,
        )
        if keywords:
            paper["tags"] = keywords
        papers.append(paper)
    return papers


def openreview_content_value(content: dict[str, Any], key: str) -> Any:
    if key not in content:
        return None
    value = content.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def openreview_content_text(content: dict[str, Any], key: str) -> str:
    value = openreview_content_value(content, key)
    if isinstance(value, list):
        return normalize_spaces(", ".join(str(item) for item in value))
    return normalize_spaces(value or "")


def openreview_content_list(content: dict[str, Any], key: str) -> list[str]:
    value = openreview_content_value(content, key)
    if isinstance(value, list):
        return [item for item in (normalize_spaces(item) for item in value) if item]
    if value:
        return [item for item in (normalize_spaces(part) for part in str(value).split(",")) if item]
    return []


def openreview_identifiers(content: dict[str, Any]) -> dict[str, str]:
    identifiers = {
        "doi": clean_doi_identifier(openreview_content_text(content, "doi") or openreview_content_text(content, "DOI")),
        "arxiv_id": normalize_spaces(
            openreview_content_text(content, "arxiv_id")
            or openreview_content_text(content, "arxiv")
        ),
    }
    return {key: value for key, value in identifiers.items() if value}


def openreview_pdf_url(note_id: str, pdf_value: str) -> str:
    value = normalize_spaces(pdf_value)
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"{OPENREVIEW_WEB_URL}{value}"
    if value:
        return f"{OPENREVIEW_WEB_URL}/{value.lstrip('/')}"
    return ""


def openreview_venue_from_invitation(invitation: str) -> str:
    if not invitation:
        return "OpenReview"
    return normalize_spaces(invitation.split("/-/")[0].replace("/", " "))


def openreview_note_year(note: dict[str, Any]) -> int | None:
    for field in ("pdate", "tcdate", "cdate"):
        value = int_or_none(note.get(field))
        if value:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).year
    invitation = normalize_spaces(note.get("invitation") or "")
    match = re.search(r"/(20[0-9]{2})/", invitation)
    return int(match.group(1)) if match else None


def collect_semantic_scholar_search(
    *,
    query_terms: list[str],
    max_results: int = 50,
    offset: int = 0,
    api_key: str | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    url = build_semantic_scholar_search_url(
        query_terms=query_terms,
        max_results=max_results,
        offset=offset,
    )
    if fetcher:
        content = fetcher(url)
    else:
        headers = {"x-api-key": api_key} if api_key else None
        content = fetch_url(url, headers=headers)
    return parse_semantic_scholar_search(content, query_url=url, collected_at=now)


def build_semantic_scholar_search_url(
    *,
    query_terms: list[str],
    max_results: int = 50,
    offset: int = 0,
    fields: list[str] | None = None,
) -> str:
    query = " ".join(term.strip() for term in query_terms if term.strip())
    params = {
        "query": query,
        "limit": str(max(1, min(100, max_results))),
        "offset": str(max(0, offset)),
        "fields": ",".join(fields or SEMANTIC_SCHOLAR_FIELDS),
    }
    return f"{SEMANTIC_SCHOLAR_PAPER_SEARCH_URL}?{urlencode(params, quote_via=quote_plus)}"


def parse_semantic_scholar_search(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    papers = []
    for record in payload.get("data") or []:
        title = normalize_spaces(record.get("title") or "")
        paper_id = normalize_spaces(record.get("paperId") or "")
        if not title or not paper_id:
            continue
        external_ids = record.get("externalIds") or {}
        identifiers = semantic_scholar_identifiers(record, external_ids)
        landing_url = normalize_spaces(record.get("url") or "")
        doi = identifiers.get("doi", "")
        arxiv_id = identifiers.get("arxiv_id", "")
        open_access_pdf = record.get("openAccessPdf") or {}
        pdf_url = normalize_spaces(open_access_pdf.get("url") or "")
        links = {
            "landing": landing_url,
            "semantic_scholar": landing_url,
            "doi": doi_url(doi),
            "arxiv": arxiv_url(arxiv_id),
            "pdf": pdf_url,
            "oa_pdf": pdf_url,
            "oa_status": "open" if record.get("isOpenAccess") else "",
        }
        source_record = {
            "source_id": "semantic_scholar",
            "source_paper_id": paper_id,
            "query_url": query_url,
            "publication_date": normalize_spaces(record.get("publicationDate") or ""),
            "publication_types": [str(value) for value in record.get("publicationTypes") or []],
            "fields_of_study": [str(value) for value in record.get("fieldsOfStudy") or []],
            "s2_fields_of_study": record.get("s2FieldsOfStudy") or [],
            "is_open_access": bool(record.get("isOpenAccess")),
            "open_access_pdf": open_access_pdf,
        }
        papers.append(
            create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id=paper_id,
                title=title,
                authors=semantic_scholar_authors(record.get("authors") or []),
                abstract=record.get("abstract") or "",
                year=int_or_none(record.get("year")),
                venue=record.get("venue") or "",
                identifiers=identifiers,
                links=links,
                discovered_at=collected_at,
                source_record=source_record,
            )
        )
    return papers


def semantic_scholar_identifiers(record: dict[str, Any], external_ids: dict[str, Any]) -> dict[str, str]:
    identifiers = {
        "semantic_scholar_id": normalize_spaces(record.get("paperId") or ""),
        "corpus_id": normalize_spaces(record.get("corpusId") or external_ids.get("CorpusId") or ""),
        "doi": clean_doi_identifier(external_ids.get("DOI") or ""),
        "arxiv_id": normalize_spaces(external_ids.get("ArXiv") or ""),
        "acl_id": normalize_spaces(external_ids.get("ACL") or ""),
        "pubmed_id": normalize_spaces(external_ids.get("PubMed") or ""),
    }
    return {key: value for key, value in identifiers.items() if value}


def semantic_scholar_authors(authors: list[dict[str, Any]]) -> list[str]:
    return [
        author_name
        for author_name in (normalize_spaces(author.get("name") or "") for author in authors)
        if author_name
    ]


def enrich_paper_with_unpaywall(
    paper: dict[str, Any],
    *,
    email: str,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    doi = clean_doi_identifier((paper.get("identifiers") or {}).get("doi") or "")
    if not doi:
        return dict(paper)
    url = build_unpaywall_doi_url(doi=doi, email=email)
    content = (fetcher or fetch_url)(url)
    enrichment = parse_unpaywall_record(content, query_url=url, collected_at=now)
    return apply_unpaywall_enrichment(paper, enrichment)


def build_unpaywall_doi_url(*, doi: str, email: str) -> str:
    params = {"email": email}
    return f"{UNPAYWALL_API_URL}/{quote(clean_doi_identifier(doi), safe='')}?{urlencode(params, quote_via=quote_plus)}"


def parse_unpaywall_record(
    content: bytes | str,
    *,
    query_url: str = "",
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    record = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    doi = clean_doi_identifier(record.get("doi") or "")
    best_location = record.get("best_oa_location") or {}
    oa_locations = record.get("oa_locations") or []
    pdf_url = normalize_spaces(best_location.get("url_for_pdf") or "")
    landing_url = normalize_spaces(best_location.get("url") or "")
    license_text = normalize_spaces(best_location.get("license") or record.get("license") or "")
    source_record = {
        "source_id": "unpaywall",
        "source_paper_id": doi,
        "query_url": query_url,
        "collected_at": (collected_at or datetime.now(timezone.utc)).isoformat(),
        "is_oa": bool(record.get("is_oa")),
        "oa_status": normalize_spaces(record.get("oa_status") or ""),
        "best_oa_location": best_location,
        "oa_locations": oa_locations,
        "genre": normalize_spaces(record.get("genre") or ""),
        "journal_name": normalize_spaces(record.get("journal_name") or ""),
        "publisher": normalize_spaces(record.get("publisher") or ""),
    }
    return {
        "doi": doi,
        "is_oa": bool(record.get("is_oa")),
        "oa_status": source_record["oa_status"],
        "pdf_url": pdf_url,
        "landing_url": landing_url,
        "license": license_text,
        "host_type": normalize_spaces(best_location.get("host_type") or ""),
        "version": normalize_spaces(best_location.get("version") or ""),
        "source_record": source_record,
    }


def apply_unpaywall_enrichment(paper: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    updated = dict(paper)
    links = dict(updated.get("links") or {})
    identifiers = dict(updated.get("identifiers") or {})
    if enrichment.get("doi"):
        identifiers["doi"] = enrichment["doi"]
        links.setdefault("doi", doi_url(enrichment["doi"]))
    if enrichment.get("landing_url"):
        links.setdefault("landing", enrichment["landing_url"])
        links["oa_landing"] = enrichment["landing_url"]
    if enrichment.get("pdf_url"):
        links.setdefault("pdf", enrichment["pdf_url"])
        links["oa_pdf"] = enrichment["pdf_url"]
    if enrichment.get("oa_status"):
        links["oa_status"] = enrichment["oa_status"]
        updated["oa_status"] = enrichment["oa_status"]
    if enrichment.get("license"):
        links["license"] = enrichment["license"]
        updated["license"] = enrichment["license"]
    updated["identifiers"] = identifiers
    updated["links"] = links
    updated["source_records"] = [*(updated.get("source_records") or []), enrichment["source_record"]]
    updated["updated_at"] = enrichment["source_record"]["collected_at"]
    return updated


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


def arxiv_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""


def clean_doi_identifier(value: Any) -> str:
    text = normalize_spaces(value or "")
    lowered = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"):
        if lowered.startswith(prefix):
            return text[len(prefix):]
    return text
