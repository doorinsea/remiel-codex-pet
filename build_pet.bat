@echo off
rem 打包 蕾米埃尔 Codex 桌宠为 Windows exe
rem 需要 Windows 版 Python（含 PyInstaller / pillow / pynput）。
rem 默认使用 PATH 里的 py -3 或 python；可用环境变量 PYEXE 指定 Python 命令或路径。
cd /d %~dp0

if defined PYEXE goto :have_py
where py >nul 2>nul
if not errorlevel 1 (set "PYEXE=py -3") else (set "PYEXE=python")
:have_py

%PYEXE% -m PyInstaller --clean --onefile --windowed --name "蕾米埃尔codex桌宠" "silent_pet.py" --distpath "dist" --workpath "build" --specpath "build" --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32
echo.
echo 打包完成，产物在 dist\蕾米埃尔codex桌宠.exe（记得复制到主目录替换）
pause
