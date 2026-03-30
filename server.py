"""
MCP HTTP Server — OpenClaw-compatible Tools
Python SDK (mcp[cli]) + Streamable HTTP transport
Port: 3456
"""

import asyncio
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

# ─── Playwright browser singleton ────────────────────────
_playwright = None
_browser    = None
_page       = None

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def get_browser():
    global _playwright, _browser, _page
    # Kiểm tra cả browser lẫn page còn sống
    try:
        if _browser and _browser.is_connected():
            # Ping thật sự bằng cách list contexts
            contexts = _browser.contexts
            # Validate _page còn dùng được
            if _page and not _page.is_closed():
                return _browser, _page
            # Page đã closed → tạo page mới trong context hiện có
            if contexts:
                _page = await contexts[0].new_page()
            else:
                _page = await _browser.new_page()
            return _browser, _page
    except Exception:
        pass

    # Reset sạch trước khi khởi động mới
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            await _playwright.stop()
    except Exception:
        pass
    _browser = None
    _page = None
    _playwright = None

    from playwright.async_api import async_playwright
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        executable_path=CHROME_PATH,
        headless=False,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--start-maximized"],
    )
    _page = await _browser.new_page()
    return _browser, _page

async def get_active_page():
    global _browser, _page
    # Delegate hoàn toàn về get_browser() để tránh logic lặp
    _, page = await get_browser()
    return page

# ─── Paths & helpers ─────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
WORKSPACE   = BASE_DIR / "workspace"   # lưu file mặc định tại mcp-server-py/workspace/
MEMORY_FILE = WORKSPACE / "MEMORY.md"
MEMORY_DIR  = WORKSPACE / "memory"

for d in [DATA_DIR, WORKSPACE, MEMORY_DIR]:
    d.mkdir(parents=True, exist_ok=True)

VN_TZ = timezone(timedelta(hours=7))

def today_key() -> str:
    return datetime.now(VN_TZ).strftime("%Y-%m-%d")

def daily_log() -> Path:
    return MEMORY_DIR / f"{today_key()}.md"

def safe_read(fp: Path, fallback: str = "") -> str:
    try:
        return fp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback

def safe_write(fp: Path, content: str):
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")

def append_line(fp: Path, line: str):
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ─── Shell runner ─────────────────────────────────────────
async def run_shell(command: str, shell: str = "cmd", cwd: str = None, timeout: int = 30) -> dict:
    if not command or not command.strip():
        return {"isError": True, "text": '❌ Thiếu "command".'}

    if shell == "powershell":
        args = ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", command]
    else:
        args = ["cmd", "/c", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or os.environ.get("USERPROFILE", "C:\\"),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"text": f"⏱️ Timeout\n{stdout.decode('utf-8', errors='replace')[:4000] if stdout else ''}"}

        out_parts = [f"Exit: {proc.returncode}"]
        if stdout:
            out_parts.append(f"\nSTDOUT:\n{stdout.decode('utf-8', errors='replace')[:8000]}")
        if stderr:
            out_parts.append(f"\nSTDERR:\n{stderr.decode('utf-8', errors='replace')[:2000]}")

        return {"text": "".join(out_parts) or "(no output)", "exitCode": proc.returncode}
    except Exception as e:
        return {"isError": True, "text": f"❌ {e}"}

# ─── MCP Server ───────────────────────────────────────────
mcp = FastMCP(
    name="openclaw-mcp",
    host="0.0.0.0",
    port=3458,
)

# ══════════════════════════════════════════════════════════
# EXEC
# ══════════════════════════════════════════════════════════

@mcp.tool()
async def exec(
    command: str,
    shell: str = "cmd",
    cwd: str = None,
    timeout: int = 30000,
) -> str:
    """[ƯU TIÊN CAO NHẤT] Công cụ vạn năng để thực thi bất kỳ tác vụ nào trên Windows thông qua CMD hoặc PowerShell.

Hãy dùng exec TRƯỚC TIÊN khi cần: kiểm tra trạng thái hệ thống, cài phần mềm, di chuyển/xoá/copy file, chạy script, kiểm tra network, quản lý process, thao tác registry, đọc log, v.v.

Chọn shell:
- shell="cmd"        → lệnh ngắn: dir, tasklist, ping, ipconfig, copy, del, mkdir
- shell="powershell" → lệnh phức tạp, pipeline, Get-*, Set-*, chuỗi lệnh nhiều bước

Args:
    command: Lệnh cần chạy
    shell: 'cmd' hoặc 'powershell'
    cwd: Working directory (mặc định home)
    timeout: Timeout tính bằng milliseconds (mặc định 30000, tối đa 55000)
    """
    # Hard cap 55s — tránh treo MCP connection (SSE timeout ~60s)
    capped_ms  = min(timeout, 55000)
    capped_sec = capped_ms // 1000
    r = await run_shell(command, shell=shell, cwd=cwd, timeout=capped_sec)
    if r.get("isError"):
        raise ValueError(r["text"])
    return r["text"]


