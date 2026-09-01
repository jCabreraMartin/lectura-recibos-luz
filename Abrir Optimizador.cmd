@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo No se encuentra el entorno Python del proyecto.
  echo Ejecuta primero: python -m venv .venv
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m invoice_reader.gui

