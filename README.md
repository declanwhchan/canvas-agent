# Canvas Agent

> Connect with your Canvas account once. Then, ask about upcoming deadlines, find course materials and PDFs, or get a breakdown of your grades. Responses always use course-provided information and generates a Canvas link to open the page directly.

## 1. Installation

```
git clone https://github.com/declanwhchan/canvas-agent.git
cd canvas-agent
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install canvasapi beautifulsoup4 python-dotenv "mcp[cli]" pypdf
```

**macOS / Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install canvasapi beautifulsoup4 python-dotenv "mcp[cli]" pypdf
```

## 2. Create `.env`

```dotenv
# Use your school's Canvas base URL.
CANVAS_URL=https://your-school.instructure.com
# Then, go to settings and create a new API access token.
CANVAS_TOKEN=your-access-token
```

See the [Canvas token guide](https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account). **Keep `.env` private.**

## 3. Connect your agent

In your AI app or `mcp.json`, go to MCP settings and add a server named `canvas`:

| Setting | Windows | macOS / Linux |
|---|---|---|
| **Transport type** | `STDIO` | `STDIO` |
| **Command** | `C:/path/to/canvas-agent/.venv/Scripts/python.exe` | `/path/to/canvas-agent/.venv/bin/python` |
| **Arguments** | `C:/path/to/canvas-agent/canvas_server.py` | `/path/to/canvas-agent/canvas_server.py` |

Configuration formats vary by app; use its MCP instructions. Enable the server/tools and restart the MCP server after changing code or `.env`.

## Reading assignment and file links

Ask naturally, for example: "Give me everything I need to do for lab 3 in my
digital systems course." The agent resolves your course, finds the assignment,
and follows relevant linked instructions automatically. You do not need to paste
links, look up IDs, or name tools. It asks for clarification only if multiple
courses or assignments remain plausible, and reports actual access failures.

`read_assignment` retrieves an assignment using IDs discovered from the course's
assignments or module items, including its description, linked documents, rubric,
submission settings, and references to embedded images or videos. `read_canvas_url`
is an optional shortcut for links the agent discovers or you choose to provide.
Embedded media are listed as references, not rendered or transcribed. The agent
reads relevant linked documents separately rather than fetching every attachment.

PDFs remain in memory and support page-by-page reading with `read_pdf` or
`read_canvas_url`. A file hidden from the Files list may still be available from an
assignment or module link. Hidden status alone does not block reading; an actual
user lock, an API access denial, or a download denial still does. Lock responses
include the available lock explanation and dates. No Canvas permissions are changed.

After updating this repo, **restart the Canvas MCP server and refresh its tools**
in your client so the new URL reader and file-access fix are loaded.

Offline regression checks (Windows):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s local -p "test_*.py"
```

## Done!

You can customize [AGENTS.md](AGENTS.md) and try to ask:

```prompts
What do I need on each of my remaining assessments to finish MATH101 with 85%?

List all my weighted assessments, expected work, required materials, and deadline for the next 14 days.
```
