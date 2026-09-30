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
```

---

## 五、怎么跑

```bash
# 全链（4 段）
python pipe.py

# 全链 + 闭环自动迭代（默认上限 6 轮）
python pipe.py --loop --auto

# 闭环只检查不重跑、不改参数
python pipe.py --loop --no-run

# 只跑某一段（调试用）
python pipe.py --only s2_drawing

# 隔离检查（改完步骤脚本后先跑这个）
python guard.py
```

**看消息**：`_msg/<stage>.in.json` / `.out.json` 是纯文本，
出问题直接打开看"这一步当时收到了什么、产出了什么"。

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