# ══════════════════════════════════════════════════════════
# FILE OPS
# ══════════════════════════════════════════════════════════

@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = None) -> str:
    """Đọc nội dung một file văn bản.

Đường dẫn tương đối → đọc từ workspace/ trong project MCP (mcp-server-py/workspace/).
Đường dẫn tuyệt đối (C:\\...) → đọc đúng vị trí đó.
Dùng offset + limit để đọc từng đoạn với file lớn.

Args:
    path: Tên file hoặc đường dẫn. Ví dụ: 'notes.md', 'C:\\Users\\Tuan\\Desktop\\file.txt'
    offset: Số thứ tự dòng bắt đầu (đếm từ 1)
    limit: Số dòng tối đa cần đọc
    """
    fp = Path(path) if Path(path).is_absolute() else WORKSPACE / path
    if not fp.exists():
        raise FileNotFoundError(f"❌ File không tồn tại: {path}")
    content = fp.read_text(encoding="utf-8", errors="replace")
    if offset != 1 or limit is not None:
        lines = content.splitlines()
        start = max(0, offset - 1)
        end   = start + limit if limit else None
        content = "\n".join(lines[start:end])
    if len(content) > 20000:
        content = content[:20000] + "\n...[truncated]"
    return content


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Tạo mới hoặc ghi nội dung vào file.

Đường dẫn tương đối → tự động lưu vào thư mục workspace/ trong project MCP (mcp-server-py/workspace/).
Thư mục cha được tạo tự động nếu chưa tồn tại.
Đường dẫn tuyệt đối (C:\\...) → lưu đúng vị trí đó.

Args:
    path: Tên file hoặc đường dẫn. Ví dụ: 'notes.md', 'reports/result.json', 'C:\\Users\\Tuan\\Desktop\\out.txt'
    content: Nội dung cần ghi
    append: False (mặc định) = ghi đè | True = thêm vào cuối
    """
    fp = Path(path) if Path(path).is_absolute() else WORKSPACE / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with open(fp, "a", encoding="utf-8") as f:
            f.write("\n" + content)
        return f"✅ Đã append vào: {path}"
    else:
        fp.write_text(content, encoding="utf-8")
        return f"✅ Đã ghi: {path}"


@mcp.tool()
def list_files(path: str = ".", dirs_only: bool = False) -> str:
    """Liệt kê danh sách file và thư mục.

Đường dẫn tương đối → liệt kê trong workspace/ (mcp-server-py/workspace/).
Mặc định (path='.') → liệt kê toàn bộ workspace.

Args:
    path: Đường dẫn thư mục. Mặc định '.' = workspace root
    dirs_only: True = chỉ liệt kê thư mục con
    """
    fp = Path(path) if Path(path).is_absolute() else WORKSPACE / path
    if not fp.exists():
        raise FileNotFoundError(f"❌ Không tồn tại: {path}")
    items = []
    for item in sorted(fp.iterdir()):
        if dirs_only and not item.is_dir():
            continue
        items.append({
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
# SYSTEM
# ══════════════════════════════════════════════════════════

@mcp.tool()
async def open_app(target: str, args: str = "") -> str:
    """Mở ứng dụng, file, hoặc URL trên Windows.

Hỗ trợ tên rút gọn: chrome, firefox, notepad, vscode, explorer, calc, paint.
Cũng hỗ trợ đường dẫn đầy đủ .exe, file tài liệu, URL https://.

