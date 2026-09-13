import os
import re
from urllib.parse import urljoin, urlsplit
import tempfile
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from canvasapi import Canvas
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pypdf import PdfReader

load_dotenv(Path(__file__).with_name(".env"))

BASE = os.environ["CANVAS_URL"].rstrip("/")
canvas = Canvas(BASE, os.environ["CANVAS_TOKEN"])
mcp = FastMCP("Canvas Agent")


def plain(html):
    return BeautifulSoup(html or "", "html.parser").get_text(
        " ", strip=True
    )


def pick(obj, *fields):
    return {field: getattr(obj, field, None) for field in fields}


@mcp.tool()
def current_time() -> str:
    """Get the current date, time and local UTC offset."""
    return datetime.now().astimezone().isoformat()


@mcp.tool()
def list_courses() -> list:
    """Resolve courses from the question; clarify multiple matching terms or sections."""
    return [
        pick(c, "id", "name", "course_code", "term", "start_at", "end_at")
        for c in canvas.get_courses(enrollment_state="active", include=["term"])
    ]


@mcp.tool()
def assignments_and_marks(course_id: int) -> list:
    """Read assignments, due dates and my visible submission marks."""
    course = canvas.get_course(course_id)
    result = []
    for a in course.get_assignments(include=["submission"]):
        row = pick(
            a, "id", "name", "due_at", "points_possible",
            "html_url", "submission", "has_overrides", "assignment_group_id",
            "omit_from_final_grade", "published", "grading_type"
        )
        row["description"] = plain(getattr(a, "description", ""))
        result.append(row)
    return result


@mcp.tool()
def course_grade(course_id: int) -> list:
    """Read my Canvas-reported course grades; null means unavailable."""
    course = canvas.get_course(course_id)
    return [
        pick(e, "type", "enrollment_state", "grades")
        for e in course.get_enrollments(user_id="self")
    ]


@mcp.tool()
def syllabus(course_id: int) -> dict:
    """Read the Canvas syllabus. It may link to a separate PDF."""
    course = canvas.get_course(course_id, include=["syllabus_body"])
    body = getattr(course, "syllabus_body", "") or ""
    return {
        "course": getattr(course, "name", str(course_id)),
        **document(body, f"{BASE}/courses/{course_id}/assignments/syllabus"),
    }



@mcp.tool()
def list_pages(course_id: int) -> list:
    """List course pages to locate policies and course information."""
    return [
        pick(p, "title", "url", "html_url")
        for p in canvas.get_course(course_id).get_pages()
    ]


@mcp.tool()
def read_page(course_id: int, page_url: str) -> dict:
    """Read a page using its URL slug returned by list_pages."""
    page = canvas.get_course(course_id).get_page(page_url)
    return {
        "title": getattr(page, "title", ""),
        **document(getattr(page, "body", ""), getattr(page, "html_url", None)
                   or f"{BASE}/courses/{course_id}/pages/{page_url}"),
    }


@mcp.tool()
def list_files(course_id: int) -> list:
    """List accessible course files, including PDF file IDs."""
    return [
        pick(f, "id", "display_name", "filename", "size")
        for f in canvas.get_course(course_id).get_files()
    ]


