"""Normal browser search and bounded multi-source research for JARVIS."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
import hashlib
import ipaddress
import os
import re
from typing import Callable, Iterable, Sequence
from urllib.parse import parse_qsl, quote_plus, unquote, urlencode, urlparse, urlunparse
import webbrowser
import xml.etree.ElementTree as ElementTree

import requests
from bs4 import BeautifulSoup


DEFAULT_SEARCH_URL = "https://www.google.com/search?q={query}"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
BING_RSS_URL = "https://www.bing.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
_GENERIC_RESEARCH_TERMS = {
    "advantage", "advantages", "benefit", "benefits", "effect", "effects", "impact",
    "impacts", "importance", "overview", "role", "way", "ways",
}


@dataclass(frozen=True)
class BrowserSearchResult:
    success: bool
    query: str
    url: str
    message: str
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SearchSource:
    title: str
    url: str
    snippet: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PageContent:
    title: str
    url: str
    text: str


@dataclass
class AdvancedSearchResult:
    success: bool
    query: str
    summary: str
    sources: list[SearchSource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        if self.success:
            return f"Advanced search completed using {len(self.sources)} readable sources."
        return "Advanced search could not gather enough readable source material."

    def as_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "query": self.query,
            "summary": self.summary,
            "sources": [source.as_dict() for source in self.sources],
            "errors": list(self.errors),
            "message": self.message,
        }

    def format_for_user(self) -> str:
        lines = ["SUMMARY", self.summary.strip() or self.message, "", "SOURCES"]
        if self.sources:
            lines.extend(
                f"{index}. {source.title}\n   {source.url}"
                for index, source in enumerate(self.sources, start=1)
            )
        else:
            lines.append("No readable sources were available.")
        if self.errors:
            lines.extend(("", "NOTES", *self.errors))
        return "\n".join(lines)


def normal_search(
    query: str,
    *,
    opener: Callable[[str], object] = webbrowser.open_new_tab,
    search_url: str = DEFAULT_SEARCH_URL,
) -> BrowserSearchResult:
    """Open a standard search page in the user's default browser."""

    cleaned_query = " ".join((query or "").strip().split())
    if not cleaned_query:
        return BrowserSearchResult(False, cleaned_query, "", "No search query was provided.")

    url = search_url.format(query=quote_plus(cleaned_query))
    try:
        opened = opener(url)
        if opened is False:
            return BrowserSearchResult(
                False, cleaned_query, url, "The default browser did not accept the search request."
            )
        return BrowserSearchResult(
            True, cleaned_query, url, f"Opened search results for {cleaned_query}."
        )
    except Exception as exc:
        return BrowserSearchResult(
            False,
            cleaned_query,
            url,
            f"Could not open search results for {cleaned_query}.",
            error=str(exc),
        )


def _decode_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        redirect_target = dict(parse_qsl(parsed.query)).get("uddg")
        if redirect_target:
            return unquote(redirect_target)
    return raw_url


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"fbclid", "gclid", "ref", "ref_src"}
    ]
    netloc = parsed.netloc.casefold()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunparse(
        (
            parsed.scheme.casefold() or "https",
            netloc,
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(filtered_query),
            "",
        )
    )


def _low_value_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    path = parsed.path.casefold()
    if parsed.scheme not in {"http", "https"} or not host:
        return True
    hostname = parsed.hostname or ""
    if hostname.casefold() == "localhost" or hostname.casefold().endswith(".local"):
        return True
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return True
    except ValueError:
        pass
    if any(
        blocked in host
        for blocked in ("duckduckgo.com", "google.com", "bing.com", "facebook.com", "pinterest.com")
    ):
        return True
    return path.endswith((".pdf", ".doc", ".docx", ".ppt", ".pptx", ".zip"))


