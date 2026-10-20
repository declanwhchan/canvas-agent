import asyncio
import json
import os
import re
from urllib.parse import urljoin, urlsplit
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path
from threading import RLock, local
from time import monotonic

from bs4 import BeautifulSoup
from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.module import Module
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pypdf import PdfReader
from requests import Session

load_dotenv(Path(__file__).with_name(".env"))

BASE = os.environ["CANVAS_URL"].rstrip("/")
mcp = FastMCP("Canvas Agent")
_origin = urlsplit(BASE)
_clients = local()
_tool_slots = asyncio.Semaphore(4)
_courses_lock = RLock()
_courses_cache = ()
_courses_expires = 0.0


class _ReadOnlySession(Session):
    def request(self, method, url, **kwargs):
        if method.upper() not in ("GET", "HEAD"):
            raise ValueError("Canvas access is read-only.")
        kwargs.setdefault("timeout", (5, 30))
        return super().request(method, url, **kwargs)


def _client():
    # Requests sessions are reused per worker, never shared between threads.
    if not hasattr(_clients, "canvas"):
        client = Canvas(BASE, os.environ["CANVAS_TOKEN"])
        requester = client._Canvas__requester
        requester._session.close()
        requester._session = _ReadOnlySession()
        _clients.canvas = client
    return _clients.canvas


def _requester():
    # canvasapi has no public lazy course/requester accessor.
    return _client()._Canvas__requester


def _course(course_id):
    # The resource GET enforces permissions; fetching its parent first is redundant.
    return Course(_requester(), {"id": course_id})


def tool(fn):
    @wraps(fn)
    async def run(**kwargs):
        async with _tool_slots:
            result = await asyncio.to_thread(fn, **kwargs)
        # FastMCP otherwise pretty-prints JSON and duplicates structured results.
        return CallToolResult(content=[TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        )])

    mcp.tool(structured_output=False, annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
    ))(run)
    return fn

# Session-only LRU: retain parsed readers and text, never write documents to disk.
# Bound retained PDF bytes + UTF-8 text; reader overhead is also bounded by count.
PDF_MAX_BYTES = 30_000_000
PDF_CACHE_BYTES = 64_000_000
PDF_TEXT_LIMIT = 8000
_pdf_cache = OrderedDict()
_pdf_lock = RLock()
# Serialize the same document without blocking unrelated PDF downloads/extraction.
_pdf_locks = tuple(RLock() for _ in range(32))


def _trim_pdf_cache():
    while _pdf_cache and (
        len(_pdf_cache) > 8
        or sum(entry["size"] for entry in _pdf_cache.values()) > PDF_CACHE_BYTES
    ):
        _pdf_cache.popitem(last=False)


def pick(obj, *fields):
    get = obj.get if isinstance(obj, dict) else lambda name: getattr(obj, name, None)
    return {field: value for field in fields if (value := get(field)) is not None}


def _matches(text, query):
    text = re.sub(r"[\W_]+", "", text.casefold())
    return all(re.sub(r"[\W_]+", "", word.casefold()) in text for word in query.split())


@tool
def current_time() -> str:
    """Get the current date, time and local UTC offset."""
    return datetime.now().astimezone().isoformat()


@tool
def list_courses(search: str = "", refresh: bool = False) -> list:
    """Find active courses/terms; search by code/title/term. Cached 900s; refresh=true bypasses cache."""
    global _courses_cache, _courses_expires
    with _courses_lock:
        if refresh or monotonic() >= _courses_expires:
            # Never retain a successful discovery after an explicit refresh fails.
            _courses_cache, _courses_expires = (), 0.0
            _courses_cache = _load_courses()
            _courses_expires = monotonic() + 900
        return [row for row in _courses_cache if not search or _matches(
            " ".join(str(row.get(field, "")) for field in ("name", "course_code", "term")), search,
        )]


