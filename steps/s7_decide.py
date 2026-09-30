# -*- coding: utf-8 -*-
r"""s7_decide —— 差异清单 → 判定 + 修正建议（只决策，不动任何文件）

入参 refs: params（用于过滤「与当前值相同」的无效建议）
入参 data: s6 的 issues
产出 data: verdict(pass|fix|manual) / fixes / diagnosis / reason
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path, ref_data, exec_module    # noqa: E402


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "gasket_params")
    D = ref_data(in_msg)
    iss = D.get("issues", [])
    n_geom, n_mark = D.get("n_geom", 0), D.get("n_mark", 0)

    if not iss:
        return [], {"verdict": "pass", "fixes": {}, "diagnosis": "",
                    "reason": "几何与标注全部相符"}

    # 汇总建议；过滤掉「与当前值相同」的 no-op
    fixes = {}
    for x in iss:
        if x.get("action"):
            k, v = x["action"]
            v = round(float(v), 4)
            if abs(getattr(P, k) - v) > 1e-9:
                fixes[k] = v

    if n_geom:
        diagnosis = "三维画错（投影轮廓与图纸不符；标注偏差会随之消失）"
        reason = "三维形状不对 → 改 params.py 后重出"
        verdict = "fix" if fixes else "manual"
    elif n_mark:
        diagnosis = "二维标注错（形状对，标注没跟上）"
        reason = "形状没问题，是标注层的事 → 需人工检查边引用"
        verdict = "manual"
    else:
        diagnosis, reason, verdict = "", "未知差异", "manual"

    if not fixes and verdict == "fix":
        verdict, reason = "manual", "差异存在但推不出参数级建议"

    return [], {"verdict": verdict, "fixes": fixes, "diagnosis": diagnosis,
                "reason": reason, "n_geom": n_geom, "n_mark": n_mark,
                "items": [{"kind": x["kind"], "name": x["name"],
                           "base": x["base"], "cur": x["cur"]} for x in iss]}


if __name__ == "__main__":
    run_stage("s7_decide", handler)
