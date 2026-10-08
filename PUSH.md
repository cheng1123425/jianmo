# 上传 GitHub 的规矩（`jianmo`）

> **不自动推送。** 每次模型/流水线更新，agent 只在本机跑通并提交（commit），
> **等你明确说「上传 / push / 传 GitHub」之后才 push**。
> 这条是为了避免半成品、或者用错参数的一版被推上去。

---

## 一、上传前必做的检查（按顺序）

```bash
# 1) 隔离检查：任何一个步骤越过消息线就拒绝跑
python guard.py --steps steps
python guard.py --steps parts/bracket/steps --steps steps

# 2) 主零件（垫片）：全链 + 闭环
python pipe.py --loop

# 3) 铰链支座：全链 + 闭环
python pipe.py --part parts/bracket --loop

# 4) 看本地改动，确认没有把临时产物/密钥带进去
git status --short
git diff --stat
```

判定标准：两步闭环都输出 `闭环结局：pass`，且 `git status` 里没有 `_msg/`、
`*.FCBak`、`__pycache__`、`.cache.json` 之类的运行时文件。

---

## 二、提交（本地）

```bash
git add -A
git commit -m "<一句话说明改了什么>"
```

提交内容一般包括：

| 类型 | 例子 |
|---|---|
| 参数 | `params.py`、`parts/*/params.py` |
| 尺寸关系与基准 | `dims_spec.py`、`ref_spec.py` |
| 步骤脚本 | `steps/*.py`、`parts/*/steps/*.py` |
| 方案与记录 | `notes/plan_src.md`、`notes/model_notes.md`、`notes/errors.md` |
| 文档 | `README.md`、`MSG.md`、`lessons.md` |
| 产物 | `models/*.step`、`drawing.pdf`、`dims_table.*` |

不入库（已在 `.gitignore`）：`_msg/`（含 `.cache.json`）、`_drawing.json`、`__pycache__/`、`*.FCBak`、`.workbuddy/`。

---

## 三、推送（**等你提醒**）

```bash
git push origin main
```

已知的两个坑（原开发机）：

1. **SSH**：用的是 `~/.ssh/id_ed25519_jianmo`（已配 `core.sshCommand`）。
   22 端口偶发 reset → 重试，或走 `ssh -p 443 git@ssh.github.com`。
2. **沙箱写 ref**：`push` 报成功但 `.git/refs/remotes/origin/main` 没落盘时
   （`git status` 显示 `[gone]`），手动补：

   ```bash
   mkdir -p .git/refs/remotes/origin
   git rev-parse HEAD > .git/refs/remotes/origin/main
   ```

---

## 四、上传记录

| 日期 | commit | 内容 |
|---|---|---|
| 2026-09-29 | `93b6e03` | 首版：垫片 + 球铰盖 + 铰链支座 |
| 2026-09-30 | `fcf126f` | 消息驱动隔离流水线（steps/s1~s8 + pipe + guard + msgio） |
| 2026-09-30 | `dd656ac` | s0_plan / s9_record + 统一驱动器（`--part`）+ 指纹缓存 + 延迟出图 |
| 2026-09-30 | `5cc7239` | 接入 mech-projection-analysis 技能回路（skill_advice → s0 → skill_feedback ← s9） |
| 2026-09-30 | `a687bea` | bracket 重跑闭环 pass，刷新方案时间戳 |
| 2026-09-30 | `08f876b` | 垫片重跑闭环 pass，刷新方案与记录 |
| 2026-09-30 | `0cfc657` | s9_record 写回的技能反馈与模型记录（闭环产物） |
| 2026-09-30 | `0dd18fe` | lbracket：补全 steps/s3~s8 独立副本 + 修 s1 底板 R9 圆角，闭环 pass |
| 2026-09-30 | `8e91fc9` | lbracket s3_render：修「逐边归一化」导致的视图翻转 |
| 2026-09-30 | `e96b680` | lbracket 第 2 版：按原图重修（叶形底板 / 顶双耳 / 中央窗口 / 3×φ8） |
| 2026-09-30 | `2f77f52` | MSG.md：逐步输入/输出表 + 技能提问回路 + 「维护约定」 |
| 2026-09-30 | `e631e6d` | README + lessons：补 lbracket 现状、缺 steps 静默回退警告、§7 尺寸链手法 |
| 2026-09-30 | `dd59950` | 三件闭环产物（垫片 / 铰链支座 / L 形支座）重跑闭环 pass |
| 2026-10-08 | `13f96af` | 新增流程图自动生成：tools/gen_flowchart.py 从 pipe.py 的 STEPS 生成 docs/flowchart.md |
| 2026-10-08 | `ed5ff0d` | pipe.py 新增 --trace：每步入参/出参/耗时/判定写成 _msg/trace.jsonl |
| 2026-10-08 | `42ed67b` | 闭环产物：回归验证（三条闭环 pass）产生的方案与记录 |
| 2026-10-08 | `4492e46` | 新增 tools/trace_view.py：把 trace 画成「高亮路径」报告（直观调试） |
| 2026-10-08 | 本次推送 | 代码专家加固 pipe.py：① 只有 s0_plan/s9_record 允许回落 root 通用实现，s1~s8 缺失改为启动即报错（根目录那几份是垫片副本，schema 对不上）；② 指纹缓存命中前核对产物是否存在/被改动，命中刷新 seq；③ MSG.md/README.md 同步。新增 tools/msg_view.py（消息线查看器，含轮次/回边，代码+中文命名对照）；三条闭环复跑均 pass。 |
