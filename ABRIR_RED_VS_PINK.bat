@echo off
REM Doble clic para abrir RED vs PINK. Se abre la pagina en el navegador y desde
REM ahi se controla todo (entrenar, parar, puntos, mapa, ver partidas).
REM Esta ventana se cierra sola: el servidor queda funcionando en segundo plano.
cd /d "%~dp0"
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" servidor.py
) else (
    start "" pythonw servidor.py
)
