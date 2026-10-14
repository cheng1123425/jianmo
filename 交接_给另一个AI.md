# 双耳直角支座（ybracket）· 会话交接

> 本文档由本会话的 AI 自动生成，供另一个 AI 快速接管上下文。
> 生成时间：2026-10-14 · 工作根目录：`/workspace` · 仓库：`/workspace/jianmo`（git remote: `https://github.com/cheng1123425/jianmo.git`）

---

## 1. 这个任务是什么

把一张**双耳直角支座工程图**做成真正的零件：三维模型（STEP/STL）+ 工程图（三视图）+ 尺寸对照表，并跑通项目自有的 13 步建模流水线（mpipe/1 消息协议）。

## 2. 产物在哪（最重要的部分）

### 2.1 最终交付（成品，直接看）

根目录：**`/workspace/双耳支座成果/`**

| 文件 | 内容 |
|---|---|
| `工程图_三视图.png` / `工程图_三视图.pdf` | 第一角投影三视图（Front / Top / Right），三视图不重叠、完整落入图框 |
| `尺寸对照表.png` / `.pdf` / `.md` | 15 项尺寸逐项对比：模型 vs 图纸基准，全部一致 |
| `ybracket.step` / `ybracket.stl` | 三维模型，包围盒 200×144×120 mm |
| `三视图预览.png` | 模型预览 |

### 2.2 零件工程目录（可复跑的源头）

根目录：**`/workspace/jianmo/parts/ybracket/`**

```
parts/ybracket/
├── params.py               # 20+ 建模参数（len_x=200 / depth_y=144 / height_z=120 /
│                           #   EAR_R=42 / EAR_PITCH=116 / EAR_T=32 / EAR_CY=72 /
│                           #   D_THRU=32 / D_CBORE=54 / CBORE_DEPTH=22 ...）
├── dims_spec.py            # 13 项尺寸命名规范
├── ref_spec.py             # 三视图基准真值（投影校验用）
├── steps/
│   ├── s1_build.py         # build123d 双耳建模（双耳 Circle(±58,72,R42) extrude +
│   │                       #   中心台阶孔 Ø54 深22 + Ø32 通孔），产物 STEP/STL
│   ├── s2_drawing.py       # 真 FreeCAD 版工程图（TechDraw），已在静态层适配 ybracket
│   ├── s2_drawing_nofc.py  # 沙箱无 FreeCAD 的等效实现：正交投影生成同 schema _drawing.json
│   ├── s3_render.py        # 渲染三视图 PNG/PDF（Front 115,185 / Top 115,70 / Right 295,185）
│   ├── s4_table.py         # 尺寸对照表
│   └── s5_collect.py … s8_apply.py   # 闭环段（compare/decide/apply）
├── models/ybracket.step / .stl        # 流水线产出的模型本体
├── notes/plan_src.md       # 6 阶段构造方案
├── 本机运行说明.md          # 用户 Windows 本机跑 FreeCAD 的前置检查/环境变量/命令
├── _drawing.json           # 视图几何数据（schema: views[name]{X,Y,plot_scale,edges,circles,hlines}）
├── drawing.png / .pdf      # 流水线工程图产物
└── dims_table.md/.png/.pdf # 流水线尺寸表产物
```

### 2.3 本次会话额外改动的仓库级文件

- `pipe.py`：ybracket 适配
- `.gitignore`：忽略 `notes/*/dwg_semantics.json` 运行时产物
- `README.md`：同步本机 FreeCAD 跑法（环境变量 `MPIPE_PY` / `MPIPE_FC` / `MPIPE_TD`）

## 3. 关键技术结论（踩过的坑，接管的 AI 必读）

1. **build123d 的 `project_to_viewport` 是透视投影**：圆会投成椭圆、跨距算错（实测 182.8 vs 真实 200）。解法：用正交投影——按视线方向丢掉一个坐标分量（Front 丢 Y、Top 丢 Z、Right 丢 X）。
2. **边的圆心 API**：`e.center()` 返回的是错误值（类 bbox），真圆心是 `e.arc_center`；`e.radius` 是属性不是方法。
3. **视图坐标约定**：`_drawing.json` 里 edges/circles 的坐标以视图中心为原点（±半长）；s3_render 的换算为 `ex = v["X"] + q[0]*sc`、`ey = v["Y"] + (ey_max - q[1])*sc`（Top 视图不 flip）。
4. **沙箱没有 FreeCAD**：用 `s2_drawing_nofc.py` 生成同 schema 的 `_drawing.json`，使 s3/s4/闭环全部可跑。
5. **闭环结局**：s6_compare 模型 vs 基准 **pass**；s5b/s6b 的告警来自图纸解析层标定错 1.89 倍，非模型问题。

## 4. 复跑方式

### 4.1 沙箱内（无 FreeCAD）

```bash
cd /workspace/jianmo
source env.sh
python pipe.py --part parts/ybracket --loop   # 闭环，期望输出「闭环结局：pass」
```

### 4.2 用户 Windows 本机（有 FreeCAD 1.1）

```bat
set MPIPE_PY=D:\3d\build123d\.venv\Scripts\python.exe
set MPIPE_FC=D:\3d\新建文件夹\FreeCAD 1.1\bin\freecadcmd.exe
set MPIPE_TD=D:\3d\新建文件夹\FreeCAD 1.1\data\Mod\TechDraw\Templates\ISO\A3_Landscape_TD.svg
cd /d <仓库路径>\jianmo
python pipe.py --part parts/ybracket --loop
```

注意：freecadcmd 默认 GBK 输出，脚本内需 `sys.stdout.reconfigure(encoding="utf-8")`。

## 5. Git / 上传现状

- 本地分支 `main` 已含 4 个 ybracket 提交（e79af04 / 7f5d46d / 90923d1 / 2b9d0d3），未推送。
- 工作区另有 54 个文件未提交（含各零件闭环复跑产物、pipe.py 加固、根目录 demo 复跑记录）。
- **推送障碍**：沙箱到 `github.com` 网络阻断（`git ls-remote` 超时；`api.github.com` 可达），且沙箱无任何 GitHub 凭证（gh 未登录、IDE credential helper 对该仓库返回空）。
- 项目 `PUSH.md` 规定：不自动推送，须用户明确说「上传」；上传前须跑 `guard.py` 隔离检查 + 两个零件闭环 pass。
- 用户已明确授权上传，待办：建 `ybracket` 分支 → 提交 → push（push 需用户本机执行或提供有效 PAT 走 api.github.com REST 通道）。

## 6. 本会话未能完成的事项

- 无法在用户 Windows 本机直接执行 `freecadcmd.exe`（沙箱与用户本机无通道，这是物理隔离，不是权限问题）。
- `s2_drawing.py`（真 FreeCAD 版）只做了静态审查，未实跑；若用户本机报错需贴原文修复。