Args:
    target: App/file/URL cần mở
    args: Tham số dòng lệnh (optional)
    """
    APP_MAP = {
        "notepad": "notepad.exe", "chrome": "chrome", "firefox": "firefox",
        "vscode": "code", "explorer": "explorer.exe", "calc": "calc.exe", "paint": "mspaint.exe",
    }
    resolved = APP_MAP.get(target.lower(), target)
    is_url   = resolved.startswith(("http://", "https://", "ms-"))

    if is_url:
        ps_cmd = f'Start-Process "{resolved}"'
    elif args:
        ps_cmd = f'Start-Process "{resolved}" -ArgumentList "{args}"'
    else:
        ps_cmd = f'Start-Process "{resolved}"'

    full_cmd = f'try {{ {ps_cmd}; Write-Output "OK" }} catch {{ Write-Error $_.Exception.Message; exit 1 }}'
    r = await run_shell(full_cmd, shell="powershell", timeout=8)
    if r.get("isError") or (r.get("exitCode", 0) != 0):
        raise RuntimeError(f"❌ Không thể mở \"{target}\": {r['text']}")
    return f"✅ Đã mở: {target}"


@mcp.tool()
async def get_system_info(type: str = "all") -> str:
    """Lấy thông tin phần cứng và trạng thái hệ thống Windows.

Args:
    type: 'all' | 'cpu' | 'ram' | 'disk' | 'network' | 'processes'
    """
    async def wmic(cmd): return (await run_shell(cmd, timeout=10))["text"]

    result = {}

    if type in ("all", "cpu"):
        result["cpu"] = await wmic("wmic cpu get Name,NumberOfCores,CurrentClockSpeed /format:list")

    if type in ("all", "ram"):
        raw   = await wmic("wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /format:list")
        free  = int(re.search(r"FreePhysicalMemory=(\d+)",    raw).group(1)) // 1024 if re.search(r"FreePhysicalMemory=(\d+)", raw) else 0
        total = int(re.search(r"TotalVisibleMemorySize=(\d+)", raw).group(1)) // 1024 if re.search(r"TotalVisibleMemorySize=(\d+)", raw) else 1
        result["ram"] = {
            "total_mb": total, "free_mb": free,
            "used_mb": total - free,
            "used_pct": f"{round((total - free) / total * 100)}%",
        }

    if type in ("all", "disk"):
        result["disk"] = await wmic("wmic logicaldisk get DeviceID,FreeSpace,Size,VolumeName /format:list")

    if type in ("all", "network"):
        result["network"] = (await wmic("ipconfig"))[:2000]

    if type == "processes":
        raw = await wmic("tasklist /fo csv /nh")
        result["processes"] = [
            " | ".join(l.strip('"').split('","')[:2])
            for l in raw.splitlines()[:30] if l.strip()
        ]

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def screenshot(filename: str = None) -> str:
    """Chụp toàn bộ màn hình chính và lưu thành file PNG.

Args:
    filename: Tên file PNG (optional, tự sinh nếu bỏ trống)
    """
    name = filename or f"screenshot_{int(time.time() * 1000)}.png"
    save_path = WORKSPACE / name
    sp = str(save_path).replace("\\", "\\\\")
    ps = (
        f"Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        f"$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        f"$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
        f"$g=[System.Drawing.Graphics]::FromImage($b);"
        f"$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
        f"$b.Save('{sp}');"
        f"$g.Dispose();$b.Dispose()"
    )
    r = await run_shell(ps, shell="powershell", timeout=15)
    if not save_path.exists():
        raise RuntimeError(f"❌ Screenshot thất bại: {r['text']}")
    size_kb = save_path.stat().st_size // 1024
    return f"✅ Screenshot: {name} ({size_kb}KB)\nPath: {save_path}"


@mcp.tool()
async def clipboard(action: str, text: str = None) -> str:
    """Đọc hoặc ghi nội dung text vào Windows Clipboard.

Args:
    action: 'read' hoặc 'write'
    text: Text cần ghi (chỉ với action='write')
    """
    if action == "write":
        if text is None:
            raise ValueError("❌ Thiếu text cho action='write'")
        escaped = text.replace("'", "''")
        r = await run_shell(f"Set-Clipboard '{escaped}'", shell="powershell", timeout=5)
        if r.get("isError"):
            raise RuntimeError(f"❌ Clipboard write lỗi: {r['text']}")
        return f"✅ Đã copy {len(text)} ký tự vào clipboard"
    else:
        r = await run_shell("Get-Clipboard", shell="powershell", timeout=5)
        return r["text"].strip() or "(clipboard trống)"


@mcp.tool()
async def send_notification(title: str, message: str) -> str:
    """Hiển thị thông báo toast trên Windows (góc phải màn hình).

