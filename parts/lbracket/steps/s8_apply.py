# -*- coding: utf-8 -*-
r"""s8_apply —— 把修正建议写回 params.py（L 形支座）

注意：本步是**唯一**被允许修改 params.py 的步骤；pipe.py 在运行后会校验
params.py 的 sha256，若非本步改动会直接报错（隔离违例）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    ppath = ref_path(in_msg, "params")
    fixes = ref_data(in_msg, "fixes") or {}
    if not fixes:
        raise RuntimeError("没有可应用的修正（fixes 为空）")

    mod = os.path.basename(ppath)[:-3]
    P = exec_module(ppath, mod)
    before = {}
    for k in fixes:
        try:
            before[k] = getattr(P, k)
        except AttributeError:
            raise RuntimeError("params.py 没有参数 %s" % k)

    txt = open(ppath, encoding="utf-8").read()
    applied = {}
    for k, v in fixes.items():
        lit = ("%.4f" % float(v)).rstrip("0").rstrip(".")
        txt, n = re.subn(r"^(%s\s*=\s*)[\d.+-]+" % re.escape(k),
                         lambda m: m.group(1) + lit, txt, flags=re.M)
        if n != 1:
            raise RuntimeError("参数 %s 在 params.py 里匹配到 %d 处" % (k, n))
        applied[k] = float(v)

    open(ppath, "w", encoding="utf-8").write(txt)
    print("       %s" % "  ".join("%s %s→%s" % (k, before[k], v) for k, v in applied.items()))

    return [("params", ppath)], {"applied": applied, "before": before}


if __name__ == "__main__":
    run_stage("s8_apply", handler)
