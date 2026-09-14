# Canvas MCP server

> Connect your Canvas account once. Then, ask about upcoming deadlines, find course materials and PDFs, or get a clear breakdown of your grades—with exact wording from courses when you need it. **When it finds something, it can give you a direct Canvas link so you can open it immediately.**

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
CANVAS_URL=https://your-school.instructure.com
CANVAS_TOKEN=your-access-token
```

Use your school's Canvas base URL. Then, obtain an API token through your school's approved process. See the [Canvas token guide](https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account). Keep `.env` private: never upload it, commit it, or paste its contents into an AI chat.

## 3. Connect your agent

In your AI app, go to MCP settings and add a server named `canvas`:

- **Transport type:** `STDIO`
- **Command to launch:** path to `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS/Linux) e.g. `C:/path/to/canvas-agent/.venv/Scripts/python.exe`
- **Arguments:** path to `canvas_server.py` e.g. `C:/path/to/canvas-agent/canvas_server.py`


Configuration formats vary by app; use its MCP instructions. Enable the server/tools and restart the MCP server after changing code or `.env`.
