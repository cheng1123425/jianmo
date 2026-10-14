@echo off
rem ============================================================================
rem jianmo 本地环境配置（Windows 版）
rem 用法： 在 jianmo 目录里执行  call env.bat
rem 作用： 把 MPIPE_* 三个环境变量指到本机实际工具路径，并设 pip 镜像
rem ----------------------------------------------------------------------------
rem 说明：本机 FreeCAD 装在 D:\cad2024\FreeCAD 1.1（非原开发机的 D:\3d\新建文件夹），
rem       build123d 装在当前仓库的 .venv 里（python -m venv .venv 后 pip 安装）。
rem ============================================================================

set "JIANMO_ROOT=%~dp0"
if "%JIANMO_ROOT:~-1%"=="\" set "JIANMO_ROOT=%JIANMO_ROOT:~0,-1%"

rem 1) venv 的 python（build123d + matplotlib）
set "MPIPE_PY=%JIANMO_ROOT%\.venv\Scripts\python.exe"
if not exist "%MPIPE_PY%" (
  echo [env][警告] venv 的 python 不存在：%MPIPE_PY%
  echo           请先： python -m venv .venv 然后 .venv\Scripts\python.exe -m pip install -r requirements.txt
)

rem 2) FreeCAD 命令行版（本机 D:\cad2024\FreeCAD 1.1）
set "MPIPE_FC=D:\cad2024\FreeCAD 1.1\bin\freecadcmd.exe"
if not exist "%MPIPE_FC%" (
  echo [env][警告] FreeCAD 命令行不存在：%MPIPE_FC%
  echo           请改成本机实际的 freecadcmd.exe 路径
)

rem 3) FreeCAD 的 A3 横向图框模板（注意 Windows 下是 data/ 而非 share/）
set "MPIPE_TD=D:\cad2024\FreeCAD 1.1\data\Mod\TechDraw\Templates\ISO\A3_Landscape_TD.svg"
if not exist "%MPIPE_TD%" (
  echo [env][警告] A3 图框模板不存在：%MPIPE_TD%
)

echo [env] MPIPE_PY = %MPIPE_PY%
echo [env] MPIPE_FC = %MPIPE_FC%
echo [env] MPIPE_TD = %MPIPE_TD%
