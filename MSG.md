# 消息协议 `mpipe/1`

> 目的：把整条流水线（建模 → 出图 → 渲染 → 表格）和闭环校核（采集 → 比对 → 判定 → 修正）
> 拆成**互相隔离的独立进程**，步骤之间**只允许通过消息文件传递数据**。

---

## 一、为什么

改造前的耦合（都是隐式传递，出了问题不好追）：

| 位置 | 改造前 | 问题 |
|---|---|---|
| `make_all.py` | subprocess 串 4 段，靠硬编码路径 + 裸文件名交接 | 谁写谁读全靠约定 |
| `check_loop.py` | `collect/compare/apply_fix` 是同进程函数，直接传 Python 对象 | 隐式共享状态 |
| `apply_fix` | 直接改写 `params.py` | 校核步骤越界改了建模步骤的输入 |
| 各脚本 | `import params` / `import ref_spec` | 共享内存式耦合 |
| 校核 | 直接读 `_td_data.json` | 直读上游内部产物，不知道它的格式契约 |

改造后：**每个步骤是一个独立进程，只知道自己收到的那份消息。**

---

## 二、消息文件

每步一个**入参消息**、一个**结果消息**，固定放在 `_msg/`：

```
_msg/
  ref.input.json          ← 外部输入基线（由驱动器从 ref_spec.py 序列化）
  s1_build.in.json        ← 驱动器投递给 s1 的入参
  s1_build.out.json       ← s1 产出的结果
  s2_drawing.in.json
  s2_drawing.out.json
  ...
```

### 格式

```json
{
  "protocol": "mpipe/1",
  "stage": "s1_build",
  "seq": 1,
  "status": "ok",
  "started": "2026-09-30T08:50:00",
  "finished": "2026-09-30T08:50:05",
  "in": {
    "refs": [
      {"role": "params", "path": "params.py", "sha256": "3f2a…", "bytes": 1234}
    ],
    "data": {}
  },
  "out": {
    "refs": [
      {"role": "model_step", "path": "models/gasket_fixture.step",
       "sha256": "9c1b…", "bytes": 63044}
    ],
    "data": {"volume": 5409140.1, "bbox": [550, 300, 100]}
  },
  "error": null
}
```

| 字段 | 含义 |
|---|---|
| `protocol` | 固定 `mpipe/1`，版本不符即拒绝 |
| `stage` / `seq` | 谁、第几轮 |
| `status` | `ok` / `fail` |
| `in.refs` | **本步被允许读的全部文件**，带 sha256 |
| `in.data` | 上一步传来的结构化结果（小数据直接内联） |
| `out.refs` | 本步产出的文件，带 sha256 与大小 |
| `out.data` | 本步的结构化结果 |
| `error` | 失败时的堆栈 |

---

## 三、规则（允许 / 禁止）

### 每个步骤**只允许**

- 读自己的 `_msg/<stage>.in.json`
- 读 `in.refs` 里**列出的**文件（读前校验 sha256）
- 写自己的 `out.refs` 里声明的产物
- 写 `_msg/<stage>.out.json`

### **禁止**

- ❌ `import` 其他步骤的模块
- ❌ 凭常量路径读**别的步骤的产物**（如 s3 直接读 `_td_data.json`）
- ❌ 写 `params.py`（**只有 `s8_apply` 允许**）
- ❌ 在 `out.refs` 之外写文件

> 这些不是"约定"，是**机制强制**：`guard.py` 会静态扫描 `steps/`，
> 发现违例直接非零退出，驱动器拒绝运行。

### 外部输入 vs 步骤产物

| 类别 | 例子 | 说明 |
|---|---|---|
| **外部输入**（人给的） | `params.py`、`ref_spec.py`、`dims_spec.py` | 由驱动器在 `in.refs` 里声明，步骤按声明读 |
| **步骤产物** | `models/*.step`、`_drawing.json` | 只能由产出它的步骤写；别的步骤要读，必须在 `in.refs` 里被声明 |

---

## 四、拓扑

