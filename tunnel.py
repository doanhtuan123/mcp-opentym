"""
Cloudflare Quick Tunnel — tương đương tunnel.js
Chạy qua: python tunnel.py
Hoặc qua PM2: pm2 start tunnel.py --interpreter python
"""

import subprocess
import time
import re
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
URL_FILE = BASE_DIR / "data" / "tunnel-url.txt"
URL_FILE.parent.mkdir(parents=True, exist_ok=True)

CLOUDFLARED = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"

def start_tunnel():
    print("[tunnel] Starting cloudflared quick tunnel...")
    while True:
        try:
            proc = subprocess.Popen(
                [CLOUDFLARED, "tunnel", "--url", "http://localhost:3458", "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Xoá URL cũ
            try:
                URL_FILE.unlink()
            except FileNotFoundError:
                pass

            url_found = False
            for line in proc.stdout:
                print(line, end="")
                if not url_found:
                    match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
                    if match:
                        url = match.group(0)
                        print(f"\n✅ Tunnel URL: {url}/mcp\n")
                        URL_FILE.write_text(url + "\n", encoding="utf-8")
                        url_found = True

            code = proc.wait()
            print(f"[tunnel] Exited ({code}), restarting in 5s...")
            try:
                URL_FILE.unlink()
            except FileNotFoundError:
                pass
            time.sleep(5)

        except FileNotFoundError:
            print(f"❌ Không tìm thấy cloudflared: {CLOUDFLARED}")
            print("Tải tại: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            time.sleep(10)
        except Exception as e:
            print(f"[tunnel] Error: {e}, retrying in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    start_tunnel()
