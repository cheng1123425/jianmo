# -*- coding: utf-8 -*-
r"""s8_apply —— 把修正建议写回 params.py

**这是整条链里唯一被允许修改 params.py 的步骤**（guard.py 会强制这一点）。

入参 refs: params
入参 data: s7 的 fixes
产出 refs: params（改后的新版本，带新 sha256）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path, ref_data, exec_module    # noqa: E402


def handler(in_msg):
    ppath = ref_path(in_msg, "params")
    fixes = ref_data(in_msg, "fixes") or {}
    if not fixes:
        raise RuntimeError("没有可应用的修正（fixes 为空）——不该调用这一步")

    P = exec_module(ppath, "gasket_params")
    before = {k: getattr(P, k) for k in fixes}
    txt = open(ppath, encoding="utf-8").read()

    applied = {}
    for k, v in fixes.items():
        lit = ("%.4f" % float(v)).rstrip("0").rstrip(".")
        txt, n = re.subn(r"^(%s\s*=\s*)[\d.]+" % re.escape(k),
                         lambda m: m.group(1) + lit, txt, flags=re.M)
        if n != 1:
            raise RuntimeError("参数 %s 在 params.py 里匹配到 %d 处，拒绝修改" % (k, n))
        applied[k] = float(v)

    open(ppath, "w", encoding="utf-8").write(txt)
    print("       %s" % "  ".join("%s %s→%s" % (k, before[k], v) for k, v in applied.items()))

    return [("params", ppath)], {"applied": applied, "before": before}


if __name__ == "__main__":
    run_stage("s8_apply", handler)
