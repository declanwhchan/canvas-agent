import os
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
    """List my active enrolled courses and their IDs."""
    return [
        pick(c, "id", "name", "course_code")
        for c in canvas.get_courses(enrollment_state="active")
    ]


@mcp.tool()
def assignments_and_marks(course_id: int) -> list:
    """Read assignments, due dates and my visible submission marks."""
    course = canvas.get_course(course_id)
    result = []
    for a in course.get_assignments(include=["submission"]):
        row = pick(
            a, "id", "name", "due_at", "points_possible",
            "html_url", "submission", "has_overrides"
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
    soup = BeautifulSoup(body, "html.parser")
    return {
        "course": getattr(course, "name", str(course_id)),
        "text": plain(body),
        "links": [
            {"text": a.get_text(" ", strip=True), "href": a["href"]}
            for a in soup.find_all("a", href=True)
        ],
        "source": f"{BASE}/courses/{course_id}/assignments/syllabus",
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
        "text": plain(getattr(page, "body", "")),
        "source": getattr(page, "html_url", ""),
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
            })

    return {
        "filename": getattr(file, "display_name", str(file_id)),
        "source": f"{BASE}/courses/{course_id}/files/{file_id}",
        "total_pages": total,
        "pages": pages,
        "next_page": end + 1 if end < total else None,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