Args:
    title: Tiêu đề thông báo
    message: Nội dung thông báo
    """
    t = title.replace("'", "\\'")
    m = message.replace("'", "\\'")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$t.SelectSingleNode('//text[@id=1]').InnerText='{t}';"
        f"$t.SelectSingleNode('//text[@id=2]').InnerText='{m}';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('MCP').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    r = await run_shell(ps, shell="powershell", timeout=10)
    if r.get("exitCode", 0) == 0:
        return f"✅ Notification: \"{title}\""

    # Fallback: MessageBox
    fb = f"Add-Type -AssemblyName PresentationFramework;[System.Windows.MessageBox]::Show('{m}','{t}')"
    await run_shell(fb, shell="powershell", timeout=10)
    return "✅ Notification (dialog fallback)"


# ══════════════════════════════════════════════════════════
# WEB
# ══════════════════════════════════════════════════════════

@mcp.tool()
async def web_search(query: str, count: int = 5) -> str:
    """Tìm kiếm thông tin trên internet thông qua DuckDuckGo Instant Answer API.

Args:
    query: Từ khoá cần tìm (nên dùng tiếng Anh, ngắn gọn)
    count: Số kết quả related topics (mặc định 5)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": "Mozilla/5.0 MCPBot/2.0"},
        )
    d = r.json()
    results = []
    if d.get("AbstractText"):
        results.append({"source": d.get("AbstractSource"), "url": d.get("AbstractURL"), "snippet": d["AbstractText"]})
    for t in (d.get("RelatedTopics") or [])[:count - 1]:
        if t.get("Text"):
            results.append({"url": t.get("FirstURL", ""), "snippet": t["Text"]})
    if not results:
        results.append({"note": "Không có instant answer. Thử query cụ thể hơn.", "query": query})
    return json.dumps(results, ensure_ascii=False, indent=2)


def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    return re.sub(r"\s{2,}", " ", soup.get_text(separator=" ")).strip()


# Domains / patterns thường cần JS render hoặc block httpx
_JS_REQUIRED_PATTERNS = [
    "kaggle.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "facebook.com", "tiktok.com", "cloudflare",
    "medium.com", "substack.com", "notion.so",
]

def _needs_playwright(url: str) -> bool:
    return any(p in url.lower() for p in _JS_REQUIRED_PATTERNS)


async def _fetch_with_httpx(url: str, maxChars: int, timeout: int = 12) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0),
        follow_redirects=True,
    ) as client:
        r = await client.get(url, headers=headers)
    r.raise_for_status()

    if "application/json" in r.headers.get("content-type", ""):
        text = json.dumps(r.json(), ensure_ascii=False, indent=2)
    else:
        text = _extract_text_from_html(r.text)

    if not text or len(text) < 200:
        raise ValueError(f"httpx trả về nội dung quá ít ({len(text)} ký tự) — cần Playwright")

    return text[:maxChars] + "\n...[truncated]" if len(text) > maxChars else text


async def _fetch_with_playwright(url: str, maxChars: int) -> str:
    _, page = await get_browser()
    try:
        # Timeout tổng cho Playwright: 20s (tránh treo quá lâu)
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Chờ JS render nhưng không quá 5s
        try:
            await asyncio.wait_for(
                page.wait_for_function(
                    "() => document.body && document.body.innerText.trim().length > 300",
                    timeout=5000,
                ),
                timeout=6,
            )
        except Exception:
            pass  # lấy luôn những gì đang có

        html = await page.content()
        text = _extract_text_from_html(html)
        title = await page.title()

        if not text or len(text) < 100:
            return f"⚠️ Trang tải xong nhưng nội dung rỗng.\nTitle: {title}\nURL: {page.url}"

        header = f"Title: {title}\nURL: {page.url}\n\n"
        body = text[:maxChars] + "\n...[truncated]" if len(text) > maxChars else text
        return header + body
    except Exception as e:
        if _is_browser_dead_error(e):
            await _force_reset_browser()
            raise RuntimeError(f"Browser đã reset, thử lại: {e}")
        raise


