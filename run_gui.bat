@echo off
cd /d "%~dp0"
python agent_gui.py
if errorlevel 1 pause
