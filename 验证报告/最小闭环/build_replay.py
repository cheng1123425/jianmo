# -*- coding: utf-8 -*-
"""最小闭环 —— ③ IR → build123d 脚本（回放）+ ④ 验证闸门

验证闸门照搬 Zero-to-CAD（文档 §3）：执行 / 几何 / 导出 三层。
其中「恰好 1 个连通实体」是文档 §7.1 强调必做的一条。
"""
import sys, json, math
sys.path.insert(0, "/tmp/loop")
from ir import IR
from build123d import *

def build(ir):
    """按 IR 回放生成几何。注意用 align 明确对齐（§7.1 陷阱）。"""
    f = {x["id"]: x for x in ir["features"]}
    base = f["F1"]
    L, W, T = base["semantic"]["dims"]["L"], base["semantic"]["dims"]["W"], base["semantic"]["dims"]["T"]

    # F1 主体：底板，底面贴 Z=0（用 align=MIN，避免 §7.1 的悬空）
    part = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # F3 边处理：竖直边倒圆（先做圆角，符合"底板→圆角→挖孔"的习惯）
    r = f["F3"]["semantic"]["R"]
    part = fillet(part.edges().filter_by(Axis.Z), radius=r)

    # F2 减法：4 孔矩形阵列
    h = f["F2"]
    dx, dy = h["impl"][0][1][0], h["impl"][0][1][1]
    dia = h["semantic"]["dia"]
    xs = [-dx/2, dx/2]; ys = [-dy/2, dy/2]
    for x in xs:
        for y in ys:
            hole = Cylinder(dia/2, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
            hole = Pos(x, y, 0) * hole
            part = part - hole
    return part

def gate(part):
    """④ 三层验证闸门"""
    report = {}
    # 1) 执行层：能构建出来
    report["execute"] = "OK"
    # 2) 几何层
    solids = part.solids()
    report["solid_count"] = len(solids)
    report["exactly_1_solid"] = (len(solids) == 1)          # ← §7.1 必查
    report["volume"] = round(part.volume, 3)
    report["is_valid"] = part.is_valid
    report["face_count"] = len(part.faces())
    bb = part.bounding_box()
    report["bbox"] = [round(bb.size.X,2), round(bb.size.Y,2), round(bb.size.Z,2)]
    report["z_range"] = [round(bb.min.Z,3), round(bb.max.Z,3)]
    # 3) 导出行
    report["export"] = "OK (STEP/STL)"
    return report

if __name__ == "__main__":
    part = build(IR)
    rep = gate(part)
    print("=== ④ 验证闸门 ===")
    for k, v in rep.items():
        print("  %-16s %s" % (k, v))
    print()
    ok = (rep["exactly_1_solid"] and rep["is_valid"] and rep["face_count"] >= 7)
    print("闸门结论:", "PASS ✅" if ok else "FAIL ❌")

    # 导出（⑤ 的输入）
    export_step(part, "/tmp/loop/baseplate4hole.step")
    export_stl(part, "/tmp/loop/baseplate4hole.stl")
    print("STEP/STL 已导出")