@mcp.tool()
async def web_fetch(url: str, maxChars: int = 8000) -> str:
    """Tải và trích xuất nội dung text từ một URL bất kỳ.

Tự động dùng Playwright (Chrome headless) cho các trang cần JS render
(Kaggle, Medium, Twitter, LinkedIn, v.v.) và httpx cho trang tĩnh thông thường.
Tổng timeout tối đa ~25s để tránh Network connection lost.

Args:
    url: URL đầy đủ cần tải (https:// hoặc http://)
    maxChars: Giới hạn ký tự text trả về (mặc định 8000)
    """
    TOTAL_DEADLINE = 25  # giây — hard cap toàn bộ tool

    async def _run():
        use_playwright = _needs_playwright(url)

        if not use_playwright:
            try:
                return await _fetch_with_httpx(url, maxChars)
            except Exception as e:
                print(f"[web_fetch] httpx failed ({e}), falling back to Playwright")
                use_playwright = True

        if use_playwright:
            try:
                return await _fetch_with_playwright(url, maxChars)
            except Exception as e:
                if _needs_playwright(url):
                    # Last resort: httpx
                    try:
                        print(f"[web_fetch] Playwright failed ({e}), last resort httpx")
                        return await _fetch_with_httpx(url, maxChars)
                    except Exception as e2:
                        raise RuntimeError(
                            f"❌ web_fetch thất bại với cả httpx lẫn Playwright.\n"
                            f"Playwright: {e}\nhttpx: {e2}\n"
                            f"Gợi ý: exec('taskkill /f /im chrome.exe') rồi gọi lại."
                        ) from e2
                raise

    try:
        return await asyncio.wait_for(_run(), timeout=TOTAL_DEADLINE)
    except asyncio.TimeoutError:
        return (
            f"❌ web_fetch timeout sau {TOTAL_DEADLINE}s — trang quá chậm hoặc bị block.\n"
            f"URL: {url}\n"
            f"Gợi ý: Thử lại sau, hoặc dùng browser_action(action='open', url='{url}') "
            f"rồi browser_action(action='get_content') để lấy nội dung."
        )


@mcp.tool()
async def http_request(
    url: str,
    method: str = "GET",
    body: dict = None,
    headers: dict = None,
) -> str:
    """Gửi HTTP request đến bất kỳ API endpoint nào và nhận response.

Args:
    url: URL đầy đủ của endpoint
    method: HTTP method: GET, POST, PUT, PATCH, DELETE
    body: Request body dạng JSON object (với POST/PUT/PATCH)
    headers: HTTP headers bổ sung
    """
    merged_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
        ) as client:
            r = await client.request(method.upper(), url, json=body, headers=merged_headers)
        try:
            data = json.dumps(r.json(), ensure_ascii=False, indent=2)
        except Exception:
            data = r.text
        return f"Status: {r.status_code}\n\n{data[:8000]}"
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"❌ HTTP {e.response.status_code}: {e}")
    except Exception as e:
        raise RuntimeError(f"❌ Request lỗi: {e}")


# ══════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════