```
   params.py + dims_spec.py + ref_spec.py + notes/plan_src.md
                        │
                   ┌────▼─────┐
                   │ s0_plan  │──> notes/plan.md   ← 每轮循环前的读图/方案/失误定位
                   └────┬─────┘
                        │
                    params.py  (人的输入)
                        │
                   ┌────▼────┐
                   │ s1_build │──> models/*.step / .stl
                   └────┬─────┘
                        │
                   ┌────▼───────┐
                   │ s2_drawing │──> _drawing.json + *.FCStd
                   └────┬────────┘
              ┌─────────┴─────────┐
        ┌─────▼─────┐       ┌─────▼──────┐
        │ s3_render │       │ s4_table   │   (+ dims_spec.py)
        └─────┬─────┘       └─────┬──────┘
              │                   │
      drawing.pdf/.png     dims_table.*

  — — — — — — — 闭环（可选）— — — — — — —
        _drawing.json
              │
        ┌─────▼──────┐
        │ s5_collect │──> 几何摘要
        └─────┬──────┘
              │  + ref.input.json（原图基准）
        ┌─────▼──────┐
        │ s6_compare │──> 差异清单
        └─────┬──────┘
              │
        ┌─────▼──────┐
        │ s7_decide  │──> 判定 + 修正建议
        └─────┬──────┘
              │  (有建议且 --auto)
        ┌─────▼──────┐
        │ s8_apply   │──> 改写 params.py  ← 唯一被允许改参数的步骤
        └─────┬──────┘
              │  回到 s1（下一轮）
              └──────────►

        ┌────────────┐
        │ s9_record  │──> notes/model_notes.md + notes/errors.md
        └────────────┘   每轮结束记录：本轮怎么判的、改了什么、错在哪
```

### s0_plan / s9_record：思考与记忆

闭环最容易出现的浪费是「不看图纸就改参数」。所以链的两端各加了一步：

| 步骤 | 时机 | 读什么 | 产出 |
|---|---|---|---|
| `s0_plan` | 每轮循环**最前面** | `ref_spec`（图上标的数）+ `dims_spec`（标注↔实体关系）+ `notes/plan_src.md`（人工维护的方案源）+ `notes/errors.md`（历史错误）+ 上一轮 `s7` 的判定 | `notes/plan.md`：读图结论、构造顺序、**参数预检**、**上一轮差异定位到哪个建模阶段**、历史错误提示 |
| `s9_record` | 每轮**结束**（无论成败） | 本轮 `s7` 判定 + `dims_spec` 分类 + `s0` 的方案 | 追加 `notes/model_notes.md`（时间线）与 `notes/errors.md`（按分类去重累积，记次数） |

`s0` 定位失误的办法：把差异项的名字按「标注 label → 分类 cat → 构造阶段」三级映射，
输出形如「阶段 3『圆头铰接端』← R_head 基准 10 / 当前 13」。
所以 `notes/plan_src.md` 里的 `cat=` 必须和 `dims_spec.py` 的 `cat` 对得上。

`s0` 还能在**参数层面**直接预检：对每个「标注 == 参数本身」的恒等关系，
把关系式算出来的值和图上标的数比对，不符就给出可直接应用的建议值；
`s7` 在投影比对推不出建议时用它兜底，让闭环还能继续跑。

---

## 五、怎么跑

```bash
# 全链（s0→s1→s2→s3→s4），默认跑根零件（垫片）
python pipe.py

# 跑别的零件
python pipe.py --part parts/bracket

# 全链 + 闭环自动迭代（默认上限 6 轮）
python pipe.py --part parts/bracket --loop --auto

# 闭环只检查不重跑、不改参数
python pipe.py --loop

# 只跑某一段（调试用）
python pipe.py --part parts/bracket --only s2_drawing

# 忽略指纹缓存，强制重跑（改了环境或想确认真实耗时）
python pipe.py --no-cache

# 隔离检查（改完步骤脚本后先跑这个）
python guard.py --steps parts/bracket/steps --steps steps
```

**看消息**：`_msg/<stage>.in.json` / `.out.json` 是纯文本，
出问题直接打开看"这一步当时收到了什么、产出了什么"。

**看思路**：`notes/plan.md`（本轮方案）、`notes/model_notes.md`（每轮结论）、
`notes/errors.md`（错误库）是人读的，也是下一轮 `s0` 的输入。

### 两个省时间的机制（默认开启）

1. **指纹缓存**：入参 sha256 + 入参 data + 步骤脚本 sha256 全都没变 → 直接复用上次
   结果，不起进程。改了某一步的脚本，只有它和它的下游会重跑。
   缓存索引在 `_msg/.cache.json`，用 `--no-cache` 跳过。
2. **延迟出图**：闭环中间轮只跑 `s1+s2`（几何相关），`s3_render/s4_table`
   等最后一轮结束再补跑一次 —— 每轮省下约 3 秒的渲染与制表开销。

跑完会打印**耗时排行**，一眼看出瓶颈在哪一步。

---

## 六、加一个新步骤

1. 在 `steps/` 建 `sN_xxx.py`，写一个 `handler(in_msg)`：

   ```python
   import os, sys
   sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
   from msgio import run_stage, ref_path

   def handler(in_msg):
       src = ref_path(in_msg, "model_step")      # 按消息声明读入参
       ...                                        # 你的逻辑
       return [("result", out_path)], {"k": v}    # (out.refs, out.data)

   if __name__ == "__main__":
       run_stage("sN_xxx", handler)
   ```

2. 在 `pipe.py` 的 `TOPO` 里加一行（声明输入 role → 输出 role）。
3. 跑 `python guard.py` 确认没有违例。
