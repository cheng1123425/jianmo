# -*- coding: utf-8 -*-
r"""s2_drawing —— STEP → 工程图（L 形支座，三视图 + 尺寸标注）

通用骨架（建文档 / 建视图 / 标注工具 / 收尾取值 / 导出）在 `lib/drawing_fc.py`，
本文件只声明这个零件自己的两样东西：

  ① `VIEW_SPECS` —— 建哪些视图（投影方向、XDirection、纸面位置、缩放）
  ② `place_marks(b, P)` —— 标注布置（标哪些尺寸、放在视图的什么位置、用什么语义名）

数值由 FreeCAD 在 `b.finalize()` 里从实体实算（`getRawValue()`），不是写死的。
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
P = exec_module(ref_path(IN, "params"), "lbracket_params")
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")
TD = ref_data(IN, "template")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ================= ① 视图布局 =================
VIEW_SPECS = [
    dict(name="Top",   dir=(0, 0, 1),  xdir=None,      X=34,  Y=45,  scale=2.0),
    dict(name="Front", dir=(0, -1, 0), xdir=None,      X=34,  Y=172, scale=2.0),
    dict(name="Right", dir=(1, 0, 0),  xdir=(0, 1, 0), X=214, Y=172, scale=2.0),
]


# ================= ② 标注布置（零件特有） =================
def place_marks(b, P):
    vt, vf, vr = b.views["Top"], b.views["Front"], b.views["Right"]

    # ---- Top：L（横）/ W（竖）/ 底板 φ8 ----
    b.add_extent(vt, 0, _y(vt.X) + 50, _y(vt.Y) + 5, "L")
    b.add_extent(vt, 1, _y(vt.X) - 5, _y(vt.Y) + 15, "W")
    k8t, _ = b.first_circle_r(vt, P.HOLE_D / 2.0)
    if k8t is not None:
        b.add_dia(vt, P.HOLE_D / 2.0, _y(vt.X) - 25, _y(vt.Y) - 30, "D8_base")

    # ---- Front：H_total（总高）/ 立板 φ8（两孔投影重合为 1 个圆）----
    b.add_extent(vf, 1, _y(vf.X) - 5, _y(vf.Y) + 15, "H_total")
    k8f, _ = b.first_circle_r(vf, P.HOLE_D / 2.0)
    if k8f is not None:
        b.add_dia(vf, P.HOLE_D / 2.0, _y(vf.X) + 25, _y(vf.Y) + 30, "D8_wall")

    # ---- Right：pitch（立板两 φ8 在 Right 视图里的 view2d-X 间距 = 世界 Y 心距）----
    rc = [k for k, e in enumerate(b.visible(vr))
          if "Circle" in e.Curve.__class__.__name__
          and abs(_y(e.Curve.Radius) - P.HOLE_D / 2.0) < 0.3]
    if len(rc) >= 2:
        c1 = b.visible(vr)[rc[0]].Curve
        c2 = b.visible(vr)[rc[1]].Curve
        b.add_distx(vr, _y(c1.Center.x), _y(c2.Center.x),
                    _y(vr.X) + 50, _y(vr.Y) - 8, "pitch")


# ================= 主流程（通用） =================
b = DrawingBuilder("LBracket", STEP, P.TAG, TD, VIEW_SPECS)
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
