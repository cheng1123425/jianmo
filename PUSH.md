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

# 4) 架构影响面：有没有"删了/改了仍有产品依赖"的破坏性变更
#    退出码 2 = 禁止上传（见 MSG.md §〇 接口演进纪律）
python tools/arch_impact.py --strict

# 5) 看本地改动，确认没有把临时产物/密钥带进去
git status --short
git diff --stat
```

判定标准：三步闭环都输出 `闭环结局：pass`；`arch_impact.py --strict` **退出码 0**
（有破坏性变更时退出码 2，此时要么把老函数改成转发、要么先迁完产品）；
且 `git status` 里没有 `_msg/`、`*.FCBak`、`__pycache__`、`.cache.json` 之类的运行时文件。

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
| 2026-10-14 | `c8e7672` | **推 sandbox-merge 分支（非 main）**：① s6b_projection.py 修复（_load_json_opt 改 msgio.ref_path，解决误读根目录 _drawing.json 的 4 条假投影错误，已编译待闭环）；② ybracket ref_spec 补全 13 项 MARKS；③ 沙箱 zip 的 13 步流水线代码同步（pipe.py/s0_plan/s7_decide）；④ 四件闭环产物回归；⑤ 新增 HANDOFF-2026-10-14.md。注意：含未验证项（ybracket 模型 bug 开放、s6b 未跑闭环），按 PUSH.md 约定不进 main；推送触发 PUSH.md「沙箱写 ref」坑，已手动补 .git/refs/remotes/origin/sandbox-merge。另：验证报告/z2c_sample.parquet(84MB) 超 50MB 告警但已入库。 |
| 2026-10-14 | `74a2c69` → `dd5a3be`（共 6 个） | **推 `refactor/naming-and-layering` 分支（非 main）**：① **命名规范化**——参数改四段式 `<部位>_[<修饰>_]<量型>[_<方向>]`，带方向的量必带轴向后缀；新增 `tools/check_naming.py`（可执行检查）与 `tools/rename_params.py`（tokenize 标识符级改名）；`docs/rename_maps/*.json` 存 4 个零件改名映射（可反向撤销）；命名 0 error/0 warning。② **逻辑分层**——`SHARED_STEPS` 5→9（新增 s4_table/s5_collect/s7_decide/s8_apply）；新增 `lib/` 系统层骨架（`collect.py` / `drawing_fc.py` / `drawing_render.py`）；删 12 个零件副本，零件只留 4 个含几何/标注的步骤。③ **s6b 修复**——容差 1e-6→1e-3（FreeCAD 投影噪声 1e-4 量级），高度链要求 ≥2 段。④ **出图自动适配**——`s3_render` 分两遍绘制，保证视图/标注/文字不越图框（bracket/lbracket/ybracket 均已收进图框）。⑤ **垫片迁入 `parts/gasket/`**——根目录只剩框架，默认 `--part` 改 `parts/gasket`。⑥ **s2/s3 抽 lib**——3 个零件文件从 250~283 行缩到约 100 行，只声明视图布局与标注布置（s3 用数据清单 DIMS、s2 用 `place_marks` 回调）。**关键验证：每个零件「抽 lib 前 vs 后」像素对比全部 0 差异**（`tools/diff_images.py`）；四件闭环全 pass，guard 26/26。遗留见 `docs/遗留事项与下一步.md`（gasket 是另一套老实现未纳入、bracket 标注数字硬编码等）。 |
| 2026-10-15 | `703a619` | **推 `feature/ir-feature-tree` 分支（非 main）**：① **IR 路线定案**——IR 当唯一真值源（不再是"双后端"），build123d 升为几何引擎 + 特征树真源，FreeCAD PartDesign 退为按需物化的交互面，TechDraw 出图，`drawing.anchors` 缝 3D↔2D；四项 2D↔3D 决策拍板（锚点放 IR 特征侧 / 绑定存可重放查询不存编号 / 图纸只读 / 内腔不可见当特例放行）。② **A** `lib/ir.py`：IR schema（feature 八栏 + 词表 + `validate()` + dump/load）。③ **B** `tools/recorder.py`：build123d 执行+录制 → IR（三种注入：模块属性补丁 + `Compound.__sub__/__add__` 布尔钩子 + `Builder._get_context()` 快照中间形状），样板 `parts/lbracket/ir.json`（26 事件 → 9 特征）。④ **交接文档** `docs/HANDOFF-2026-10-15.md`。⑤ `.gitignore` 忽略本机 `env.bat`。❗**实测关键坑**：build123d 的 `BuildPart`/`BuildSketch` 一点都不能打补丁（替换 BuildPart 破坏 `pending_faces` 传递；替换 BuildSketch 类或改其 `__init__` 破坏 `BuildLine`→`make_face` 边传递）⇒ 草图平面只能静态扫源码。保真度：录制最终形状 vs 流水线 s1_build 输出 bbox/solids 一致、体积差 0.03。上传前检查：guard 9/13 步全过；垫片 + bracket 闭环均 `闭环结局：pass`。**下一步**：C（IR→build123d 生成器 + 往返自测）→ D/E（PartDesign 生成 + 回读）→ G（2D↔3D 三层绑定）。 |

### ⚠️ 本次推送的坑：本地分支 ref 建不了

`git checkout -b refactor/naming-and-layering` **报成功**，但 `.git/refs/heads/refactor/naming-and-layering`
**没落盘**（沙箱写 ref 的坑，见 §五）。结果这 6 个 commit 实际落在 **`sandbox-merge`** 上，
`git branch --show-current` 显示的是 `sandbox-merge`（ahead 6）。

**解法**：推送时**直接指定远程分支名**，不依赖本地 ref：

```bash
GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -i $HOME/.ssh/id_ed25519" \
  git push git@github.com:cheng1123425/jianmo.git \
  HEAD:refs/heads/refactor/naming-and-layering
```

这样远程会**新建独立分支**，`origin/sandbox-merge` 与 `origin/main` 都不受影响。

### 本地分支状态（2026-10-15 16:40 更新）

| 分支 / 标记 | 指向 | 与远程 |
|---|---|---|
| `main` | `029adbd` | ✅ 一致（很久没动） |
| `sandbox-merge` | `c1cc32c` | ⚠️ 沙箱不能在 `refs/heads/` 下新建 ref，故本地这个 ref **实际承载 feature 分支的工作**；领先 `origin/sandbox-merge` 23 个 commit |
| tag `refactor-naming-and-layering-c69e466` | `c69e466` | 本地标记 |
| 远程 `refactor/naming-and-layering` | `59d35c3` | ✅ 已推送 |
| **远程 `feature/ir-feature-tree`** | `c1cc32c` | ✅ 已推送（2026-10-15，快进 `2ff1c06` → `c1cc32c`，共 12 个 commit） |

工作区 `git status` **干净**（0 改动）。

**IR 路线这批工作放在 `feature/ir-feature-tree`**（不在 main、不推 sandbox-merge），
沿用项目一贯做法：新工作开新远程分支，验证充分后再谈合流。

**为什么本地 sandbox-merge 会领先**：沙箱不允许在 `refs/heads/` 下**新建** ref ——
`git checkout -b` / `git branch -f` / `git update-ref` / bash 手写文件 **四种方式都试过，均不落盘**
（`git branch -v` 看不到新分支）。所以这些 commit 只能挂在已存在的 `sandbox-merge` 上。
（具体数字会随后续 commit 变化，看表时以 `git branch -v` 的实际输出为准。）

补充事实：**`refs/tags/` 下新建是允许的**（`git tag` 能落盘），故用 tag 把 `c69e466` 标住。
**修改已存在的 ref 也是允许的**（`update-ref refs/heads/sandbox-merge <sha>` 有效）。

⚠️ **不要 `git push origin sandbox-merge`** —— 会把重构直接推到该分支。

**在真机（无沙箱限制）上整理**：

```bash
git branch -f refactor/naming-and-layering c69e466   # 建真正的本地分支
git branch -f sandbox-merge c0f4a2e                  # 把 sandbox-merge 拉回与远程一致
git checkout refactor/naming-and-layering
git push -u origin refactor/naming-and-layering      # 之后可直接 push
```

也可以从远程取回：

```bash
git fetch origin refactor/naming-and-layering
git checkout -b refactor/naming-and-layering FETCH_HEAD
```

---

## 五、本机（当前开发机）推送备忘

原开发机的 SSH 约定（`~/.ssh/id_ed25519_jianmo` + `core.sshCommand`）**在本机不适用**。本机情况：

| 项 | 值 |
|---|---|
| 远程（fetch 用） | `https://gh-proxy.com/https://github.com/cheng1123425/jianmo.git` |
| **HTTPS 推送** | ❌ 无凭据（`credential.helper=helper-selector`，无 `~/.git-credentials`），会报 `could not read Username` |
| **SSH 推送** | ✅ 用 `~/.ssh/id_ed25519_jianmo`（**可写**）；⚠️ `~/.ssh/id_ed25519` 是**只读 deploy key**，用它 push 会报 `Permission ... denied to deploy key`（2026-10-15 实测） |

**本机推荐推送命令**（不改动 remote 配置）：

```bash
git push origin HEAD:refs/heads/<分支名>     # 直接走仓库 core.sshCommand 里的 id_ed25519_jianmo

# ⚠️ 下面这条已【作废】：id_ed25519 是只读 deploy key，会报 denied
# GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=no -i $HOME/.ssh/id_ed25519" \
#   git push git@github.com:cheng1123425/jianmo.git HEAD:refs/heads/<分支名>
```

### ⚠️ 本机沙箱的「写 ref」坑（比原开发机的更严重）

`git checkout -b <新分支>` 会**报成功**（`git branch --show-current` 也显示新分支名），
但 `.git/refs/heads/<新分支>` **根本没落盘** —— 于是 `git commit` 报
`your current branch '...' does not have any commits yet`。

已试过三种补法，**都无效**（沙箱对 `.git/refs/` 的写入被隔离，git 进程看不到）：

```bash
mkdir -p .git/refs/heads/refactor && echo <sha> > .git/refs/heads/refactor/<name>   # ✗
git update-ref refs/heads/refactor/<name> <sha>                                     # ✗
echo "<sha> refs/heads/refactor/<name>" >> .git/packed-refs                         # ✗
```

**可行做法**：在已存在的分支（如 `sandbox-merge`）上 commit，再
`git push <url> HEAD:refs/heads/<新分支>` —— 远程仍会得到独立的新分支。
（`.git/config`、`.git/index`、`.git/HEAD` 是可写的，只有 `refs/` 不行。）
| 2026-10-15 | `d87ea4b` | **IR 路线 C/D/E/G 四阶段落地 + 修 s5b 误读**（本地提交，未推）：以「零件=回归夹具、架构=产品」定位。C=IR→build123d 生成器 `tools/ir2build.py`（往返体积差 0.0）；D=IR→FreeCAD PartDesign 真特征树 `tools/ir2partdesign.py`（lbracket 9 特征 diff 0.0 + Spreadsheet 表达式绑参）；E=FreeCAD→IR 回读 `tools/partdesign_readback.py`（参数联动实证 + 圆柱面翻几何谓词）；G=2D↔3D 语义锚点（3 零件 `ir_anchors.json` + `lib/drawing_fc.py::add_anchor_dim` 谓词找边绑边 + `tools/anchor_verify.py` 存在性/指对性双校核，12 锚点全 PASS 证通用架构能力；顺带修 D8_wall 静默跳过）。修 `steps/s5b_dimchain.py` 与 s6b 同源误读 bug。闭环：lbracket/gasket pass，bracket/ybracket manual（夹具自身 s5b 尺寸链问题）。guard 9/13 全过。 |
| 2026-10-15 | `4de98f2` … `ae10129`（8 个） | **阶段 0 + 阶段 1（解耦）**（随本次推送一起上传）：① 接口演进纪律（MSG.md §〇）+ `tools/arch_impact.py --strict` 硬检查；② `a2af6b3` 几何接 IR + 标注清单数据化；③ `2fc494b` 轮廓尺寸全部迁到绑边标注；④ `cc5de1c` 孔心距也绑上（圆心在投影几何里本就是 Vertex）；⑤ `ae10129` 闭环加「交付 PDF 图面文字」校验（`lib/pdf_marks.py`，堵住遗留 #2 的硬编码检测缺口）。 |
| 2026-10-15 | `77cb1e0` | **阶段 1 验收通过**：三个共享步骤 `steps/s1_build.py`（IR 驱动建模）/ `s2_drawing.py`（数据驱动出图）/ `s6_compare.py`（ref_spec 驱动校验）加入 `SHARED_STEPS`；`tools/new_part.py` 一键生成纯数据零件；新增 `parts/acc_plate/`（**无 steps/、0 行 Python**）闭环 pass 作证据。**真剖视图**：`lib/drawing_fc.py` +45/-0 支持 `type=="section"`（DrawViewSection + DrawHatch），解决「内腔不可见挂不上标注」的旧短板，剖视成为数据选项。含产物刷新与 `docs/s1-IR化方案.md` 草案。 |
| 2026-10-15 | `c1cc32c` | **z2c 算子挖掘与转化实验区**（独立于主干）：`tools/z2c_fetch_ops.py`（hf-mirror 列投影抓 210 分片 → 42.7MB/100516 行，已 gitignore）、`tools/z2c_mine_ops.py`（三层挖掘，10 万零件 23 秒；全量榜与 430 样本榜一致 ⇒ 小样本可信；完备度 K=30→84%）、`验证报告/z2c_conv/`（`op_lib.py` 15 个可 dispatch 算子 + `verify_ops.py` 19 条独立几何验证全 PASS）、`验证报告/z2c_mined{,_full}/` 候选算子榜。**18 个算子全部只在实验区，0 个接入主干**。 |

### ⚠️ 本次推送的两个坑（记下来省下次）

1. **本机两把 SSH key，用错会报 `denied to deploy key`**：
   - `~/.ssh/id_ed25519` = **只读 deploy key** → push 报 `ERROR: Permission to cheng1123425/jianmo.git denied to deploy key`（exit 128）；
   - `~/.ssh/id_ed25519_jianmo` = **可写**（已配在 `core.sshCommand`）→ 用 `git push origin HEAD:refs/heads/<分支>` 即走它。公钥指纹见 `.pub`。
   - 另：`ssh -T git@github.com` 偶发 `Connection reset ... port 22`，**但 git push 仍成功**（不必据此判定失败）。
2. **沙箱写 ref 依旧**：`git push <url> HEAD:refs/heads/feature/ir-feature-tree` 报成功、远程 tip 正确，但本地 `origin/*` 不落盘 → 需手写：
   ```bash
   mkdir -p .git/refs/remotes/origin
   printf <远程sha> > .git/refs/remotes/origin/sandbox-merge
   mkdir -p .git/refs/remotes/origin/feature
   printf <远程sha> > .git/refs/remotes/origin/feature/ir-feature-tree
   ```
   （注意：`origin/sandbox-merge` 要写**远程 tip `c0f4a2e`**，不是 HEAD —— 本地 `sandbox-merge` 实际承载的是 feature 分支的工作，写 HEAD 会掩盖这个事实。）
