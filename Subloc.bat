@echo off
rem Double-click to open Subloc. You can also drag a video onto this file.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m subloc.ui.app %*