@mcp.tool()
def read_pdf(
    course_id: int, file_id: int, start_page: int = 1
) -> dict:
    """Read up to five PDF pages. Page numbers start at 1.
    Call again with the next start_page to continue reading.
    Accept discovered file IDs even when the Files listing is denied.
    """
    file = canvas.get_course(course_id).get_file(file_id)
    if getattr(file, "size", 0) > 30_000_000:
        return {"error": "PDF exceeds this starter tool's 30 MB limit."}

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "document.pdf"
        file.download(str(path))
        reader = PdfReader(str(path))
        total = len(reader.pages)

        if not 1 <= start_page <= total:
            return {"error": "Invalid page number.", "total_pages": total}

        end = min(start_page + 4, total)
        pages = []
        for number in range(start_page, end + 1):
            text = reader.pages[number - 1].extract_text() or ""
            pages.append({
                "page": number,
                "text": text[:16000],
                "truncated": len(text) > 16000,
                "characters_total": len(text),
                "needs_ocr": not bool(text.strip()),
                "status": "No extractable text; page may be scanned and need OCR."
                          if not text.strip() else "Text extracted",
            })

    return {
        "filename": getattr(file, "display_name", str(file_id)),
        "source": f"{BASE}/courses/{course_id}/files/{file_id}",
        "total_pages": total,
        "start_page": start_page,
        "end_page": end,
        "text_character_limit_per_page": 16000,
        "truncated": any(p["truncated"] for p in pages),
        "needs_ocr_pages": [p["page"] for p in pages if p["needs_ocr"]],
        "pages": pages,
        "next_page": end + 1 if end < total else None,
    }



def document(body, source):
    """Extract reference text and links without losing Canvas file IDs."""
    soup = BeautifulSoup(body or "", "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(source, a["href"])
        if urlsplit(href).scheme not in ("http", "https"):
            continue
        row = {"text": a.get_text(" ", strip=True), "href": href}
        for candidate in (href, urljoin(source, a.get("data-api-endpoint", ""))):
            if urlsplit(candidate).netloc == urlsplit(BASE).netloc:
                match = re.search(r"/(?:courses/(\d+)/)?files/(\d+)(?:/|$)", urlsplit(candidate).path)
                if match:
                    row["file_id"] = int(match[2])
                    if match[1]:
                        row["course_id"] = int(match[1])
        links.append(row)
    for tag in soup(["script", "style"]):
        tag.decompose()
    return {"text": soup.get_text(" ", strip=True), "links": links, "source": source}


@mcp.tool()
def read_front_page(course_id: int) -> dict:
    """Read the course front page with hyperlinks and Canvas file IDs."""
    course = canvas.get_course(course_id)
    # This installed canvasapi version has no front-page GET wrapper.
    page = course._requester.request("GET", f"courses/{course_id}/front_page").json()
    return {"title": page.get("title", ""),
            **document(page.get("body", ""), page.get("html_url")
                       or f"{BASE}/courses/{course_id}/front_page")}


@mcp.tool()
def list_modules(course_id: int) -> list:
    """Discover course modules dynamically, including introductory material."""
    return [dict(pick(m, "id", "name", "position", "items_count"),
                 source=f"{BASE}/courses/{course_id}/modules/{m.id}")
            for m in canvas.get_course(course_id).get_modules()]


@mcp.tool()
def list_module_items(course_id: int, module_id: int) -> list:
    """Find files and pages even when the course Files listing is denied."""
    module = canvas.get_course(course_id).get_module(module_id)
    result = []
    for item in module.get_module_items():
        row = pick(item, "id", "title", "type", "content_id", "page_url", "html_url", "external_url")
        row["source"] = row["html_url"] or f"{BASE}/courses/{course_id}/modules/items/{item.id}"
        if row["type"] == "File":
            row["file_id"] = row["content_id"]
            row["file_source"] = f"{BASE}/courses/{course_id}/files/{row['content_id']}"
        result.append(row)
    return result


@mcp.tool()
def assignment_groups(course_id: int) -> dict:
    """Read group weights, drop rules, assignments and my submissions; null is unknown."""
    course = canvas.get_course(course_id)
    groups = [pick(g, "id", "name", "group_weight", "rules")
              for g in course.get_assignment_groups()]
    assignments = assignments_and_marks(course_id)
    for group in groups:
        group["assignments"] = [a for a in assignments if a["assignment_group_id"] == group["id"]]
    return {"course_id": course_id,
            "apply_assignment_group_weights": getattr(course, "apply_assignment_group_weights", None),
            "groups": groups, "source": f"{BASE}/courses/{course_id}/grades"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
