@echo off
rem 打包 蕾米埃尔 Codex 桌宠为 Windows exe
rem 必须用 Windows Python 打包；WSL 里的 PyInstaller 只能出 Linux ELF，不是 Windows exe
cd /d %~dp0

set "PYEXE=C:\Users\lenovo\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=python.exe"

"%PYEXE%" -m PyInstaller --clean --onefile --windowed --name "蕾米埃尔codex桌宠" "silent_pet.py" --distpath "dist" --workpath "build" --specpath "build" --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32
echo.
echo 打包完成，产物在 dist\蕾米埃尔codex桌宠.exe（记得复制到主目录替换）
pause
