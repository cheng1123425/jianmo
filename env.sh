#!/usr/bin/env bash
# ============================================================================
# jianmo 本地环境配置（Linux 沙箱版）
# ----------------------------------------------------------------------------
# 用法：  source env.sh
# 作用：  为 pipe.py / 各 steps 脚本设置三项环境变量，指到本机实际工具路径。
#         Windows 开发机的默认值写在 pipe.py 里，这里只做「本机覆盖」。
# ----------------------------------------------------------------------------
# 对应的 README「环境准备」三件事：
#   1) Python 依赖  → .venv/           （build123d==0.13.0 + matplotlib==3.11.2）
#   2) FreeCAD      → conda 环境 fc/   （FreeCAD 1.1.3，非 pip 包）
#   3) 环境变量     → 本文件
# ============================================================================

_JIANMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# 1) venv 的 python 可执行文件（Windows 上是 .venv\Scripts\python.exe）
export MPIPE_PY="$_JIANMO_ROOT/.venv/bin/python"

# 2) FreeCAD 命令行版（Windows 上是 freecadcmd.exe）
#    Linux 下 conda 装的 FreeCAD 提供 bin/freecadcmd（全小写）
_FREECAD_PREFIX="${FREECAD_PREFIX:-/root/miniconda/envs/fc}"
export MPIPE_FC="$_FREECAD_PREFIX/bin/freecadcmd"

# 3) FreeCAD 的 A3 横向图框模板（TechDraw）
#    Linux 下位于 share/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg
export MPIPE_TD="$_FREECAD_PREFIX/share/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg"

echo "[env] MPIPE_PY = $MPIPE_PY"
echo "[env] MPIPE_FC = $MPIPE_FC"
echo "[env] MPIPE_TD = $MPIPE_TD"

if [ ! -x "$MPIPE_PY" ]; then
  echo "[env][警告] venv 的 python 不存在，请先： python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi
if [ ! -x "$MPIPE_FC" ]; then
  echo "[env][警告] FreeCAD 命令行不存在，请先： conda create -n fc -c conda-forge freecad=1.1.3 python=3.13"
fi
if [ ! -f "$MPIPE_TD" ]; then
  echo "[env][警告] A3 图框模板不存在：$MPIPE_TD"
fi
