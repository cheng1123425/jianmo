# -*- coding: utf-8 -*-
r"""s7_decide —— 差异清单 → 判定 + 修正建议（铰链支座）"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "bracket_params")
    D = ref_data(in_msg)
    iss = D.get("issues", [])
    n_geom, n_mark = D.get("n_geom", 0), D.get("n_mark", 0)

    if not iss:
        return [], {"verdict": "pass", "fixes": {}, "diagnosis": "",
                    "reason": "几何与标注全部相符"}

    fixes = {}
    for x in iss:
        if x.get("action"):
            k, v = x["action"]
            v = round(float(v), 4)
            if abs(getattr(P, k, v) - v) > 1e-9:
                fixes[k] = v

    if n_geom:
        diagnosis = "三维画错（投影轮廓与图纸不符）"
        reason = "三维形状不对 → 改 params.py 后重出"
        verdict = "fix" if fixes else "manual"
    elif n_mark:
        diagnosis = "二维标注错"
        reason = "形状对、标注没跟上 → 查 s2_drawing.py 的边引用"
        verdict = "manual"
    else:
        diagnosis, reason, verdict = "", "未知差异", "manual"

    # 兜底：s0_plan 的「参数预检」能直接反解恒等映射（标注 == 参数本身）的差异
    s0_fix = D.get("s0_fix") or {}
    if not fixes and s0_fix:
        for k, v in s0_fix.items():
            v = round(float(v), 4)
            if abs(getattr(P, k, v) - v) > 1e-9:
                fixes[k] = v
        if fixes:
            verdict = "fix"
            diagnosis = "参数值与图上标注不一致（s0_plan 预检发现）"
            reason = "标注 ↔ 参数是恒等映射 → 直接按图上标注改参数"

    if not fixes and verdict == "fix":
        verdict, reason = "manual", "差异存在但推不出参数级建议"

    return [], {"verdict": verdict, "fixes": fixes, "diagnosis": diagnosis,
                "reason": reason, "n_geom": n_geom, "n_mark": n_mark,
                "items": [{"kind": x["kind"], "name": x["name"],
                           "base": x["base"], "cur": x["cur"]} for x in iss]}


if __name__ == "__main__":
    run_stage("s7_decide", handler)