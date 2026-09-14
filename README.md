# Canvas Agent

> Connect with your Canvas account once. Then, ask about upcoming deadlines, find course materials and PDFs, or get a breakdown of your grades. **Responses always use course-provided information and generates a Canvas link to open the page directly.**

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

## Done!

You can customize [AGENTS.md](AGENTS.md) and try to ask:

```prompts
What do I need on each of my remaining assessments to finish MATH101 with 85%?

List every item worth > 15% of final grade, include details I need to watch out for, and the due date.

List all my assessments worth marks, expected work, required materials, and deadline for the next 7 days.
```