@mcp.tool()
def get_datetime() -> str:
    """Lấy ngày và giờ hiện tại theo múi giờ Asia/Saigon (UTC+7).

Luôn gọi tool này thay vì tự suy đoán ngày giờ.
    """
    now = datetime.now(VN_TZ)
    weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    return json.dumps({
        "date":     f"{weekdays[now.weekday()]}, {now.strftime('%d/%m/%Y')}",
        "time":     now.strftime("%H:%M:%S"),
        "iso":      now.isoformat(),
        "unix":     int(now.timestamp()),
        "timezone": "Asia/Saigon (UTC+7)",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def calculate(expression: str) -> str:
    """Tính toán chính xác bằng cách thực thi expression Python.

Hỗ trợ toàn bộ module math: math.sqrt, math.pow, math.ceil, math.floor, v.v.
Không cho phép import, exec, eval không an toàn.

Args:
    expression: Biểu thức Python hợp lệ. Ví dụ: '1_000_000 * 0.075 * 12', 'math.pow(1.08, 10) - 1'
    """
    BANNED = ["import", "__import__", "open", "exec", "eval", "os.", "sys.", "subprocess"]
    for b in BANNED:
        if b in expression:
            raise ValueError(f"❌ Expression chứa từ khoá không được phép: {b}")
    safe_globals = {"__builtins__": {}, "math": math, "abs": abs, "round": round, "min": min, "max": max, "sum": sum}
    try:
        result = eval(expression, safe_globals)  # noqa: S307
        return f"{expression}\n= {result}"
    except Exception as e:
        raise ValueError(f"❌ Lỗi tính toán: {e}")


@mcp.tool()
async def get_weather(city: str) -> str:
    """Lấy thông tin thời tiết hiện tại và dự báo 3 ngày cho một thành phố.

Args:
    city: Tên thành phố (nên dùng tiếng Anh). Ví dụ: 'Ha Noi', 'Ho Chi Minh City'
    """
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"https://wttr.in/{city}?format=j1")
    d  = r.json()
    cur = d["current_condition"][0]
    return json.dumps({
        "city": city,
        "now": {
            "temp":       f"{cur['temp_C']}°C",
            "feels_like": f"{cur['FeelsLikeC']}°C",
            "condition":  cur["weatherDesc"][0]["value"],
            "humidity":   f"{cur['humidity']}%",
            "wind":       f"{cur['windspeedKmph']} km/h",
        },
        "forecast": [
            {
                "date": w["date"],
                "max":  f"{w['maxtempC']}°C",
                "min":  f"{w['mintempC']}°C",
                "desc": w["hourly"][4]["weatherDesc"][0]["value"] if w.get("hourly") else "",
            }
            for w in d["weather"][:3]
        ],
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════
# BROWSER
# ══════════════════════════════════════════════════════════

BROWSER_DEAD_HINTS = """
⚠️ BROWSER ERROR — Hướng dẫn tự xử lý:
Bước 1 — Force kill Chrome + reset browser state:
  exec(command="taskkill /f /im chrome.exe", shell="cmd")
Bước 2 — Thử lại thao tác ban đầu (browser_action sẽ tự khởi động Chrome mới).
Nếu vẫn lỗi sau 2 lần retry:
  exec(command="taskkill /f /im chrome.exe & taskkill /f /im chromedriver.exe", shell="cmd")
  rồi chờ 2 giây và thử lại browser_action một lần nữa.
"""

def _is_browser_dead_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in [
        "target page", "target closed", "browser has been closed",
        "context or browser", "page has been closed", "execution context was destroyed",
        "session closed", "connection closed", "protocol error",
    ])

async def _force_reset_browser():
    """Hard reset toàn bộ browser state, không cần kill Chrome ngoài."""
    global _playwright, _browser, _page
    try:
        if _browser:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            await _playwright.stop()
    except Exception:
        pass
    _browser = None
    _page = None
    _playwright = None


@mcp.tool()
async def browser_action(
    action: str,
    url: str = None,
    selector: str = None,
    text: str = None,
    value: str = None,
    key: str = None,
    script: str = None,
    filename: str = None,
    timeout: int = 10000,
) -> str:
    """Điều khiển Chrome để tự động hoá thao tác web.

Luồng làm việc:
1. action='open'       → mở URL
2. action='screenshot' → chụp ảnh trang
3. action='get_content'→ lấy text + interactive elements + selector
4. action='type'       → nhập text vào input
5. action='click'      → click button/link
6. action='screenshot' → xác nhận kết quả

Các action: open | screenshot | get_content | click | type | select | press_key | wait | evaluate | close

Args:
    action: Hành động cần thực hiện
    url: URL cần mở (action='open')
    selector: CSS selector (click/type/select/wait)
    text: Text để nhập hoặc click theo text
    value: Giá trị option dropdown (action='select')
    key: Tên phím (action='press_key'): Enter, Tab, Escape, ArrowDown...
    script: JavaScript cần chạy (action='evaluate')
    filename: Tên file PNG screenshot (optional)
    timeout: Timeout ms (mặc định 10000)
    """
    MAX_RETRIES = 2
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await _browser_action_inner(
                action=action, url=url, selector=selector, text=text,
                value=value, key=key, script=script, filename=filename, timeout=timeout,
            )
        except Exception as e:
            last_error = e
            if _is_browser_dead_error(e):
                print(f"[browser] Attempt {attempt}/{MAX_RETRIES} — browser dead, resetting... ({e})")
                await _force_reset_browser()
                # Nếu action là open và có url → auto retry sau reset sẽ mở lại URL đó
                # Nếu action khác (click, type...) → sau reset không có page → sẽ fail với hint
                if attempt < MAX_RETRIES:
                    continue
                # Hết retry → raise với hint
                raise RuntimeError(
                    f"❌ Browser bị đóng sau {MAX_RETRIES} lần thử: {e}\n{BROWSER_DEAD_HINTS}"
                ) from e
            else:
                raise  # Lỗi khác → raise thẳng

    raise RuntimeError(f"❌ Unexpected: {last_error}")


async def _browser_action_inner(
    action: str,
    url: str = None,
    selector: str = None,
    text: str = None,
    value: str = None,
    key: str = None,
    script: str = None,
    filename: str = None,
    timeout: int = 10000,
) -> str:
    ms = timeout / 1000  # playwright dùng ms nhưng ta giữ unit gốc

    async def take_screenshot(page, fname=None) -> str:
        name = fname or f"browser_{int(time.time() * 1000)}.png"
        save_path = WORKSPACE / name
        await page.screenshot(path=str(save_path), full_page=False)
        size_kb = save_path.stat().st_size // 1024
        return f"✅ Screenshot: {name} ({size_kb}KB)\nPath: {save_path}"

    async def get_elements(page) -> dict:
        return await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.type || null,
                name: el.name || null,
                id: el.id || null,
                placeholder: el.placeholder || null,
                value: el.value || null,
                selector: el.id ? '#' + el.id : el.name ? '[name="' + el.name + '"]' : el.type ? '[type="' + el.type + '"]' : el.tagName.toLowerCase(),
            }));
            const buttons = Array.from(document.querySelectorAll('button, input[type=submit], a[href]')).slice(0, 20).map(el => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.value || el.getAttribute('href') || '').trim().slice(0, 80),
                type: el.type || null,
                id: el.id || null,
                selector: el.id ? '#' + el.id : el.type === 'submit' ? '[type="submit"]' : el.tagName.toLowerCase(),
            }));
            return { inputs, buttons };
        }""")

    if action == "open":
        if not url:
            raise ValueError("❌ Thiếu url cho action='open'")
        _, page = await get_browser()
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await asyncio.sleep(1)
        title    = await page.title()
        elements = await get_elements(page)
        return json.dumps({
            "status": "✅ Đã mở trang", "title": title, "url": page.url,
            "inputs": elements["inputs"], "buttons": elements["buttons"][:10],
            "tip": "Dùng action='screenshot' để xem giao diện.",
        }, ensure_ascii=False, indent=2)

    elif action == "screenshot":
        page   = await get_active_page()
        result = await take_screenshot(page, filename)
        return f"{result}\nTitle: {await page.title()}\nURL: {page.url}"

    elif action == "get_content":
        page     = await get_active_page()
        title    = await page.title()
        body_txt = await page.evaluate("() => document.body?.innerText?.slice(0, 3000) || ''")
        elements = await get_elements(page)
        return json.dumps({
            "title": title, "url": page.url,
            "text": body_txt, **elements,
        }, ensure_ascii=False, indent=2)

    elif action == "type":
        if not selector:
            raise ValueError("❌ Thiếu selector cho action='type'")
        if text is None:
            raise ValueError("❌ Thiếu text cho action='type'")
        page = await get_active_page()
        await page.wait_for_selector(selector, timeout=timeout)
        await page.click(selector, click_count=3)
        await page.type(selector, text, delay=30)
        return f"✅ Đã nhập \"{text}\" vào {selector}"

    elif action == "click":
        page = await get_active_page()
        if selector:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.click(selector)
            await asyncio.sleep(0.8)
            return f"✅ Đã click: {selector}\nURL hiện tại: {page.url}"
        elif text:
            clicked = await page.evaluate(f"""() => {{
                const els = Array.from(document.querySelectorAll('button, a, input[type=submit], [role=button]'));
                const el = els.find(e => (e.innerText || e.value || '').toLowerCase().includes('{text.lower()}'));
                if (el) {{ el.click(); return true; }}
                return false;
            }}""")
            if not clicked:
                raise RuntimeError(f"❌ Không tìm thấy element có text: \"{text}\"")
            await asyncio.sleep(0.8)
            return f"✅ Đã click element có text: \"{text}\"\nURL hiện tại: {page.url}"
        raise ValueError("❌ Cần cung cấp selector hoặc text cho action='click'")

    elif action == "select":
        if not selector:
            raise ValueError("❌ Thiếu selector cho action='select'")
        if not value:
            raise ValueError("❌ Thiếu value cho action='select'")
        page = await get_active_page()
        await page.wait_for_selector(selector, timeout=timeout)
        await page.select_option(selector, value=value)
        return f"✅ Đã chọn \"{value}\" trong {selector}"

    elif action == "press_key":
        if not key:
            raise ValueError("❌ Thiếu key. Ví dụ: 'Enter', 'Tab'")
        page = await get_active_page()
        await page.keyboard.press(key)
        await asyncio.sleep(0.5)
        return f"✅ Đã nhấn phím: {key}\nURL hiện tại: {page.url}"

    elif action == "wait":
        if not selector:
            raise ValueError("❌ Thiếu selector cho action='wait'")
        page = await get_active_page()
        await page.wait_for_selector(selector, timeout=timeout)
        return f"✅ Element xuất hiện: {selector}"

    elif action == "evaluate":
        if not script:
            raise ValueError("❌ Thiếu script cho action='evaluate'")
        page   = await get_active_page()
        result = await page.evaluate(script)
        if result is None:
            return f"✅ Script đã chạy (không có return value)\nURL hiện tại: {page.url}"
        return str(result) if not isinstance(result, (dict, list)) else json.dumps(result, ensure_ascii=False, indent=2)

    elif action == "close":
        global _browser, _page, _playwright
        if _browser:
            await _browser.close()
            _browser = None
            _page    = None
        if _playwright:
            await _playwright.stop()
            _playwright = None
        return "✅ Đã đóng browser"

    else:
        raise ValueError(
            f"❌ action không hợp lệ: \"{action}\". "
            "Các action hợp lệ: open, screenshot, get_content, click, type, select, press_key, wait, evaluate, close"
        )


# ══════════════════════════════════════════════════════════
# MEMORY
# ══════════════════════════════════════════════════════════

@mcp.tool()
def memory_search(query: str, maxResults: int = 10) -> str:
    """Tìm kiếm nội dung trong bộ nhớ dài hạn (MEMORY.md) và nhật ký hôm nay.

