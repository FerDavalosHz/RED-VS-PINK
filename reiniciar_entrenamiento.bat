@echo off
REM Doble clic: para el entrenamiento (si hay uno) y lo vuelve a lanzar.
REM NO borra lo aprendido: sigue desde la ultima ronda guardada.
cd /d "%~dp0"
echo.
echo === Parando el entrenamiento anterior ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0parar_entrenamiento.ps1"
echo.
echo === Lanzando el entrenamiento ===
echo (Ctrl+C para pararlo. Si cierras esta ventana, se para.)
echo.
venv\Scripts\python.exe -u entrenar.py
echo.
pause
