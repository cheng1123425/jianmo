# -*- coding: utf-8 -*-
r"""s1_build（共享层 · IR 驱动）—— 三维建模 → STEP / STL

**它让「新增零件不写 Python」成立**：零件没有自带 `steps/s1_build.py` 时，
本步骤读零件的 `ir.json`，用 `tools/ir2build.py` 生成 build123d 脚本并执行。

    ir.json ──[tools/ir2build.py]──▶ build123d 脚本 ──[exec]──▶ STEP/STL

**回落规则**（`pipe.py::script_of`）：零件自带 `steps/s1_build.py` → 用自带的
（老零件/逃生口）；没自带 → 落到本共享实现（纯数据零件）。

**为什么安全**：本步骤**只读数据**（`params.py` + `ir.json`），不写零件目录；
`guard.py` 的隔离检查针对 `steps/`（本文件在 `SHARED_STEPS` 白名单内）。

入参消息  refs: params；data: out_dir
产出      model_step / model_stl
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module            # noqa: E402
from build123d import import_step, export_stl                           # noqa: E402


def _part_dir():
    """零件目录：pipe.py 通过 MPIPE_HERE 传入（msgio.PATH_BASE 同源）。"""
    return os.environ.get("MPIPE_HERE") or os.getcwd()


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    out_dir = ref_data(in_msg, "out_dir")
    part_dir = os.path.abspath(_part_dir())

    ir_path = os.path.join(part_dir, "ir.json")
    if not os.path.exists(ir_path):
        raise SystemExit(
            "s1_build（共享 · IR 驱动）：零件 %s 既没有自带 steps/s1_build.py，"
            "也没有 ir.json。\n"
            "  纯数据零件必须提供 ir.json（特征图）；"
            "或用 tools/new_part.py 生成骨架。" % part_dir)

    import ir2build                                                    # noqa: E402

    with open(ir_path, encoding="utf-8") as f:
        ir = json.load(f)
    part_name = os.path.basename(part_dir)
    ns = ir2build._resolver_ns(P)
    code = ir2build.generate(ir, part_name, ns)

    os.makedirs(out_dir, exist_ok=True)
    step = os.path.join(out_dir, P.TAG + ".step")
    stl = os.path.join(out_dir, P.TAG + ".stl")

    # 生成脚本以 IR2B_STEP 环境变量指定输出路径，然后就地执行。
    os.environ["IR2B_STEP"] = step
    g = {"__name__": "__ir2b__", "__file__": ir_path}
    exec(compile(code, "<ir2build:%s>" % part_name, "exec"), g)

    if not os.path.exists(step):
        raise SystemExit("s1_build（IR 驱动）：生成的脚本没有产出 %s" % step)

    shape = import_step(step)
    export_stl(shape, stl)
    bb = shape.bounding_box()
    return [("model_step", step), ("model_stl", stl)], {
        "bounding_box": [round(bb.max.X - bb.min.X, 2),
                         round(bb.max.Y - bb.min.Y, 2),
                         round(bb.max.Z - bb.min.Z, 2)],
        "volume": round(shape.volume, 1),
        "solids": len(shape.solids()),
        "bbox_min": [round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)],
        "bbox_max": [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)],
        "source": "ir.json（IR 驱动）",
    }


if __name__ == "__main__":
    run_stage("s1_build", handler)