def _load_courses():
    rows = []
    for course in _client().get_courses(enrollment_state="active", include=["term"]):
        row = pick(course, "id", "name", "course_code", "start_at", "end_at")
        if getattr(course, "term", None):
            row["term"] = pick(course.term, "id", "name", "start_at", "end_at")
        row["source"] = f"{BASE}/courses/{course.id}"
        rows.append(row)
    return rows


@tool
def assignments_and_marks(course_id: int, search: str = "", details: bool = False) -> list:
    """Find assignments, dates and marks. Optional title search; read_assignment for full instructions. Missing fields are unknown."""
    params = {"include": ["submission"]}
    if search:
        params["search_term"] = search
    return [_assignment_details(a, course_id, details)
            for a in _course(course_id).get_assignments(**params)]


def _assignment_details(assignment, course_id, details=True):
    row = pick(
        assignment, "id", "name", "due_at", "points_possible", "html_url",
        "has_overrides", "assignment_group_id",
        "omit_from_final_grade", "published", "grading_type",
        "locked_for_user", "lock_explanation",
    )
    row.setdefault("html_url", f"{BASE}/courses/{course_id}/assignments/{assignment.id}")
    submission = getattr(assignment, "submission", None)
    if submission is not None:
        row["submission"] = pick(
            submission, "score", "grade", "entered_score", "entered_grade", "attempt",
            "submitted_at", "graded_at", "workflow_state", "late", "missing", "excused",
            "late_policy_status", "points_deducted", "seconds_late", "cached_due_date",
        )
    if not details:
        return row
    row.update(pick(assignment, "submission_types", "allowed_extensions", "unlock_at",
                    "lock_at", "rubric", "rubric_settings"))
    description = document(
        getattr(assignment, "description", ""),
        row["html_url"],
    )
    row["description"] = description.pop("text")
    row.update(description)
    return row


@tool
def read_assignment(course_id: int, assignment_id: int) -> dict:
    """Read discovered assignment instructions, links, rubric and rules; follow relevant linked PDFs separately."""
    assignment = _course(course_id).get_assignment(
        assignment_id, include=["submission"]
    )
    return _assignment_details(assignment, course_id)


@tool
def read_canvas_url(
    url: str, start_page: int = 1, page_count: int = 1, text_offset: int = 0,
) -> dict:
    """Optional shortcut for a discovered Canvas assignment/page/syllabus/PDF URL; PDF pagination matches read_pdf."""
    try:
        target = urlsplit(url)
    except ValueError:
        return {"error": "Invalid Canvas URL."}
    origin = _origin
    if (target.scheme not in ("http", "https")
            or target.scheme != origin.scheme or target.netloc != origin.netloc
            or target.username is not None or target.password is not None):
        return {"error": "URL must belong to the configured Canvas origin."}
    match = re.fullmatch(r"/(?:api/v1/)?courses/(\d+)/(.*?)/?", target.path)
    if not match:
        return {"error": "Use a course-scoped Canvas assignment, page or file URL."}
    course_id, resource = int(match[1]), match[2]
    if resource == "assignments/syllabus":
        return syllabus(course_id)
    assignment = re.fullmatch(r"assignments/(\d+)", resource)
    if assignment:
        return read_assignment(course_id, int(assignment[1]))
    if resource in ("front_page", "pages/front_page"):
        return read_front_page(course_id)
    page = re.fullmatch(r"pages/([^/]+)", resource)
    if page:
        return read_page(course_id, page[1])
    file = re.fullmatch(r"files/(\d+)(?:/(?:download|preview))?", resource)
    if file:
        return read_pdf(course_id, int(file[1]), start_page, page_count, text_offset)
    return {"error": "Unsupported Canvas URL. Use an assignment, page, syllabus, front page or PDF URL."}


@tool
def course_grade(course_id: int) -> list:
    """Read my Canvas-reported grades; absent/null means unavailable."""
    course = _course(course_id)
    return [
        dict(pick(e, "type", "enrollment_state", "grades"),
             source=f"{BASE}/courses/{course_id}/grades")
        for e in course.get_enrollments(user_id="self")
    ]


