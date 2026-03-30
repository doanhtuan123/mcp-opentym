# 🛠️ mcp-opentym

A lightweight **Model Context Protocol (MCP) HTTP server** built with the official Python MCP SDK and Streamable HTTP transport. Designed to give AI assistants (Claude, Cursor, etc.) real tools to interact with your Windows machine.

---

## ✨ Features

| Tool | Description |
|------|-------------|
| `exec` | Run shell commands (cmd / PowerShell) |
| `read_file` | Read files with offset/limit pagination |
| `write_file` | Write or append to files |
| `list_files` | List directory contents |
| `open_app` | Open applications or URLs |
| `get_system_info` | CPU, RAM, disk, network info |
| `screenshot` | Capture the screen |
| `clipboard` | Read or write clipboard |
| `send_notification` | Windows toast notifications |
| `web_search` | Search the web via Brave API |
| `web_fetch` | Fetch and extract content from URLs |
| `http_request` | Generic HTTP client (GET/POST/etc.) |
| `get_datetime` | Current date & time |
| `calculate` | Safe math expression evaluator |
| `get_weather` | Weather by city name |
| `browser_action` | Full browser automation via Playwright |
| `memory_search` | Semantic search over memory files |
| `memory_get` | Read memory file snippets |
| `memory_write` | Append or write memory files |

---

## 🚀 Quick Start

### 1. Clone & setup

```bash
git clone https://github.com/doanhtuan123/mcp-server-python.git
cd mcp-server-python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Run the server

```bash
python server.py
```

Server starts at: `http://localhost:3458/mcp`  
Health check: `http://localhost:3458/health`

### 3. Public tunnel (optional)

Expose locally via Cloudflare Quick Tunnel:

```bash
python tunnel.py
```

The public URL is saved to `data/tunnel-url.txt`.

---

## ⚙️ Configuration

| Item | Default |
|------|---------|
| Port | `3458` |
| Transport | Streamable HTTP |
| Browser | Chrome (Playwright) |
| Shell | `cmd` / `powershell` |

To change the port, edit the `port=` value near the bottom of `server.py`.

---

## 📦 Dependencies

```
mcp[cli]>=1.0.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
playwright>=1.44.0
```

---

## 🔌 Connect to Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-opentym": {
      "url": "http://localhost:3458/mcp"
    }
  }
}
```

Or with the public tunnel URL:

```json
{
  "mcpServers": {
    "mcp-opentym": {
      "url": "https://<your-tunnel>.trycloudflare.com/mcp"
    }
  }
}
```

---

## 🗂️ Project Structure

```
mcp-server-python/
├── server.py          # Main MCP server
├── tunnel.py          # Cloudflare Quick Tunnel helper
├── requirements.txt   # Python dependencies
├── data/              # Runtime data (logs, tunnel URL)
└── workspace/         # Shared file workspace for tools
```

---

## 📄 License

MIT