Args:
    query: Từ khoá cần tìm
    maxResults: Số kết quả tối đa (mặc định 10)
    """
    sources = [
        (MEMORY_FILE, "MEMORY.md"),
        (daily_log(),  f"memory/{today_key()}.md"),
    ]
    q       = query.lower()
    results = []
    for fp, label in sources:
        lines = safe_read(fp).splitlines()
        for i, line in enumerate(lines):
            if q in line.lower():
                ctx_start = max(0, i - 1)
                ctx       = "\n".join(lines[ctx_start:i + 2])
                results.append(f"[{label}#{i + 1}]\n{ctx}")
    if not results:
        return f"Không tìm thấy: \"{query}\""
    return "\n---\n".join(results[:maxResults])


@mcp.tool()
def memory_get(target: str, from_: int = 1, lines: int = None) -> str:
    """Đọc toàn bộ hoặc một phần nội dung bộ nhớ.

Args:
    target: 'long-term' = đọc MEMORY.md | 'daily' = đọc nhật ký hôm nay
    from_: Số dòng bắt đầu (1-indexed)
    lines: Số dòng cần đọc (None = đến hết)
    """
    fp      = daily_log() if target == "daily" else MEMORY_FILE
    content = safe_read(fp)
    if not content:
        return "(trống)"
    all_lines = content.splitlines()
    start     = max(0, from_ - 1)
    end       = start + lines if lines else None
    return "\n".join(all_lines[start:end])


@mcp.tool()
def memory_write(target: str, content: str, append: bool = True) -> str:
    """Ghi thông tin vào bộ nhớ dài hạn hoặc nhật ký hôm nay. những nội dung bảo mật như tài khoản mật khẩu nên ghi vào MEMORY.md, còn nhật ký hàng ngày có thể ghi những sự kiện, trạng thái, kết quả quan trọng của ngày hôm đó.

Args:
    target: 'long-term' = ghi vào MEMORY.md | 'daily' = ghi nhật ký hôm nay
    content: Nội dung Markdown cần ghi
    append: True (mặc định) = thêm vào cuối | False = ghi đè hoàn toàn
    """
    fp = daily_log() if target == "daily" else MEMORY_FILE
    ts = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")
    if append:
        append_line(fp, f"\n<!-- {ts} -->\n{content}")
    else:
        safe_write(fp, content)
    label = f"memory/{today_key()}.md" if target == "daily" else "MEMORY.md"
    return f"✅ Đã ghi vào {label}"


# ─── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("\n[MCP] OpenClaw MCP Server v3 (Python)")
    print("[MCP] MCP    : http://localhost:3458/mcp")
    print("[MCP] Health : http://localhost:3458/health\n")
    mcp.run(transport="streamable-http")
