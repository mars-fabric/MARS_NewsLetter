# MARS-NewsLetter: Custom Tools and Integrations Developer Guide

This guide explains how to extend the MARS-NewsLetter pipeline with user-defined tools
and custom integrations at runtime. It covers everything from the underlying tool
registration architecture through complete, production-ready examples for premium search
APIs, internal knowledge bases, LangChain tool wrapping, and end-to-end wiring into
the backend.

---

## Table of Contents

1. [How Tools Work in the Pipeline](#1-how-tools-work-in-the-pipeline)
2. [Adding a Custom Search Tool](#2-adding-a-custom-search-tool)
3. [Adding Any Callable Tool at Runtime](#3-adding-any-callable-tool-at-runtime)
4. [LangChain Tool Integration](#4-langchain-tool-integration)
5. [Premium Search Tool Examples](#5-premium-search-tool-examples)
6. [Internal Knowledge Base Tool](#6-internal-knowledge-base-tool)
7. [Tool Timeout and Error Handling](#7-tool-timeout-and-error-handling)
8. [Environment Variable Config for Tools](#8-environment-variable-config-for-tools)
9. [End-to-End Example: Replacing DDGS with Brave Search](#9-end-to-end-example-replacing-ddgs-with-brave-search)

---

## 1. How Tools Work in the Pipeline

### Pipeline overview

The NewsLetter pipeline runs in five stages. Stage 2 (Source Collection) and Stage 3
(Curation) are where web-search tools are exercised by the **researcher agent** —
the AG2 `ConversableAgent` that is given a task and a tool belt to execute it.

```
Stage 1  Setup            deterministic
    ↓
Stage 2  Source Collection  researcher agent runs DDGS / Wikipedia /
                            custom tools to find company news
    ↓
Stage 3  Curation           researcher agent curates and ranks raw results
    ↓
Stage 4  Generation         section-by-section newsletter writing
    ↓
Stage 5  Review             LangGraph critic + editor + PDF
```

### How `enable_ag2_free_tools=True` wires tools into the researcher

The backend calls `cmbagent.one_shot()` and
`planning_and_control_context_carryover()` with the flag:

```python
# backend/task_framework/newsletter/mode_dispatcher.py
kwargs: Dict[str, Any] = {
    "task": prompt,
    "agent": agent,
    "work_dir": work_dir,
    "max_rounds": fallback_max_rounds,
    "enable_ag2_free_tools": True,   # <── this flag
    ...
}
return cmbagent.one_shot(**kwargs)
```

When `enable_ag2_free_tools=True`, `mars_cmbagent` calls into the
`cmbagent.external_tools` package which:

1. Loads the built-in free tools (DuckDuckGo, Wikipedia, ArXiv, and the custom news
   scrapers in `cmbagent/external_tools/news_tools.py`).
2. Queries the **global `ExternalToolRegistry`** for any additional tools you have
   registered.
3. Registers all found tools with both the researcher agent (caller) and its executor
   agent using `autogen.register_function()`.

### Tool registration flow

```
Your code
  │
  ▼
cmbagent.external_tools.user_tools.register_tool(fn)
  │
  ▼
ExternalToolRegistry (singleton, lives in cmbagent.external_tools.tool_registry)
  │
  ▼  (at solve/one_shot time)
ExternalToolRegistry.register_with_agent(researcher_agent, executor_agent)
  │
  ▼
autogen.register_function(
    fn,
    caller=researcher_agent,
    executor=executor_agent,
    name="...",
    description="...",
)
  │
  ▼
AG2 GroupChat — researcher LLM can now call the function as a tool
```

### Key source files

| File | Purpose |
|------|---------|
| `mars_cmbagent/cmbagent/external_tools/user_tools.py` | Public API for registering tools |
| `mars_cmbagent/cmbagent/external_tools/tool_registry.py` | Global `ExternalToolRegistry` singleton |
| `mars_cmbagent/cmbagent/external_tools/tool_adapter.py` | `AG2ToolAdapter` wrapper + LangChain/CrewAI converters |
| `mars_cmbagent/cmbagent/external_tools/langchain_tools.py` | Built-in LangChain free tool loaders |
| `mars_cmbagent/cmbagent/external_tools/ag2_free_tools.py` | `_build_safe_duckduckgo_tool()` and `AG2FreeToolsLoader` |
| `backend/task_framework/newsletter/mode_dispatcher.py` | Where `enable_ag2_free_tools=True` is set |
| `backend/task_framework/newsletter/source_collector.py` | Stage 2 orchestration — calls `run_ai_stage` |

---

## 2. Adding a Custom Search Tool

### The pattern

A search tool is a plain Python function that accepts a query string and returns a
string. The researcher agent calls it exactly like `duckduckgo_search`. You register
it once before the pipeline starts and it becomes available to every subsequent call.

### Where to add the registration call

Create a file `backend/custom_tools.py` (tracked in version control) and import it
from `backend/main.py` so it runs at server startup:

```python
# backend/main.py  (existing file — add the import near the top)
import custom_tools  # noqa: F401  — registers tools into the global registry
```

### Complete example — Serper.dev (Google Search)

```python
# backend/custom_tools.py

"""Register all user-defined tools with the cmbagent global registry.

Import this module once from main.py. Each function decorated with
@register_tool is added to the singleton ExternalToolRegistry and becomes
available to the researcher agent whenever enable_ag2_free_tools=True.
"""

import os
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="google_search",
    description=(
        "Search Google via Serper.dev and return structured results "
        "including title, link, snippet, and publication date."
    ),
    category="premium_search",
)
def google_search(query: str, num_results: int = 10) -> str:
    """Search Google for recent news and web results.

    Args:
        query: The search query string.
        num_results: Number of results to return (1–100, default 10).

    Returns:
        Formatted string of search results with title, URL, and snippet.
    """
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return "google_search unavailable: SERPER_API_KEY not set."

    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": min(num_results, 100)},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"google_search error: {exc}"

    lines = [f"Google search results for: {query}", ""]
    for idx, item in enumerate(data.get("organic", []), 1):
        title = item.get("title", "Untitled")
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        date = item.get("date", "")
        date_str = f" [{date}]" if date else ""
        lines.append(f"{idx}. {title}{date_str}")
        lines.append(f"   URL: {link}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines) if len(lines) > 2 else "No results found."
```

After adding `import custom_tools` to `backend/main.py`, restart the server and run
a Stage 2 call. The researcher agent will have both `duckduckgo_search` and
`google_search` in its tool belt.

---

## 3. Adding Any Callable Tool at Runtime

### The three registration paths

`cmbagent.external_tools.user_tools` exposes three registration patterns:

**Path 1 — Decorator** (recommended for tools defined in your codebase):

```python
from cmbagent.external_tools import register_tool

@register_tool(name="my_tool", description="What this tool does", category="custom")
def my_tool(query: str) -> str:
    ...
```

**Path 2 — Explicit call** (for tools defined in third-party code):

```python
from cmbagent.external_tools import register_callable

register_callable(some_function, name="my_tool", description="...", category="custom")
```

**Path 3 — Config file** (for deployment-time tool selection without code changes):

```python
from cmbagent.external_tools import load_tools_from_config

load_tools_from_config("/path/to/tools.yaml")
```

### Full example — database lookup tool

```python
# backend/custom_tools.py

import os
import json
from typing import Optional
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="company_database_lookup",
    description=(
        "Look up a company in the internal CRM to retrieve its industry classification, "
        "recent press releases, key executives, and financial metrics."
    ),
    category="internal",
)
def company_database_lookup(
    company_name: str,
    fields: Optional[str] = None,
) -> str:
    """Query the internal company database by name.

    Args:
        company_name: Name of the company to look up (case-insensitive partial match).
        fields: Comma-separated list of fields to return. Defaults to all fields.
                Options: name, industry, press_releases, executives, financials.

    Returns:
        JSON-formatted string with the company record, or an error message.
    """
    base_url = os.environ.get("INTERNAL_API_BASE_URL", "")
    api_key = os.environ.get("INTERNAL_API_KEY", "")

    if not base_url:
        return "company_database_lookup unavailable: INTERNAL_API_BASE_URL not set."

    params = {"q": company_name}
    if fields:
        params["fields"] = fields

    try:
        response = requests.get(
            f"{base_url}/api/companies/search",
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return f"company_database_lookup timed out for query: {company_name}"
    except requests.RequestException as exc:
        return f"company_database_lookup error: {exc}"

    if not data.get("results"):
        return f"No company found matching: {company_name}"

    results = data["results"][:3]  # Return top 3 matches
    return json.dumps(results, indent=2, default=str)
```

### Type hints are important

The AG2 framework inspects the function signature to build the JSON schema for the
LLM's tool-call interface. Always annotate parameters and return types. Use
`Optional[str]` for optional parameters and provide clear docstring descriptions for
each argument — the LLM reads these when deciding how to call the tool.

---

## 4. LangChain Tool Integration

### Overview

Any LangChain `BaseTool` subclass can be converted to an AG2-compatible tool using
`convert_langchain_tool_to_ag2()`. This function uses AG2's native
`autogen.interop.Interoperability` module when available, with a custom adapter as
fallback.

**Integration file:** `mars_cmbagent/cmbagent/external_tools/tool_adapter.py`
**High-level loader:** `mars_cmbagent/cmbagent/external_tools/langchain_tools.py`
**Public import:** `cmbagent.external_tools.convert_langchain_tool_to_ag2`

### Wrapping any LangChain tool

```python
# backend/custom_tools.py

from cmbagent.external_tools import register_callable
from cmbagent.external_tools.tool_adapter import convert_langchain_tool_to_ag2
from cmbagent.external_tools import get_global_registry


def register_langchain_tools():
    """Convert and register LangChain tools into the cmbagent global registry."""

    # ── Tavily Search (requires: pip install langchain-tavily) ────────────────
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        import os
        if os.environ.get("TAVILY_API_KEY"):
            tavily = TavilySearchResults(max_results=10)
            ag2_tavily = convert_langchain_tool_to_ag2(tavily)
            get_global_registry().register_tool(ag2_tavily, category="premium_search")
    except ImportError:
        pass  # langchain-tavily not installed — silently skip

    # ── SerpAPI (requires: pip install langchain-community google-search-results) ──
    try:
        from langchain_community.utilities import SerpAPIWrapper
        from langchain_community.tools import Tool
        import os
        if os.environ.get("SERPAPI_API_KEY"):
            search = SerpAPIWrapper()
            serp_tool = Tool(
                name="serpapi_google_search",
                func=search.run,
                description="Search Google via SerpAPI. Returns organic results with snippets and links.",
            )
            ag2_serp = convert_langchain_tool_to_ag2(serp_tool)
            get_global_registry().register_tool(ag2_serp, category="premium_search")
    except ImportError:
        pass

    # ── Custom LangChain retriever wrapping a vector store ────────────────────
    try:
        from langchain_core.tools import Tool as LCTool
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
        import os
        if os.environ.get("KNOWLEDGE_BASE_PATH") and os.environ.get("OPENAI_API_KEY"):
            embeddings = OpenAIEmbeddings()
            vectorstore = FAISS.load_local(
                os.environ["KNOWLEDGE_BASE_PATH"],
                embeddings,
                allow_dangerous_deserialization=True,
            )
            retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

            def knowledge_base_search(query: str) -> str:
                docs = retriever.get_relevant_documents(query)
                return "\n\n".join(
                    f"[Source: {d.metadata.get('source', 'internal')}]\n{d.page_content}"
                    for d in docs
                )

            kb_tool = LCTool(
                name="internal_knowledge_base",
                func=knowledge_base_search,
                description=(
                    "Search the internal company knowledge base for proprietary data, "
                    "reports, and institutional knowledge not available on the public web."
                ),
            )
            ag2_kb = convert_langchain_tool_to_ag2(kb_tool)
            get_global_registry().register_tool(ag2_kb, category="internal")
    except ImportError:
        pass


# Register on import
register_langchain_tools()
```

### Using the built-in `get_langchain_search_tools()` loader

If you want to reload the standard free tools (DuckDuckGo + Wikipedia + ArXiv) and
add them back alongside your premium tools:

```python
from cmbagent.external_tools import get_langchain_search_tools, get_global_registry

standard_tools = get_langchain_search_tools()
for tool in standard_tools:
    get_global_registry().register_tool(tool, category="free_search")
```

---

## 5. Premium Search Tool Examples

### 5.1 Brave Search API

Brave Search provides a high-quality, privacy-first alternative to DDGS with a
dedicated news endpoint and date filtering.

```python
# backend/custom_tools.py

import os
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="brave_search",
    description=(
        "Search the web via Brave Search API. Returns high-quality, "
        "privacy-preserving results with news, web, and discussion tabs."
    ),
    category="premium_search",
)
def brave_search(query: str, num_results: int = 10, freshness: str = "pw") -> str:
    """Search the web using the Brave Search API.

    Args:
        query: The search query string.
        num_results: Number of results to return (1–20, default 10).
        freshness: Date filter — 'pd' (past day), 'pw' (past week),
                   'pm' (past month), 'py' (past year). Default 'pw'.

    Returns:
        Formatted string of search results with title, URL, snippet, and age.
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not api_key:
        return "brave_search unavailable: BRAVE_SEARCH_API_KEY not set."

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            params={
                "q": query,
                "count": min(num_results, 20),
                "freshness": freshness,
                "text_decorations": False,
                "search_lang": "en",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"brave_search error: {exc}"

    web_results = data.get("web", {}).get("results", [])
    news_results = data.get("news", {}).get("results", [])
    all_results = news_results + web_results  # news first for freshness

    if not all_results:
        return f"No Brave Search results for: {query}"

    lines = [f"Brave Search results for: {query}", ""]
    for idx, item in enumerate(all_results[:num_results], 1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        snippet = item.get("description", "")
        age = item.get("age", "")
        age_str = f" ({age})" if age else ""
        lines.append(f"{idx}. {title}{age_str}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet[:300]}")
        lines.append("")

    return "\n".join(lines)
```

### 5.2 Serper.dev — Google News Search

```python
import os
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="google_news_search",
    description=(
        "Search Google News via Serper.dev. Returns recent news articles "
        "with title, source, link, snippet, and publication date."
    ),
    category="premium_search",
)
def google_news_search(query: str, num_results: int = 10) -> str:
    """Search Google News for recent articles.

    Args:
        query: The search query string. Include date qualifiers for freshness,
               e.g. 'AI agents 2026' or 'OpenAI announcement site:techcrunch.com'.
        num_results: Number of articles to return (1–100, default 10).

    Returns:
        Formatted news articles with source, date, title, link, and snippet.
    """
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return "google_news_search unavailable: SERPER_API_KEY not set."

    try:
        response = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": min(num_results, 100)},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"google_news_search error: {exc}"

    news_items = data.get("news", [])
    if not news_items:
        return f"No news found for: {query}"

    lines = [f"Google News results for: {query}", ""]
    for idx, item in enumerate(news_items, 1):
        title = item.get("title", "Untitled")
        source = item.get("source", "Unknown source")
        date = item.get("date", "")
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        date_str = f" — {date}" if date else ""
        lines.append(f"{idx}. [{source}{date_str}] {title}")
        lines.append(f"   URL: {link}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines)
```

### 5.3 Exa.ai — Semantic Search

Exa provides neural/semantic search — useful for finding conceptually related
content that keyword search misses.

```python
import os
from datetime import datetime, timedelta
from cmbagent.external_tools import register_tool


@register_tool(
    name="exa_semantic_search",
    description=(
        "Search the web semantically via Exa.ai. Finds conceptually similar "
        "content even without exact keyword matches. Best for research topics, "
        "emerging trends, and broad industry analysis."
    ),
    category="premium_search",
)
def exa_semantic_search(
    query: str,
    num_results: int = 10,
    days_back: int = 30,
    use_autoprompt: bool = True,
) -> str:
    """Perform semantic/neural search via Exa.ai.

    Args:
        query: Natural language query or topic description.
        num_results: Number of results to return (1–25, default 10).
        days_back: Restrict results to the last N days (default 30).
        use_autoprompt: Let Exa rewrite the query for better semantic matching.

    Returns:
        Formatted search results with title, URL, date, and highlighted text.
    """
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return "exa_semantic_search unavailable: EXA_API_KEY not set."

    # Exa requires the exa-py client (pip install exa-py)
    try:
        from exa_py import Exa
    except ImportError:
        return "exa_semantic_search unavailable: install exa-py with `pip install exa-py`."

    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

    try:
        exa_client = Exa(api_key=api_key)
        results = exa_client.search_and_contents(
            query,
            type="neural",
            use_autoprompt=use_autoprompt,
            num_results=min(num_results, 25),
            start_published_date=start_date,
            highlights={"num_sentences": 3},
        )
    except Exception as exc:
        return f"exa_semantic_search error: {exc}"

    if not results.results:
        return f"No Exa results for: {query}"

    lines = [f"Exa semantic search results for: {query}", ""]
    for idx, result in enumerate(results.results, 1):
        title = result.title or "Untitled"
        url = result.url or ""
        date = (result.published_date or "")[:10]
        date_str = f" [{date}]" if date else ""
        highlights = result.highlights or []
        highlight_text = " … ".join(highlights[:2]) if highlights else ""
        lines.append(f"{idx}. {title}{date_str}")
        lines.append(f"   URL: {url}")
        if highlight_text:
            lines.append(f"   Excerpt: {highlight_text[:400]}")
        lines.append("")

    return "\n".join(lines)
```

---

## 6. Internal Knowledge Base Tool

When newsletter content should be enriched with proprietary data (company product
roadmaps, internal research reports, customer success stories), register a tool that
bridges the researcher to your internal systems. The LLM will call it alongside web
search to combine public and proprietary signals.

### 6.1 REST API knowledge base

```python
# backend/custom_tools.py

import os
import json
from typing import Optional
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="internal_knowledge_base",
    description=(
        "Query the Infosys internal knowledge base for proprietary research, "
        "product announcements, client case studies, and analyst reports. "
        "Use this in addition to web search to include non-public information "
        "in the newsletter. Always cite the source as 'Internal KB'."
    ),
    category="internal",
)
def internal_knowledge_base(
    query: str,
    categories: Optional[str] = None,
    max_results: int = 5,
) -> str:
    """Search the internal knowledge base for proprietary content.

    Args:
        query: Natural language query describing the information needed.
        categories: Optional comma-separated list of content categories to restrict to.
                    Options: research_reports, product_announcements,
                    case_studies, analyst_notes, press_releases.
        max_results: Maximum number of documents to return (1–20, default 5).

    Returns:
        Formatted string of internal documents with title, source, date,
        and excerpt. Cites each document as 'Internal KB'.
    """
    base_url = os.environ.get("INTERNAL_KB_BASE_URL", "")
    api_key = os.environ.get("INTERNAL_KB_API_KEY", "")

    if not base_url:
        return "internal_knowledge_base unavailable: INTERNAL_KB_BASE_URL not set."

    payload: dict = {"query": query, "max_results": min(max_results, 20)}
    if categories:
        payload["categories"] = [c.strip() for c in categories.split(",")]

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return f"internal_knowledge_base timed out for: {query}"
    except requests.RequestException as exc:
        return f"internal_knowledge_base error: {exc}"

    documents = data.get("documents", [])
    if not documents:
        return f"No internal documents found for: {query}"

    lines = [f"Internal Knowledge Base results for: {query}", ""]
    for idx, doc in enumerate(documents, 1):
        title = doc.get("title", "Untitled")
        source = doc.get("source", "Internal KB")
        date = doc.get("date", "")
        category = doc.get("category", "")
        excerpt = doc.get("excerpt", doc.get("summary", ""))
        date_str = f" [{date}]" if date else ""
        cat_str = f" ({category})" if category else ""
        lines.append(f"{idx}. [Internal KB]{date_str}{cat_str} {title}")
        lines.append(f"   Source: {source}")
        if excerpt:
            lines.append(f"   Excerpt: {excerpt[:500]}")
        lines.append("")

    return "\n".join(lines)
```

### 6.2 Vector database (FAISS / Chroma) without LangChain

```python
import os
import json
from cmbagent.external_tools import register_tool


@register_tool(
    name="vector_kb_search",
    description=(
        "Semantic search over the company vector knowledge base. "
        "Returns the most relevant internal documents by embedding similarity."
    ),
    category="internal",
)
def vector_kb_search(query: str, top_k: int = 5) -> str:
    """Search the internal vector knowledge base by semantic similarity.

    Args:
        query: Natural language query for semantic search.
        top_k: Number of most similar documents to return (default 5).

    Returns:
        Relevant internal documents formatted as a string with source metadata.
    """
    try:
        import chromadb
    except ImportError:
        return "vector_kb_search unavailable: install chromadb with `pip install chromadb`."

    collection_path = os.environ.get("CHROMA_DB_PATH", "")
    collection_name = os.environ.get("CHROMA_COLLECTION", "knowledge_base")
    if not collection_path:
        return "vector_kb_search unavailable: CHROMA_DB_PATH not set."

    try:
        client = chromadb.PersistentClient(path=collection_path)
        collection = client.get_collection(collection_name)
        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, 20),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        return f"vector_kb_search error: {exc}"

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        return f"No relevant internal documents found for: {query}"

    lines = [f"Vector KB results for: {query}", ""]
    for idx, (doc, meta) in enumerate(zip(documents, metadatas), 1):
        title = meta.get("title", f"Document {idx}")
        source = meta.get("source", "Internal")
        date = meta.get("date", "")
        date_str = f" [{date}]" if date else ""
        lines.append(f"{idx}. [Internal KB]{date_str} {title}")
        lines.append(f"   Source: {source}")
        lines.append(f"   Content: {doc[:500]}")
        lines.append("")

    return "\n".join(lines)
```

---

## 7. Tool Timeout and Error Handling

### Why this matters

A tool that hangs or raises an uncaught exception will cause the AG2 group chat to
receive an error message. The pipeline will attempt to recover, but a well-behaved
tool should never raise — it should return a descriptive error string so the
researcher LLM can decide whether to retry or continue with other sources.

### Timeout wrapper

```python
import os
import signal
import threading
from functools import wraps
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def with_timeout(seconds: int, error_message: str = "Tool call timed out"):
    """Decorator that cancels a tool function call if it exceeds `seconds`."""
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            result_container = [None]
            exception_container = [None]

            def target():
                try:
                    result_container[0] = fn(*args, **kwargs)
                except Exception as exc:
                    exception_container[0] = exc

            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            thread.join(timeout=seconds)

            if thread.is_alive():
                return f"{error_message} (limit: {seconds}s)"
            if exception_container[0] is not None:
                return f"Tool error: {exception_container[0]}"
            return result_container[0]

        return wrapper  # type: ignore[return-value]
    return decorator
```

### Retry wrapper

```python
import time
from functools import wraps
from typing import Tuple, Type


def with_retry(
    max_attempts: int = 3,
    delay_seconds: float = 2.0,
    backoff: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator that retries a function on failure with exponential back-off."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_error = None
            wait = delay_seconds
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_error = exc
                    if attempt < max_attempts:
                        time.sleep(wait)
                        wait *= backoff
            return f"Tool failed after {max_attempts} attempts: {last_error}"
        return wrapper
    return decorator
```

### Applying both wrappers to a tool

```python
import os
import requests
from cmbagent.external_tools import register_tool


@register_tool(
    name="brave_search_resilient",
    description="Brave Search with timeout and retry.",
    category="premium_search",
)
@with_timeout(seconds=20, error_message="brave_search timed out")
@with_retry(max_attempts=3, delay_seconds=1.5, backoff=2.0)
def brave_search_resilient(query: str, num_results: int = 10) -> str:
    """Brave Search with automatic retry and 20-second timeout.

    Args:
        query: Search query string.
        num_results: Number of results (default 10).

    Returns:
        Formatted search results or an error message.
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not api_key:
        return "brave_search_resilient unavailable: BRAVE_SEARCH_API_KEY not set."

    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        params={"q": query, "count": min(num_results, 20), "freshness": "pw"},
        timeout=15,
    )
    response.raise_for_status()
    items = response.json().get("web", {}).get("results", [])

    lines = [f"Brave Search: {query}", ""]
    for idx, item in enumerate(items[:num_results], 1):
        lines.append(f"{idx}. {item.get('title', 'Untitled')}")
        lines.append(f"   URL: {item.get('url', '')}")
        lines.append(f"   Snippet: {item.get('description', '')[:300]}")
        lines.append("")
    return "\n".join(lines) or "No results."
```

### Safe error return pattern (no decorator)

For simpler cases, wrap the body in a try/except and always return a string:

```python
@register_tool(name="safe_api_tool", description="Example safe tool pattern.")
def safe_api_tool(query: str) -> str:
    """Always returns a string — never raises."""
    try:
        # ... your logic here ...
        return "result"
    except KeyboardInterrupt:
        raise  # Always re-raise keyboard interrupt
    except Exception as exc:
        # Return a descriptive failure string so the LLM can handle it
        return f"safe_api_tool failed for '{query}': {type(exc).__name__}: {exc}"
```

---

## 8. Environment Variable Config for Tools

### Where keys live

All secrets are stored in `backend/.env`. The backend reads this file at startup via
`python-dotenv` (called from `backend/run.py`). The variables are then available via
`os.environ.get()` in any tool function.

### Recommended `.env` section for custom tools

Add this block to `backend/.env` below the existing provider sections:

```bash
# ═════════════════════════════════════════════════════════════════════════════
# CUSTOM TOOL API KEYS
#
# Keys for premium search APIs and internal integrations.
# Unused entries are silently ignored — the tool checks for its key and
# returns an informative message if it is not set.
# ═════════════════════════════════════════════════════════════════════════════

# ─── Brave Search ────────────────────────────────────────────────────────────
# Get a free or paid API key at https://brave.com/search/api/
BRAVE_SEARCH_API_KEY=

# ─── Serper.dev (Google Search / News) ───────────────────────────────────────
# Plans start at $50/month for 50k searches. https://serper.dev/
SERPER_API_KEY=

# ─── Exa.ai (semantic search) ────────────────────────────────────────────────
# https://exa.ai — includes a generous free tier for research.
EXA_API_KEY=

# ─── Internal knowledge base / REST API ──────────────────────────────────────
# Base URL of your internal API (no trailing slash).
INTERNAL_KB_BASE_URL=
INTERNAL_KB_API_KEY=

# Base URL and key for general internal REST APIs used by custom tools.
INTERNAL_API_BASE_URL=
INTERNAL_API_KEY=

# ─── Vector database (Chroma) ────────────────────────────────────────────────
# Absolute path to the persistent Chroma DB directory.
CHROMA_DB_PATH=
CHROMA_COLLECTION=knowledge_base
```

### Reading keys safely in a tool function

```python
import os

def my_tool(query: str) -> str:
    api_key = os.environ.get("MY_API_KEY", "").strip()
    if not api_key:
        # Return an informative message instead of raising — the LLM
        # will log this and continue with other available tools.
        return (
            "my_tool is not configured: set MY_API_KEY in backend/.env "
            "and restart the server."
        )
    # ... use api_key safely ...
```

### Verifying tool registration at startup

Add this log call to `backend/custom_tools.py` to confirm all tools registered:

```python
from cmbagent.external_tools import list_user_tools
import logging

_log = logging.getLogger(__name__)

def _log_registered_tools() -> None:
    tools = list_user_tools()
    _log.info(
        "custom_tools_registered",
        count=len(tools),
        names=[t["name"] for t in tools],
    )

# Call at module-level so it runs on import
_log_registered_tools()
```

---

## 9. End-to-End Example: Replacing DDGS with Brave Search

This section walks through the complete process of swapping the default DuckDuckGo
search for Brave Search across the entire Stage 2 pipeline.

### Step 1 — Get the API key

Sign up at https://brave.com/search/api/ and obtain a Subscription Token. The free
tier provides 2,000 queries/month. Paid plans start at $3/1000 queries.

### Step 2 — Add the key to `.env`

Open `backend/.env` and set:

```bash
BRAVE_SEARCH_API_KEY=BSAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Step 3 — Create `backend/custom_tools.py`

```python
# backend/custom_tools.py

"""Register custom tools with the cmbagent global registry.

This module is imported by main.py at startup. Adding or removing a tool
here takes effect after a server restart — no other files need to change.
"""

import os
import logging
import requests
from cmbagent.external_tools import register_tool, list_user_tools

_log = logging.getLogger(__name__)


@register_tool(
    name="brave_search",
    description=(
        "Search the web using Brave Search API. Provides high-quality, "
        "up-to-date web and news results filtered to the past week. "
        "Use this as the primary web search tool for all research tasks."
    ),
    category="premium_search",
)
def brave_search(query: str, num_results: int = 10) -> str:
    """Search the web via Brave Search API.

    Args:
        query: The search query string. Supports standard search operators
               such as site:, intitle:, and OR.
        num_results: Number of results to return (1–20, default 10).

    Returns:
        Formatted string of search results: title, URL, snippet, and age.
        Returns an error message string on failure — never raises.
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return (
            "brave_search unavailable: set BRAVE_SEARCH_API_KEY in backend/.env "
            "and restart the server. Falling back to duckduckgo_search."
        )

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            params={
                "q": query,
                "count": min(num_results, 20),
                "freshness": "pw",        # Past week
                "text_decorations": False,
                "search_lang": "en",
                "country": "us",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return f"brave_search timed out for: {query}"
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        return f"brave_search HTTP {status} error for: {query}"
    except requests.RequestException as exc:
        return f"brave_search network error: {exc}"

    # Merge news + web results, news first for temporal relevance
    news = data.get("news", {}).get("results", [])
    web = data.get("web", {}).get("results", [])
    all_results = news + web

    if not all_results:
        return f"No Brave Search results for: {query}"

    lines = [f"Brave Search results for: {query}", ""]
    for idx, item in enumerate(all_results[:num_results], 1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        snippet = item.get("description", "")
        age = item.get("age", "")
        age_str = f" ({age})" if age else ""
        lines.append(f"{idx}. {title}{age_str}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet[:350]}")
        lines.append("")

    return "\n".join(lines)


# ── Log what was registered ──────────────────────────────────────────────────

def _log_custom_tools() -> None:
    tools = list_user_tools()
    names = [t["name"] for t in tools]
    _log.info("custom_tools_registered", count=len(tools), tools=names)


_log_custom_tools()
```

### Step 4 — Import from `main.py`

Open `backend/main.py` and add the import near the top, before the FastAPI `app`
object is created:

```python
# backend/main.py

from fastapi import FastAPI
# ... other existing imports ...

import custom_tools  # noqa: F401 — registers brave_search into the global registry

# ... rest of main.py unchanged ...
```

### Step 5 — Restart the server

```bash
cd /Innovation/home/sachin_mourya/Desktop/MARS_APP/MARS_NewsLetter/backend
python run.py
```

You should see a log line similar to:

```
INFO  custom_tools_registered  count=1  tools=['brave_search']
```

### Step 6 — Verify in a newsletter run

Start a new newsletter task from the UI or API. In the Stage 2 console log
(available at `GET /api/newsletter/{task_id}/stages/2/console`), you will see tool
calls like:

```
>>>> EXECUTING FUNCTION brave_search
Query: "AI agents enterprise 2026"
...
```

If you see `duckduckgo_search` being called instead, confirm that:

1. The server was restarted after `backend/main.py` was modified.
2. `BRAVE_SEARCH_API_KEY` is non-empty in `backend/.env`.
3. The `brave_search` tool returned a result string (not an error) on the first call.

Because both `brave_search` and `duckduckgo_search` are registered, the researcher
agent may call either. To make Brave Search the exclusive tool, unregister DDGS by
adding to `custom_tools.py`:

```python
from cmbagent.external_tools import get_global_registry

# Remove the built-in DDGS tool so the researcher exclusively uses Brave Search.
# This must run after the cmbagent startup routine has populated the registry.
def _deregister_ddgs() -> None:
    registry = get_global_registry()
    if "duckduckgo_search" in registry._tools:
        del registry._tools["duckduckgo_search"]
        for cat_list in registry._tool_categories.values():
            if "duckduckgo_search" in cat_list:
                cat_list.remove("duckduckgo_search")
        _log.info("deregistered_duckduckgo_search")

# Note: call _deregister_ddgs() only AFTER cmbagent has initialised its
# built-in tools. Wire it into the FastAPI lifespan startup hook in core/app.py
# if ordering is critical. For most deployments, importing custom_tools after
# cmbagent is initialized is sufficient.
```

### Step 7 — Roll back if needed

To revert to DDGS, remove `import custom_tools` from `backend/main.py` and restart.
No other files were modified.

---

## Summary of Integration Points

| What you want to do | Where to make the change |
|---------------------|--------------------------|
| Register a new tool | Add `@register_tool` decorated function to `backend/custom_tools.py` |
| Import at startup | Add `import custom_tools` to `backend/main.py` |
| Store API keys | Add entries to `backend/.env` |
| Wrap a LangChain tool | Use `convert_langchain_tool_to_ag2()` from `cmbagent.external_tools.tool_adapter` |
| Wrap a CrewAI tool | Use `convert_crewai_tool_to_ag2()` from `cmbagent.external_tools.tool_adapter` |
| Register an MCP server | Call `register_mcp_server(name, url)` from `cmbagent.external_tools` |
| Load tools from YAML | Call `load_tools_from_config("tools.yaml")` from `cmbagent.external_tools` |
| Inspect registered tools | Call `list_user_tools()` from `cmbagent.external_tools` |
| Change tool timeout | Use `@with_timeout(seconds=N)` decorator shown in Section 7 |

---

## Appendix: YAML Config-File Tool Registration

For environments where source-code changes are not desirable (operator-only config),
tools can be declared in a YAML file and loaded at startup:

```yaml
# backend/custom_tools.yaml

tools:
  - name: google_search
    description: "Google Search via Serper.dev"
    module: "tools.serper_search"
    function: "google_search"
    category: premium_search

  - name: brave_search
    description: "Brave Search API"
    module: "tools.brave_search"
    function: "brave_search"
    category: premium_search

  - name: company_kb
    type: mcp
    url: "http://localhost:3000"
    category: internal
```

Load from `backend/main.py`:

```python
from cmbagent.external_tools import load_tools_from_config

load_tools_from_config(
    os.path.join(os.path.dirname(__file__), "custom_tools.yaml")
)
```

The YAML format supports `type: function` (imports a Python module/function by
dotted path) and `type: mcp` (connects to a running MCP JSON-RPC server and
auto-discovers all tools via the `tools/list` endpoint).