@tool
def syllabus(course_id: int) -> dict:
    """Read the Canvas syllabus. It may link to a separate PDF."""
    course = _client().get_course(course_id, include=["syllabus_body"])
    body = getattr(course, "syllabus_body", "") or ""
    return {
        "course": getattr(course, "name", str(course_id)),
        **document(body, f"{BASE}/courses/{course_id}/assignments/syllabus"),
    }



@tool
def list_pages(course_id: int, search: str = "") -> list:
    """Find course pages; optional title search."""
    return [
        pick(p, "title", "url", "html_url")
        for p in _course(course_id).get_pages()
        if not search or _matches(getattr(p, "title", ""), search)
    ]


@tool
def read_page(course_id: int, page_url: str) -> dict:
    """Read a page using its URL slug returned by list_pages."""
    page = _course(course_id).get_page(page_url)
    return {
        "title": getattr(page, "title", ""),
        **document(getattr(page, "body", ""), getattr(page, "html_url", None)
                   or f"{BASE}/courses/{course_id}/pages/{page_url}"),
    }


@tool
def list_files(course_id: int, search: str = "") -> list:
    """Find accessible files; optional filename search. If denied, use discovered module/page file IDs."""
    params = {"search_term": search} if search else {}
    return [
        dict(pick(f, "id", "display_name", "size"),
             source=f"{BASE}/courses/{course_id}/files/{f.id}")
        for f in _course(course_id).get_files(**params)
    ]


def _discard_pdf(key):
    with _pdf_lock:
        _pdf_cache.pop(key, None)


def _download_pdf(file):
    # Avoid canvasapi's eager binary pformat/logging and retained HTTP responses.
    # Signed storage URLs need no Canvas token; never send it to another origin.
    requester = file._requester
    target = urlsplit(file.url)
    headers = {}
    if (target.scheme, target.netloc) == (_origin.scheme, _origin.netloc):
        headers["Authorization"] = f"Bearer {requester.access_token}"
    with requester._session.get(file.url, headers=headers, stream=True) as response:
        response.raise_for_status()
        if int(response.headers.get("Content-Length", 0)) > PDF_MAX_BYTES:
            raise ValueError("PDF exceeds the 30 MB limit.")
        with BytesIO() as data:
            for chunk in response.iter_content(chunk_size=65536):
                if data.tell() + len(chunk) > PDF_MAX_BYTES:
                    raise ValueError("PDF exceeds the 30 MB limit.")
                data.write(chunk)
            return data.getvalue()


@contextmanager
def _pdf_document(course_id, file_id):
    key = (course_id, file_id)
    meta = {"source": f"{BASE}/courses/{course_id}/files/{file_id}"}
    with _pdf_locks[hash(key) % len(_pdf_locks)]:
        # Never use cached content before rechecking current authorized metadata.
        try:
            file = _course(course_id).get_file(file_id)
        except Exception:
            _discard_pdf(key)
            raise
        meta["filename"] = getattr(file, "display_name", str(file_id))
        meta["access"] = pick(file, "hidden_for_user", "locked_for_user", "unlock_at",
                              "lock_at", "lock_explanation")
        # Hidden files can be available through assignment/module links. Canvas's
        # authenticated download still enforces access; hiding alone is no lock.
        error = None
        if getattr(file, "locked_for_user", False):
            error = "Canvas reports this file is locked for the current user."
        elif not getattr(file, "url", None):
            error = "Canvas did not provide an authorized download URL for this file."
        elif (getattr(file, "size", 0) or 0) > PDF_MAX_BYTES:
            error = "PDF exceeds the 30 MB limit."
        if error:
            _discard_pdf(key)
            yield {"error": error}, meta
            return
        version = (getattr(file, "updated_at", None),
                   getattr(file, "modified_at", None), getattr(file, "size", None),
                   getattr(file, "md5", None))
        # Without a modification marker, freshness cannot be established.
        cacheable = bool(version[0] or version[1])
        with _pdf_lock:
            entry = _pdf_cache.pop(key, None)
        if not cacheable or entry is None or entry["version"] != version:
            raw = _download_pdf(file)
            reader = PdfReader(BytesIO(raw))
            entry = {"version": version, "reader": reader, "total": len(reader.pages),
                     "texts": {}, "size": len(raw)}
            del raw
        try:
            yield entry, meta
        finally:
            with _pdf_lock:
                if cacheable:
                    _pdf_cache[key] = entry
                _trim_pdf_cache()


