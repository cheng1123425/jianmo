# -*- coding: utf-8 -*-
r"""s2_drawing —— STEP → 工程图（双耳直角支座，三视图 + 尺寸标注）

通用骨架（建文档 / 建视图 / 标注工具 / 收尾取值 / 导出）在 `lib/drawing_fc.py`，
本文件只声明这个零件自己的两样东西：

  ① `VIEW_SPECS` —— 建哪些视图（投影方向、XDirection、纸面位置、缩放）
  ② `place_marks(b, P)` —— 标注布置（标哪些尺寸、放在视图的什么位置、用什么语义名）

数值由 FreeCAD 在 `b.finalize()` 里从实体实算（`getRawValue()`），不是写死的。
`cbore_depth` 是内腔、标准三视图不可见（未开隐藏线），用「点距法」处理：
两点落在 Z=98 与 Z=120，值仍由 FreeCAD 实算 —— 保证是真尺寸线而非角落文字。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import boot, finish, ref_path, ref_data, exec_module   # noqa: E402
from lib.drawing_fc import DrawingBuilder, _y                     # noqa: E402

IN = boot("s2_drawing")
P = exec_module(ref_path(IN, "params"), "ybracket_params")
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")
TD = ref_data(IN, "template")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ================= ① 视图布局（本零件整体较大，比例取 0.8） =================
VIEW_SPECS = [
    dict(name="Front", dir=(0, -1, 0), xdir=None,      X=115, Y=185, scale=0.8),
    dict(name="Top",   dir=(0, 0, 1),  xdir=None,      X=115, Y=70,  scale=0.8),
    dict(name="Right", dir=(1, 0, 0),  xdir=(0, 1, 0), X=295, Y=185, scale=0.8),
]


# ================= ② 标注布置（零件特有） =================
def place_marks(b, P):
    vt, vf, vr = b.views["Top"], b.views["Front"], b.views["Right"]

    # ---- Front：总高 ----
    b.add_extent(vf, 1, _y(vf.X) - 8, _y(vf.Y) + 20, "height_z")

    # ---- Top：总长 / 总深 / 耳 R42 / 2-Ø42 / Ø54 / Ø32 ----
    b.add_extent(vt, 0, _y(vt.X) + 50, _y(vt.Y) - 15, "len_x")
    b.add_extent(vt, 1, _y(vt.X) - 8, _y(vt.Y) + 20, "depth_y")
    k42t, _ = b.first_circle_r(vt, P.EAR_R)
    if k42t is not None:
        b.add_rad(vt, P.EAR_R, _y(vt.X) - 45, _y(vt.Y) + 45, "ear_R")
    k21t, _ = b.first_circle_r(vt, P.EAR_R / 2.0)          # 耳孔半径 = 21（Ø42）
    if k21t is not None:
        b.add_dia(vt, P.EAR_R / 2.0, _y(vt.X) - 30, _y(vt.Y) - 35, "ear_hole")
    k27t, _ = b.first_circle_r(vt, P.CBORE_D / 2.0)        # 沉孔半径 = 27（Ø54）
    if k27t is not None:
        b.add_dia(vt, P.CBORE_D / 2.0, _y(vt.X) + 35, _y(vt.Y) + 35, "d_cbore")
    k16t, _ = b.first_circle_r(vt, P.CBORE_THRU_D / 2.0)   # 通孔半径 = 16（Ø32）
    if k16t is not None:
        b.add_dia(vt, P.CBORE_THRU_D / 2.0, _y(vt.X) + 35, _y(vt.Y) - 35, "d_thru")

    # ---- Right：外接水平 ----
    b.add_extent(vr, 0, _y(vr.X) + 50, _y(vr.Y) - 15, "depth_y")

    # ---- Top：耳孔心距（X 向 ±58 → 116）----
    b.add_distx(vt, -P.EAR_HOLE_P / 2.0, P.EAR_HOLE_P / 2.0,
                _y(vt.X), _y(vt.Y) - 55, "ear_pitch")

    # ---- Right：剖视 Y 向线性 ----
    b.add_disty(vr, 0.0, P.WALL_T_Y, _y(vr.X) + 70, _y(vr.Y) + 25, "wall_t")
    b.add_disty(vr, P.WALL_T_Y, P.ARM_L_Y, _y(vr.X) + 70, _y(vr.Y) - 25, "opening")

    # ---- Right：剖视 Z 向线性 ----
    b.add_disty(vr, 0.0, P.BASE_H_Z, _y(vr.X) - 70, _y(vr.Y) - 25, "base_h")
    b.add_disty(vr, P.BODY_H_Z - P.ARM_T_Z, P.BODY_H_Z,
                _y(vr.X) - 70, _y(vr.Y) + 25, "arm_t")
    # cbore_depth 是内腔 → 用「点距法」：两点落在 Z=98 与 Z=120，值由 FreeCAD 实算
    b.add_disty(vr, P.BODY_H_Z - P.CBORE_T_Z, P.BODY_H_Z,
                _y(vr.X) - 70, _y(vr.Y), "cbore_depth")


# ================= 主流程（通用） =================
b = DrawingBuilder("YBracket", STEP, P.TAG, TD, VIEW_SPECS)
place_marks(b, P)
b.finalize()
jf, fc, data = b.export(OUT_DIR, P.TAG)

finish([("drawing_json", jf), ("fcstd", fc)], {
    "views": [v["name"] for v in data["views"]],
    "n_edges": sum(len(v["edges"]) for v in data["views"]),
    "n_circles": sum(len(v["circles"]) for v in data["views"]),
    "n_dims": len(data["dims"]),
    "dim_values": {d["label"]: d["value"] for d in data["dims"]},
})
