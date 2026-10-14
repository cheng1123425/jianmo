# -*- coding: utf-8 -*-
r"""s7_decide —— 差异清单 → 判定 + 修正建议（只决策，不动任何文件）

入参 refs: params（用于过滤「与当前值相同」的无效建议）
入参 data: s6_compare 的 issues（几何/标注）+ s5b_dimchain / s6b_projection
           两个隔离校验步的结论（dimchain / projection 命名空间）
产出 data: verdict(pass|fix|manual) / fixes / diagnosis / reason

三路校验的责任分级（判定顺序）：
  1. s6b_projection 有 error → 图纸投影关系违规（图画错了）→ manual
  2. s5b_dimchain 有 error   → 图纸尺寸链不闭合（图纸/模型数值矛盾）→ manual
  3. s6_compare geom 有差    → 三维画错 → fix（改参数）
  4. s6_compare mark 有差    → 二维标注错 → manual
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

    # ---- 两个隔离校验步的结论（键名已命名空间隔离，不会互相覆盖）----
    dim = D.get("dimchain") or {}
    proj = D.get("projection") or {}
    dim_iss = dim.get("issues") or []
    proj_iss = proj.get("issues") or []
    dim_err = [x for x in dim_iss if x.get("severity") == "error"]
    proj_err = [x for x in proj_iss if x.get("severity") == "error"]
    chain_fixes = (dim.get("fixes") or {}).get("pitch_from_chain") or []

    if not iss and not dim_iss and not proj_iss:
        return [], {"verdict": "pass", "fixes": {}, "diagnosis": "",
                    "reason": "几何与标注全部相符，图纸自洽且投影合规"}

    # 汇总建议；过滤掉「与当前值相同」的 no-op
    fixes = {}
    for x in iss:
        if x.get("action"):
            k, v = x["action"]
            v = round(float(v), 4)
            if abs(getattr(P, k) - v) > 1e-9:
                fixes[k] = v

    # ---- 责任分级：先图纸规范，再图纸自洽，最后才是模型精度 ----
    # suppress_autofix：图纸本身出错时禁止用参数级建议自动改（会改错对象）
    suppress_autofix = False
    if proj_err:
        diagnosis = "图纸投影关系违规（%d 项：%s）—— 图画错了，不一定是模型错" % (
            len(proj_err), "；".join(x.get("kind", "?") for x in proj_err[:3]))
        reason = ("长对正/高平齐/宽相等/视图齐全是图纸语言；先修投影关系，"
                  "再谈参数（已跳过参数级建议，避免改错对象）")
        verdict, suppress_autofix = "manual", True
    elif dim_err:
        diagnosis = "图纸尺寸链不闭合（%d 项：%s）—— 图纸数值或模型数值装不进投影" % (
            len(dim_err), "；".join(x.get("kind", "?") for x in dim_err[:3]))
        reason = "Σ各段与封闭环对不上；需人工核对是图纸错标还是参数错（不自动改参数）"
        verdict, suppress_autofix = "manual", True
    elif n_geom:
        diagnosis = "三维画错（投影轮廓与图纸不符；标注偏差会随之消失）"
        reason = "三维形状不对 → 改 params.py 后重出"
        verdict = "fix" if fixes else "manual"
    elif n_mark:
        diagnosis = "二维标注错（形状对，标注没跟上）"
        reason = "形状没问题，是标注层的事 → 需人工检查边引用"
        verdict = "manual"
    else:
        diagnosis, reason, verdict = "", "未知差异", "manual"

    # 兜底：s0_plan 的「参数预检」能直接反解恒等映射（标注 == 参数本身）的差异。
    # 投影比对推不出建议时（s6 的 action 为空），用 s0 的建议让闭环继续跑。
    # 图纸本身出错（投影/尺寸链 error）时禁用 —— 那是改图纸，不是改参数。
    s0_fix = D.get("s0_fix") or {}
    if not fixes and s0_fix and not suppress_autofix:
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
                "n_dimchain_issues": len(dim_iss),
                "n_projection_issues": len(proj_iss),
                "chain_fixes": chain_fixes,
                "items": [{"kind": x["kind"], "name": x["name"],
                           "base": x["base"], "cur": x["cur"]} for x in iss]}


if __name__ == "__main__":
    run_stage("s7_decide", handler)