def _page_text(entry, number):
    if number not in entry["texts"]:
        text = entry["reader"].pages[number - 1].extract_text() or ""
        entry["texts"][number] = text
        entry["size"] += len(text.encode("utf-8"))
    return entry["texts"][number]


@tool
def read_pdf(
    course_id: int, file_id: int, start_page: int = 1,
    page_count: int = 1, text_offset: int = 0,
) -> dict:
    """Read PDF pages in memory (1-based; page_count 1-5). Follow next_page; truncated text: same page, page_count=1, text_offset=next_offset. Report needs_ocr. Cite source/page. Use search_pdf to locate text."""
    if start_page < 1 or not 1 <= page_count <= 5 or text_offset < 0:
        return {"error": "start_page must be positive; page_count 1-5; text_offset nonnegative."}
    if text_offset and page_count != 1:
        return {"error": "Use page_count=1 when continuing text within a page."}

    with _pdf_document(course_id, file_id) as (entry, meta):
        if "error" in entry:
            return {**meta, **entry}
        total = entry["total"]
        if not 1 <= start_page <= total:
            return {**meta, "error": "Invalid page number.", "total_pages": total}
        end = min(start_page + page_count - 1, total)
        pages = []
        for number in range(start_page, end + 1):
            text = _page_text(entry, number)
            if text_offset and text_offset >= len(text):
                return {**meta, "error": "text_offset is beyond the page text.",
                        "page": number, "characters_total": len(text)}
            stop = text_offset + PDF_TEXT_LIMIT
            row = {"page": number, "text": text[text_offset:stop]}
            if stop < len(text):
                row.update(truncated=True, next_offset=stop, characters_total=len(text))
            if text_offset:
                row["text_offset"] = text_offset
            if not text.strip():
                row["needs_ocr"] = True
            pages.append(row)
        return {**meta, "total_pages": total, "pages": pages,
                "next_page": end + 1 if end < total else None}


@tool
def search_pdf(
    course_id: int, file_id: int, query: str, start_page: int = 1,
    page_count: int = 20, max_results: int = 5,
) -> dict:
    """Find text in PDF pages (max 50/call); first matching snippet per page. Follow next_page; read_pdf for context. Report needs_ocr_pages. Uses shared cache and current access checks."""
    query = query.strip()
    if (not 1 <= len(query) <= 200 or start_page < 1
            or not 1 <= page_count <= 50 or not 1 <= max_results <= 10):
        return {"error": "query must be 1-200 characters; start_page positive; page_count 1-50; max_results 1-10."}
    pattern = re.compile(r"\s+".join(re.escape(word) for word in query.split()), re.IGNORECASE)
    with _pdf_document(course_id, file_id) as (entry, meta):
        if "error" in entry:
            return {**meta, **entry}
        total = entry["total"]
        if start_page > total:
            return {**meta, "error": "Invalid page number.", "total_pages": total}
        end = min(start_page + page_count - 1, total)
        matches, ocr = [], []
        for number in range(start_page, end + 1):
            text = _page_text(entry, number)
            if not text.strip():
                ocr.append(number)
            match = pattern.search(text)
            if match:
                offset = max(0, match.start() - 160)
                matches.append({"page": number, "snippet": text[offset:min(match.end() + 160, offset + 520)],
                                "text_offset": offset})
                if len(matches) >= max_results:
                    break
        result = {**meta, "total_pages": total, "matches": matches,
                  "scanned_pages": {"first": start_page, "last": number},
                  "next_page": number + 1 if number < total else None}
        if ocr:
            result["needs_ocr_pages"] = ocr
        return result



