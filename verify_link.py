# -*- coding: utf-8 -*-
r"""
联动验证：改 params.py 里的参数 → 跑一次 make_all.py → 看 PDF 的尺寸是否同步
特别验证：改「孔直径」时「孔心距」应保持不变（两者是独立尺寸）
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(HERE, "params.py")
PY = r"D:\3d\build123d\.venv\Scripts\python.exe"


def run():
    r = subprocess.run([PY, os.path.join(HERE, "make_all.py")],
                       capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode != 0:
        print(r.stdout.decode("utf-8", "replace")[-1500:])
        raise SystemExit("make_all 失败")


def snap():
    d = json.load(open(os.path.join(HERE, "_td_data.json"), encoding="utf-8"))
    out = {}
    for x in d["dims"]:
        out[x["label"]] = x["value"]
    return out


def patch(txt, key, val):
    new, n = re.subn(r"^(%s\s*=\s*)[\d.]+" % key, lambda m: m.group(1) + repr(float(val)),
                     txt, flags=re.M)
    assert n == 1, "参数 %s 未找到/多处匹配" % key
    return new


ORIG = open(PARAMS, encoding="utf-8").read()

SCEN = [
    ("\u57fa\u51c6 (原始参数)",              {}),
    ("\u4fa7\u5b54 \u03c675 \u2192 \u03c6100", {"D_HOLE_SIDE": 100.0}),
    ("\u5b54\u5fc3\u8ddd 200 \u2192 220",     {"D_SIDE": 220.0}),
    ("\u4e2d\u5fc3\u51f8\u53f0 \u03c6200 \u2192 \u03c6240", {"R_BOSS": 120.0}),
    ("\u4fa7\u51f8\u53f0 \u03c6150 \u2192 \u03c6180", {"R_SIDE": 90.0}),
]

rows = []
try:
    for name, ch in SCEN:
        txt = ORIG
        for k, v in ch.items():
            txt = patch(txt, k, v)
        open(PARAMS, "w", encoding="utf-8").write(txt)
        run()
        rows.append((name, snap()))
        print("done:", name)
finally:
    open(PARAMS, "w", encoding="utf-8").write(ORIG)
    run()

# ---------- 报表 ----------
labels = [x["label"] for x in json.load(open(os.path.join(HERE, "_td_data.json"), encoding="utf-8"))["dims"]]
w = max(len(n) for n, _ in rows) + 2
print("")
print("=" * (w + 14 * len(labels)))
print("%-*s" % (w, "场景") + "".join("%12s" % l for l in labels))
print("-" * (w + 14 * len(labels)))
for name, vals in rows:
    print("%-*s" % (w, name) + "".join("%12.1f" % vals.get(l, float("nan")) for l in labels))
