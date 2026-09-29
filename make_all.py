# -*- coding: utf-8 -*-
r"""
一键重出：改完 params.py，跑这一个脚本，全链路刷新
=====================================================
    三维模型 → STEP/STL → FreeCAD 工程图(FCStd) → PDF/PNG

用法:
    D:\3d\build123d\.venv\Scripts\python.exe make_all.py
"""
import os
import subprocess
import sys
import time

PY = r"D:\3d\build123d\.venv\Scripts\python.exe"
FC = "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/bin/freecadcmd.exe"
HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("1/4  三维建模 → STEP / STL",       [PY, os.path.join(HERE, "build_part.py")],     "@@"),
    ("2/4  FreeCAD 出图 → FCStd + 数据", [FC, os.path.join(HERE, "freecad_drawing.py")], "@@STAGE2_OK@@"),
    ("3/4  渲染 → PDF / PNG",            [PY, os.path.join(HERE, "render_pdf.py")],     "@@"),
    ("4/4  尺寸对照表 → md / PNG / PDF", [PY, os.path.join(HERE, "make_table.py")],     "@@"),
]

t0 = time.time()
for title, cmd, ok in STEPS:
    print("=" * 66)
    print(">>>", title)
    print("=" * 66)
    r = subprocess.run(cmd, capture_output=True,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    for line in out.splitlines():          # 只留关键行，滤掉 FreeCAD 的 Recompute 进度条
        s = line.strip()
        if s and ("[" in s or s.startswith("@@")):
            print("   ", s)
    if r.returncode != 0 or (ok != "@@" and ok not in out):
        print("!!! 失败，已中止：", title)
        print(out[-2000:])
        sys.exit(1)

print("=" * 66)
print("完成，用时 %.1f 秒" % (time.time() - t0))
print("  图纸    : %s" % os.path.join(HERE, "drawing.pdf"))
print("  图纸    : %s" % os.path.join(HERE, "drawing.png"))
print("  尺寸表  : %s" % os.path.join(HERE, "dims_table.pdf"))
print("  尺寸表  : %s" % os.path.join(HERE, "dims_table.md"))
print("  FCStd   : %s" % os.path.join(HERE, "gasket_fixture.FCStd"))
print("  STEP    : %s" % os.path.join(r"D:\3d\build123d", "gasket_fixture.step"))
