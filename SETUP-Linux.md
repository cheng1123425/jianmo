# jianmo 本地环境配置说明（Linux 沙箱版）

> 本文档记录本项目从 GitHub 拉取后、在本机（Linux 沙箱）跑通整条流水线的配置步骤。
> 内容对应 README「环境准备」的三件事，但**原 README 是给 Windows 开发机写的**
> （`.venv\Scripts\python.exe`、`freecadcmd.exe`、`D:\` 路径），这里给出 Linux 等价做法。

---

## 一、配置成果（已验证）

| 组件 | 版本 | 位置 |
|---|---|---|
| Python 运行时 | 3.11.1 | `./.venv/bin/python` |
| build123d | **0.13.0** ✓（项目指定版本） | venv 内 |
| matplotlib | **3.11.2** ✓（项目指定版本） | venv 内 |
| FreeCAD | **1.1.3** ✓（项目要求 1.1） | `/root/miniconda/envs/fc/bin/freecadcmd` |
| A3 图框模板 | ISO/A3_Landscape_TD.svg | `/root/miniconda/envs/fc/share/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg` |

## 二、环境变量（`pipe.py` 靠这三个定位工具，脚本里不含业务路径）

| 变量 | 本机应指向 |
|---|---|
| `MPIPE_PY` | `/workspace/jianmo/.venv/bin/python` |
| `MPIPE_FC` | `/root/miniconda/envs/fc/bin/freecadcmd`（**注意全小写**） |
| `MPIPE_TD` | `/root/miniconda/envs/fc/share/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg` |

已封装在 `env.sh`，用前 `source env.sh` 即可（会自动打印三项路径，并检查是否存在）。

---

## 三、从零复现的步骤

```bash
cd /workspace/jianmo

# 1) 拉取仓库（浅克隆，省流量）
git init -q && git remote add origin https://github.com/cheng1123425/jianmo.git
git fetch --depth 1 origin main && git checkout -b main origin/main

# 2) 建 venv 并装 Python 依赖
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install build123d==0.13.0 matplotlib==3.11.2

# 3) 装 FreeCAD（不是 pip 包，用 conda-forge）
#    ⚠ 默认 solver 极慢（>10 分钟解不出），必须加 --solver=libmamba
conda create -y -n fc --solver=libmamba -c conda-forge freecad=1.1.3 python=3.13

# 4) 加载环境变量
source env.sh
```

## 四、与 Windows 开发机的差异（注意事项）

| 项 | Windows 开发机 | 本 Linux 沙箱 |
|---|---|---|
| venv python | `.venv\Scripts\python.exe` | `.venv/bin/python` |
| FreeCAD 命令 | `freecadcmd.exe` | `freecadcmd`（全小写，在 `fc/bin/`） |
| A3 模板根 | `<FC>/data/Mod/TechDraw/...` | `<FC>/share/Mod/TechDraw/...`（`data`→`share`） |
| Python 版本 | 3.13.12 | 3.11.1（build123d 0.13.0 实测兼容） |

## 五、验证结果（本次实测）

```bash
# 隔离校验：10 个步骤全部只通过消息通信
.venv/bin/python guard.py --steps steps
# → 隔离检查通过：10 个步骤全部只通过消息通信

# 主零件（垫片）全链 + 闭环
.venv/bin/python pipe.py --loop
# → 闭环结局：pass（1 轮），用时 10.5 秒

# 另两个已迁入流水线的零件
.venv/bin/python pipe.py --part parts/bracket  --loop   # → pass（1 轮）
.venv/bin/python pipe.py --part parts/lbracket --loop   # → pass（1 轮）

# 闭环自动修正（故意改错 R_BOSS=150、H_WING=35）
.venv/bin/python pipe.py --loop --auto
# → 第 1 轮 判定=fix → 应用修正 → 第 2 轮 pass
```

## 六、常用命令速查

```bash
source env.sh                                   # 每次新开终端先加载环境

# 全链：三维 → STEP → 工程图 → PDF → 尺寸表
.venv/bin/python pipe.py
.venv/bin/python pipe.py --part parts/bracket

# 全链 + 闭环校核（只报不改）
.venv/bin/python pipe.py --loop

# 全链 + 闭环自动修正
.venv/bin/python pipe.py --part parts/bracket --loop --auto

# 强制重跑（忽略指纹缓存）
.venv/bin/python pipe.py --no-cache

# 调试：每步入参/出参/耗时/判定 → _msg/trace.jsonl
.venv/bin/python pipe.py --part parts/lbracket --loop --trace

# 单步（注意：--only 不跑前置步骤）
.venv/bin/python pipe.py --only s1_build

# 流程图（Mermaid）+ 高亮路径报告（HTML）
.venv/bin/python tools/gen_flowchart.py
.venv/bin/python tools/trace_view.py --part parts/lbracket
```

## 七、产物位置

| 文件 | 说明 |
|---|---|
| `drawing.pdf` / `.png` | A3 横向矢量图纸（三视图 + 完整标注） |
| `dims_table.pdf` / `.md` | 尺寸命名与推导对照表 |
| `models/*.step` / `.stl` | 三维实体导出（AP214 纯几何，无参数） |
| `parts/<零件>/` | 各零件独立目录（params / steps / notes / 产物） |
| `_msg/` | 消息文件（运行时产物，已被 .gitignore 忽略） |

---

## 八、两个已知坑（来自 PUSH.md，push 时才需要）

1. **不自动推送**：项目约定模型更新后只在本地提交，等用户明确说「上传/push」才推。
2. **沙箱写 ref**：若 `git push` 后 `git status` 显示 `[gone]`，手动补：
   ```bash
   mkdir -p .git/refs/remotes/origin
   git rev-parse HEAD > .git/refs/remotes/origin/main
   ```
