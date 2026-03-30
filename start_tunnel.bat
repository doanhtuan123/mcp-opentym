@echo off
setlocal
set URL_FILE=%~dp0data\tunnel-url.txt
if not exist "%~dp0data" mkdir "%~dp0data"
del /f /q "%URL_FILE%" 2>nul

"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:3457 --no-autoupdate 2>&1 | tee_tunnel.cmd
