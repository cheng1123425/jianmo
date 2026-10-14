# -*- coding: utf-8 -*-
r"""verify_loop_nogui.py —— 无 FreeCAD 环境下验证闭环段（s0_plan → s9_record）

**用途**：沙箱 / 没装 FreeCAD 的机器上，端到端验证闭环段的调度、数据合并与判定
（s5_collect / s5b_dimchain / s6_compare / s6b_projection / s7_decide / s9_record
全是 Python 步，不需要 CAD 内核）。建模段（s1/s2）与出图段（s3/s4）仍然需要
FreeCAD，本工具不碰它们。

**前提**：零件目录里已有 `_drawing.json`（s2_drawing 的产物）与
`notes/dwg_semantics.json`（s0b_dwgread 的产物）。二者由 `pipe.py --only` 单步
模式或此前完整跑批产生。

用法：
    python3 tools/verify_loop_nogui.py                 # 根零件（垫片）
    python3 tools/verify_loop_nogui.py parts/bracket   # 指定零件
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("MPIPE_PY", sys.executable)

import pipe  # noqa: E402


def main(argv):
    part = argv[1] if len(argv) > 1 else "."
    drv = pipe.Driver(part)
    p = drv.part

    dwg = os.path.join(p, "_drawing.json")
    sem = os.path.join(p, "notes", "dwg_semantics.json")
    missing = [f for f in (dwg, sem) if not os.path.exists(f)]
    if missing:
        print("缺少前置产物（先用 pipe.py --only 跑出它们，或在有 FreeCAD 的机器上跑完整链）：")
        for f in missing:
            print("   ", os.path.relpath(f, ROOT))
        return 2

    # 用真实产物预填 produced（等价于 s2_drawing / s0b_dwgread 已跑完）
    produced = {
        "s0b_dwgread": {"dwg_semantics": sem},
        "s2_drawing": {
            "drawing_json": dwg,
            "model_step": os.path.join(p, "models", os.path.basename(p) + ".step"),
            "fcstd": os.path.join(p, os.path.basename(p) + ".FCStd"),
        },
    }
    opt = dict(part=part, auto=False, loop=True, only=None, max_it=2,
               guard=False, cache=False, trace=False)

    print("=" * 70)
    print("零件：%s" % (os.path.relpath(p, ROOT) or "."))
    print("预填：_drawing.json + notes/dwg_semantics.json（真实产物）")
    print("=" * 70)
    outcome, it, deferred = drv.run_loop(1, opt, produced, cache=None)
    print("\n闭环结局：%s（%d 轮）" % (outcome, it))
    print("（manual = 图纸/投影有问题需人工；pass = 全相符；fix = 有参数级建议）")
    return 0 if outcome in ("pass", "manual") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
