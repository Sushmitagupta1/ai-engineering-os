@echo off
rem AI Engineering OS web app launcher (opens browser)
set "VENV=C:\Users\Aum\Documents\Default Project\ai-engineering-os\freeworker\.venv\Scripts"
set "ROOT=C:\Users\Aum\Documents\Default Project\ai-engineering-os"
start "" "http://127.0.0.1:8787"
"%VENV%\python.exe" "%ROOT%\app\server.py"