def parse_search_results(html: str, max_results: int = 8) -> list[SearchSource]:
    """Parse DuckDuckGo's lightweight HTML results with URL de-duplication."""

    soup = BeautifulSoup(html or "", "html.parser")
    results: list[SearchSource] = []
    seen: set[str] = set()

    for container in soup.select(".result"):
        anchor = container.select_one("a.result__a")
        if anchor is None:
            continue
        raw_url = anchor.get("href", "")
        url = _decode_result_url(raw_url)
        if _low_value_url(url):
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        snippet_element = container.select_one(".result__snippet")
        title = " ".join(anchor.get_text(" ", strip=True).split())
        snippet = (
            " ".join(snippet_element.get_text(" ", strip=True).split())
            if snippet_element is not None
            else ""
        )
        if title:
            results.append(SearchSource(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def parse_bing_rss_results(xml_text: str, max_results: int = 8) -> list[SearchSource]:
    """Parse Bing's small RSS search response as a fallback source index."""

    root = ElementTree.fromstring(xml_text or "")
    results: list[SearchSource] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = " ".join((item.findtext("title") or "").split())
        url = (item.findtext("link") or "").strip()
        description_html = item.findtext("description") or ""
        snippet = " ".join(
            BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True).split()
        )
        if not title or _low_value_url(url):
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        results.append(SearchSource(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def parse_ddgs_results(
    raw_results: Iterable[dict[str, object]], max_results: int = 8
) -> list[SearchSource]:
    """Normalize the maintained DDGS metasearch result shape."""

    results: list[SearchSource] = []
    seen: set[str] = set()
    for raw in raw_results:
        title = " ".join(str(raw.get("title") or "").split())
        url = str(raw.get("href") or raw.get("url") or "").strip()
        snippet = " ".join(str(raw.get("body") or raw.get("snippet") or "").split())
        if not title or _low_value_url(url):
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        results.append(SearchSource(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def _relevant_sources(
    sources: Sequence[SearchSource], query: str, max_results: int
) -> list[SearchSource]:
    core_terms = set(_keywords(query)).difference(_GENERIC_RESEARCH_TERMS)
    if not core_terms:
        core_terms = set(_keywords(query))
    minimum_overlap = 1 if len(core_terms) <= 2 else 2
    relevant: list[SearchSource] = []
    for source in sources:
        source_terms = set(_keywords(f"{source.title} {source.snippet}"))
        if len(core_terms.intersection(source_terms)) >= minimum_overlap:
            relevant.append(source)
        if len(relevant) >= max_results:
            break
    return relevant


def _unique_sources(
    sources: Iterable[SearchSource], max_results: int
) -> list[SearchSource]:
    unique: list[SearchSource] = []
    seen: set[str] = set()
    for source in sources:
        canonical = _canonical_url(source.url)
        if canonical in seen:
            continue
        seen.add(canonical)
        unique.append(source)
        if len(unique) >= max_results:
            break
    return unique


def search_web_sources(
    query: str,
    *,
    max_results: int = 8,
    timeout: float = 10,
    session: requests.Session | None = None,
) -> list[SearchSource]:
    """Retrieve a small set of public search-result links."""

    cleaned_query = " ".join((query or "").strip().split())
    if not cleaned_query:
        return []

    results: list[SearchSource] = []
    backend_errors: list[str] = []
    try:
        from ddgs import DDGS

        ddgs_results = DDGS(timeout=int(max(3, timeout))).text(
            cleaned_query,
            region="us-en",
            safesearch="moderate",
            max_results=max_results * 2,
            backend="auto",
        )
        results = _relevant_sources(
            parse_ddgs_results(ddgs_results, max_results=max_results * 2),
            cleaned_query,
            max_results,
        )
        if len(results) >= min(2, max_results):
            return _unique_sources(results, max_results)
    except Exception as exc:
        # Lightweight direct endpoints below keep search usable if the optional
        # metasearch backend is temporarily unavailable.
        backend_errors.append(f"DDGS: {exc}")

    requester = session or requests
    try:
        response = requester.get(
            DUCKDUCKGO_HTML_URL,
            params={"q": cleaned_query},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        results.extend(_relevant_sources(
            parse_search_results(response.text, max_results=max_results * 2),
            cleaned_query,
            max_results,
        ))
    except Exception as exc:
        backend_errors.append(f"DuckDuckGo: {exc}")
    results = _unique_sources(results, max_results)
    if len(results) >= min(2, max_results):
        return results

    # DuckDuckGo sometimes responds with a human-verification page (commonly
    # HTTP 202). Bing RSS is a compact public fallback and avoids scraping a
    # full visual result page.
    try:
        response = requester.get(
            BING_RSS_URL,
            params={"q": cleaned_query, "format": "rss"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        rss_results = parse_bing_rss_results(response.text, max_results=max_results * 2)
        results.extend(_relevant_sources(rss_results, cleaned_query, max_results))
    except Exception as exc:
        backend_errors.append(f"Bing RSS: {exc}")
    results = _unique_sources(results, max_results)

    # Some engines over-weight generic leading words such as "benefits" or
    # "impact". If relevance filtering leaves too little, retry once using the
    # concrete subject terms only.
    if len(results) < min(2, max_results):
        core_terms = [
            term for term in _keywords(cleaned_query) if term not in _GENERIC_RESEARCH_TERMS
        ]
        # Try at most three rotations. This counteracts engines that interpret
        # an ambiguous first word as a brand/category (for example "modular")
        # while keeping request volume tightly bounded.
        refined_queries = []
        for pivot in range(min(3, len(core_terms))):
            refined_query = " ".join(core_terms[pivot:] + core_terms[:pivot])
            if (
                refined_query
                and refined_query.casefold() != cleaned_query.casefold()
                and refined_query not in refined_queries
            ):
                refined_queries.append(refined_query)
        for refined_query in refined_queries:
            try:
                refined_response = requester.get(
                    BING_RSS_URL,
                    params={"q": refined_query, "format": "rss"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=timeout,
                )
                refined_response.raise_for_status()
                refined_results = parse_bing_rss_results(
                    refined_response.text, max_results=max_results * 2
                )
                results.extend(_relevant_sources(refined_results, cleaned_query, max_results))
                results = _unique_sources(results, max_results)
                if len(results) >= min(2, max_results):
                    break
            except Exception as exc:
                backend_errors.append(f"Bing RSS ({refined_query}): {exc}")

    if not results and backend_errors:
        raise RuntimeError("; ".join(backend_errors))

    return _unique_sources(results, max_results)


def _clean_extracted_text(text: str, max_words: int) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    words = compact.split()
    return " ".join(words[:max_words])


def extract_page_content(
    url: str,
    *,
    timeout: float = 9,
    max_words: int = 1_600,
    session: requests.Session | None = None,
) -> PageContent:
    """Fetch and extract the meaningful HTML text from one page."""

    requester = session or requests
    if _low_value_url(url):
        raise ValueError("unsafe or unsupported source URL")
    response = requester.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    if _low_value_url(response.url):
        raise ValueError("source redirected to an unsafe or unsupported URL")
    content_type = response.headers.get("Content-Type", "text/html").casefold()
    if "html" not in content_type and "text" not in content_type:
        raise ValueError(f"unsupported content type: {content_type}")

    soup = BeautifulSoup(response.text, "html.parser")
    title = ""
    if soup.title:
        title = " ".join(soup.title.get_text(" ", strip=True).split())
    for tag in soup.select(
        "script, style, nav, footer, header, aside, form, noscript, svg, canvas, iframe"
    ):
        tag.decompose()

    content = soup.find("article") or soup.find("main") or soup.select_one('[role="main"]')
    content = content or soup.body
    if content is None:
        raise ValueError("page did not contain readable HTML")

    paragraphs = [
        element.get_text(" ", strip=True)
        for element in content.find_all(("p", "li", "h1", "h2", "h3"))
    ]
    raw_text = " ".join(paragraph for paragraph in paragraphs if len(paragraph.split()) >= 4)
    if not raw_text:
        raw_text = content.get_text(" ", strip=True)
    text = _clean_extracted_text(raw_text, max_words)
    if len(text.split()) < 60:
        raise ValueError("page contained too little meaningful text")
    return PageContent(title=title, url=url, text=text)


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
    "do", "has", "have", "how", "if", "in", "into", "is", "it", "its", "no", "of",
    "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "what", "when", "which", "who", "will",
    "with", "would", "you", "your", "we", "up",
}


def _keywords(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'-]+", text.casefold())
        if token not in _STOP_WORDS and len(token) >= 2
    ]


def extractive_summary(
    query: str,
    pages: Sequence[PageContent],
    *,
    max_sentences: int = 6,
) -> str:
    """Build a deterministic fallback summary when no LLM is configured."""

    query_terms = set(_keywords(query))
    all_terms = Counter(_keywords(" ".join(page.text for page in pages)))
    candidates: list[tuple[float, int, int, str]] = []

    for source_index, page in enumerate(pages):
        sentences = re.split(r"(?<=[.!?])\s+", page.text)
        for sentence_index, sentence in enumerate(sentences):
            sentence = sentence.strip()
            words = sentence.split()
            if not 8 <= len(words) <= 65:
                continue
            lowered = sentence.casefold()
            if any(noise in lowered for noise in ("accept cookies", "privacy policy", "sign up", "subscribe")):
                continue
            terms = _keywords(sentence)
            if not terms:
                continue
            overlap = len(query_terms.intersection(terms))
            frequency_score = sum(all_terms[term] for term in set(terms)) / len(set(terms))
            position_bonus = max(0.0, 1.5 - sentence_index * 0.08)
            score = overlap * 5.0 + frequency_score + position_bonus
            candidates.append((score, source_index, sentence_index, sentence))

    selected: list[tuple[float, int, int, str]] = []
    per_source: Counter[int] = Counter()
    fingerprints: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
        _, source_index, _, sentence = candidate
        fingerprint = " ".join(_keywords(sentence)[:16])
        if not fingerprint or fingerprint in fingerprints or per_source[source_index] >= 2:
            continue
        fingerprints.add(fingerprint)
        per_source[source_index] += 1
        selected.append(candidate)
        if len(selected) >= max_sentences:
            break

    if not selected:
        return "Readable sources were found, but their text could not be summarized reliably."

    selected.sort(key=lambda item: (-item[0], item[1], item[2]))
    findings = [f"- {sentence} [{source_index + 1}]" for _, source_index, _, sentence in selected]
    return "Key findings from the retrieved pages:\n" + "\n".join(findings)


def _openrouter_summary(query: str, pages: Sequence[PageContent]) -> str | None:
    """Optionally synthesize with OpenRouter when both key and model are configured."""

    api_key = os.getenv("OPENROUTER_KEY") or os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("JARVIS_RESEARCH_MODEL")
    if not api_key or not model:
        return None

    excerpts: list[str] = []
    remaining = 18_000
    for index, page in enumerate(pages, start=1):
        block = f"SOURCE [{index}] {page.title}\nURL: {page.url}\n{page.text}\n"
        if remaining <= 0:
            break
        excerpts.append(block[:remaining])
        remaining -= len(block)

    prompt = (
        "Answer the research question using only the supplied sources. Synthesize rather than "
        "copying. State uncertainty or disagreement. Use compact paragraphs or bullets and cite "
        "claims with bracketed source numbers such as [1]. Do not invent sources.\n\n"
        f"QUESTION: {query}\n\n" + "\n".join(excerpts)
    )
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a careful research synthesizer."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 800,
            "temperature": 0.2,
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"].get("content") or "").strip() or None


def _content_fingerprint(text: str) -> str:
    normalized = re.sub(r"\W+", " ", text.casefold()).strip()[:1_200]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def advanced_search(
    query: str,
    *,
    max_sources: int = 6,
    searcher: Callable[..., list[SearchSource]] = search_web_sources,
    fetcher: Callable[..., PageContent] = extract_page_content,
    summarizer: Callable[[str, Sequence[PageContent]], str] | None = None,
) -> AdvancedSearchResult:
    """Search, read a bounded set of pages, de-duplicate, and summarize them."""

    cleaned_query = " ".join((query or "").strip().split())
    if not cleaned_query:
        return AdvancedSearchResult(False, cleaned_query, "No research question was provided.")
    if not 1 <= max_sources <= 12:
        raise ValueError("max_sources must be between 1 and 12")

    errors: list[str] = []
    try:
        candidates = searcher(cleaned_query, max_results=max_sources * 2)
    except Exception as exc:
        return AdvancedSearchResult(
            False,
            cleaned_query,
            "The web search step failed before any sources could be collected.",
            errors=[str(exc)],
        )
    if not candidates:
        return AdvancedSearchResult(
            False,
            cleaned_query,
            "No relevant web results were found.",
        )

    candidates = candidates[: max_sources * 2]

    def fetch(source: SearchSource) -> tuple[SearchSource, PageContent | None, str | None]:
        try:
            return source, fetcher(source.url), None
        except Exception as exc:
            return source, None, str(exc)

    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as executor:
        fetched = list(executor.map(fetch, candidates))

    pages: list[PageContent] = []
    usable_sources: list[SearchSource] = []
    seen_content: set[str] = set()
    for source, page, error in fetched:
        if page is None:
            errors.append(f"Skipped {source.title}: {error or 'unreadable page'}")
            continue
        fingerprint = _content_fingerprint(page.text)
        if fingerprint in seen_content:
            continue
        seen_content.add(fingerprint)
        page_title = page.title or source.title
        pages.append(PageContent(page_title, source.url, page.text))
        usable_sources.append(SearchSource(page_title, source.url, source.snippet))
        if len(pages) >= max_sources:
            break

    if not pages:
        return AdvancedSearchResult(
            False,
            cleaned_query,
            "Search results were found, but none of the pages exposed enough readable content.",
            sources=candidates[:max_sources],
            errors=errors,
        )

    summary = ""
    if summarizer is not None:
        try:
            summary = (summarizer(cleaned_query, pages) or "").strip()
        except Exception as exc:
            errors.append(f"Configured summarizer failed; used extractive summary: {exc}")
    else:
        try:
            summary = (_openrouter_summary(cleaned_query, pages) or "").strip()
        except Exception as exc:
            errors.append(f"LLM synthesis failed; used extractive summary: {exc}")
    if not summary:
        summary = extractive_summary(cleaned_query, pages)

    return AdvancedSearchResult(
        True,
        cleaned_query,
        summary,
        sources=usable_sources,
        errors=errors,
    )


search = normal_search
research = advanced_search
