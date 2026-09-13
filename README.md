# Canvas MCP server

> Connect your Canvas account once. Then, ask about upcoming deadlines, find course materials and PDFs, or get a clear breakdown of your grades—with exact wording from your courses when you need it. **When it finds something, it can give you a direct Canvas link so you can open it immediately.**

## 1. Install

Install Python 3.12, clone this project, and open a terminal in its folder.

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

## 2. Set up `.env`

```dotenv
CANVAS_URL=https://your-school.instructure.com
CANVAS_TOKEN=your-access-token
```

Use your school's Canvas base URL. Then, obtain an API token through your school's approved process. See the [Canvas token guide](https://community.instructure.com/en/kb/articles/662901-how-do-i-manage-api-access-tokens-in-my-user-account).

Keep `.env` private: never upload it, commit it, or paste its contents into an AI chat.

## 3. Connect your AI assistant

Your AI app must support **local MCP servers over stdio**. In its MCP settings, add a server named `canvas`:

- **Transport:** `stdio`
- **Command:** absolute path to this project's `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (macOS/Linux).
- **Arguments:** the absolute path to `canvas_server.py`, as one argument.

For clients that accept `mcpServers` JSON, use this example and replace both paths:

```json
{
  "mcpServers": {
    "canvas": {
      "command": "C:/path/to/canvas-agent/.venv/Scripts/python.exe",
      "args": ["C:/path/to/canvas-agent/canvas_server.py"]
    }
  }
}
```

Configuration formats vary by app; use its MCP instructions. Enable the server/tools. Restart the MCP server after changing its code or `.env`.