def document(body, source):
    """Extract reference text and links without losing Canvas file IDs."""
    soup = BeautifulSoup(body or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(source, a["href"])
        if urlsplit(href).scheme not in ("http", "https"):
            continue
        row = {"text": a.get_text(" ", strip=True), "href": href}
        candidates = [href]
        if a.get("data-api-endpoint"):
            candidates.append(urljoin(source, a["data-api-endpoint"]))
        for candidate in candidates:
            target = urlsplit(candidate)
            if (target.scheme, target.netloc) == (_origin.scheme, _origin.netloc):
                match = re.search(r"/(?:courses/(\d+)/)?files/(\d+)(?:/|$)", target.path)
                if match:
                    row["file_id"] = int(match[2])
                    if match[1]:
                        row["course_id"] = int(match[1])
        identity = tuple(row.items())
        if identity not in seen:
            seen.add(identity)
            links.append(row)
    media = []
    for tag in soup.find_all(["img", "iframe", "embed", "object", "video", "audio", "source"]):
        value = tag.get("data") if tag.name == "object" else tag.get("src")
        if not value:
            continue
        href = urljoin(source, value)
        if urlsplit(href).scheme in ("http", "https"):
            media.append({"type": tag.name, "href": href,
                          "text": tag.get("alt") or tag.get("title") or ""})
    result = {"text": soup.get_text(" ", strip=True), "source": source}
    if links:
        result["links"] = links
    if media:
        result["media"] = media
    return result


@tool
def read_front_page(course_id: int) -> dict:
    """Read the course front page with hyperlinks and Canvas file IDs."""
    # This installed canvasapi version has no front-page GET wrapper.
    page = _requester().request("GET", f"courses/{course_id}/front_page").json()
    return {"title": page.get("title", ""),
            **document(page.get("body", ""), page.get("html_url")
                       or f"{BASE}/courses/{course_id}/front_page")}


@tool
def list_modules(course_id: int, search: str = "", include_items: bool = False) -> list:
    """Find modules; optional title search. include_items=true previews items in one request; items_complete=false needs list_module_items."""
    params = {"include": ["items"]} if include_items else {}
    result = []
    for module in _course(course_id).get_modules(**params):
        if search and not _matches(getattr(module, "name", ""), search):
            continue
        row = dict(pick(module, "id", "name", "position", "items_count"),
                   source=f"{BASE}/courses/{course_id}/modules/{module.id}")
        if include_items:
            row["items"] = [_module_item_details(item, course_id)
                            for item in (getattr(module, "items", None) or [])]
            count = getattr(module, "items_count", None)
            row["items_complete"] = isinstance(count, int) and len(row["items"]) >= count
        result.append(row)
    return result


def _module_item_details(item, course_id):
    row = pick(item, "id", "title", "type", "content_id", "page_url", "html_url", "external_url")
    row["source"] = row.get("html_url") or f"{BASE}/courses/{course_id}/modules/items/{row['id']}"
    if row.get("type") == "File" and row.get("content_id") is not None:
        row["file_id"] = row["content_id"]
        row["file_source"] = f"{BASE}/courses/{course_id}/files/{row['content_id']}"
    return row


@tool
def list_module_items(course_id: int, module_id: int) -> list:
    """Find files and pages even when the course Files listing is denied."""
    module = Module(_requester(), {"id": module_id, "course_id": course_id})
    return [_module_item_details(item, course_id) for item in module.get_module_items()]


@tool
def assignment_groups(course_id: int) -> dict:
    """Read group weights, drop rules and compact assignment marks; absent/null is unknown."""
    course = _client().get_course(course_id)
    groups = [pick(g, "id", "name", "group_weight", "rules")
              for g in course.get_assignment_groups()]
    by_group = {}
    for assignment in assignments_and_marks(course_id):
        by_group.setdefault(assignment.get("assignment_group_id"), []).append(assignment)
    for group in groups:
        group["assignments"] = by_group.get(group["id"], [])
    return {"course_id": course_id,
            "apply_assignment_group_weights": getattr(course, "apply_assignment_group_weights", None),
            "groups": groups, "source": f"{BASE}/courses/{course_id}/grades"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
