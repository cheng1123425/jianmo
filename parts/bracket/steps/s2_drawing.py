# -*- coding: utf-8 -*-
r"""s2_drawing —— STEP → 工程图（铰链支座，三视图 + 尺寸标注）

通用骨架（建文档 / 建视图 / 标注工具 / 收尾取值 / 导出）在 `lib/drawing_fc.py`，
本文件只声明这个零件自己的两样东西：

  ① `VIEW_SPECS` —— 建哪些视图（投影方向、XDirection、纸面位置、缩放）
  ② `place_marks(b, P)` —— 标注布置（标哪些尺寸、放在视图的什么位置、用什么语义名）

标注**引用投影边**（`References2D`，getVisibleEdges 的 0-based 下标）或用两点距离，
数值由 FreeCAD 在 `b.finalize()` 里从实体实算（`getRawValue()`），不是写死的。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import boot, finish, ref_path, ref_data, exec_module   # noqa: E402
from lib.drawing_fc import DrawingBuilder, _y                     # noqa: E402

IN = boot("s2_drawing")
P = exec_module(ref_path(IN, "params"), "bracket_params")
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")
TD = ref_data(IN, "template")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ================= ① 视图布局 =================
# dir = 投影方向；xdir = XDirection（Right 视图需要指定，否则默认方向会转错）
VIEW_SPECS = [
    dict(name="Top",   dir=(0, 0, 1),  xdir=None,    X=34,  Y=45,  scale=2.0),
    dict(name="Front", dir=(0, -1, 0), xdir=None,    X=34,  Y=172, scale=2.0),
    dict(name="Right", dir=(1, 0, 0),  xdir=(0, 1, 0), X=214, Y=172, scale=2.0),
]


# ================= ② 标注布置（零件特有） =================
def _load_anchors():
    """G 阶段：读语义锚点（正向标注）。没有就返回 None → 退回原硬编码。"""
    path = os.path.normpath(os.path.join(os.path.dirname(HERE), "ir_anchors.json"))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("anchors") or None


# 语义名 = label（与 dims_spec.DIMS 的 label 一致，供 s4_table / s6_compare 比对）
def place_marks(b, P):
    vf, vr, vt = b.views["Front"], b.views["Right"], b.views["Top"]

    # ---- G 阶段：锚点驱动的标注（谓词找边 + References2D 绑边）----
    anchors = _load_anchors()
    if anchors:
        APOS = {
            "L":  (_y(vf.X) + 50, _y(vf.Y) - 25),   # Front 整体长
            "D9": (_y(vt.X) + 35, _y(vt.Y) + 10),   # Top 底板孔径
            "P9": (_y(vt.X) + 50, _y(vt.Y) - 10),   # Top 两孔心距
        }
        for a in anchors:
            lbl = a.get("label")
            if lbl in APOS:
                b.add_anchor_dim(a, *APOS[lbl])
        covered = set(APOS)
    else:
        covered = set()

    # ---- 以下为未纳入锚点的其余标注（保持原实现）----
    # ---- Front ----
    # 2026-10-15 迁到绑边（遗留 §1.4 第②步）：传两条**边**而不是两个点，
    # 值由 FreeCAD 从投影边实测。find_vline / find_hline 找不到边会明确报错，
    # 不会静默出错误值。
    # ——不迁的：下面 P9（两 φ9 **孔心**距，圆心不是边，绑不了）
    # 28（两臂外宽 = ARM_OUT_C_X × 2）→ 两条臂**外侧面**（竖直边）
    b.model_dim(vf, -P.ARM_OUT_C_X, P.ARM_OUT_C_X, "X",
                _y(vf.X) + 50, _y(vf.Y) + 5, "arm_outer")
    # 16（内距 = ARM_GAP_X）→ 两条臂**内侧面**（竖直边）
    b.model_dim(vf, -P.ARM_IN_C_X, P.ARM_IN_C_X, "X",
                _y(vf.X) + 50, _y(vf.Y) + 20, "arm_inner")
    # 8（底板厚）→ 底板上表面 / 下表面两条水平边
    b.model_dim(vf, 0, P.BASE_T_Z, "Z", _y(vf.X) - 5, _y(vf.Y) + 15, "T_base")
    # 62（底板总长）—— 已由锚点生成则跳过
    if "L" not in covered:
        b.add_extent(vf, 0, _y(vf.X) + 50, _y(vf.Y) - 25, "L")
    # 45（底板 2-φ9 孔心距）—— 已由锚点生成则跳过
    # 2026-10-15：原来是 `add_distx` 传两个死坐标点（值算出来），
    # 现改为**绑圆心的投影顶点**（值由 FreeCAD 从投影几何实测）——
    #   圆心在TechDraw 投影几何里本身就是 Vertex，绑它就能随 3D 跟随。
    if "P9" not in covered:
        b.distx_by_centers(vf, P.BASE_HOLE_D / 2, _y(vf.X) + 50, _y(vf.Y) - 10, "P9")
    # 2-φ6 / 2-φ3（Front 视图里这两个孔是圆）—— 找不到对应半径就跳过，不报错
    k6, _ = b.first_circle_r(vf, P.ARM_CBORE_D / 2)
    if k6 is not None:
        b.add_dia(vf, P.ARM_CBORE_D / 2, _y(vf.X) - 25, _y(vf.Y) - 30, "dia_cbore")
    k3, _ = b.first_circle_r(vf, P.ARM_THRU_D / 2)
    if k3 is not None:
        b.add_dia(vf, P.ARM_THRU_D / 2, _y(vf.X) + 25, _y(vf.Y) + 30, "dia_thru")

    # ---- Right ----
    b.model_dim(vr, 0, P.HEAD_C_Z, "Z", _y(vr.X) - 5, _y(vr.Y) + 5, "head_h")
    b.model_dim(vr, 0, P.ARM_END_C_Z, "Z", _y(vr.X) - 5, _y(vr.Y) - 5, "arm_h")
    # 36（臂水平总长 = END_Y − HEAD_Y）→ 圆头顶端切点所在竖直边 ↔ 臂端面
    b.model_dim(vr, P.HEAD_C_Y, P.ARM_END_C_Y, "Y",
                _y(vr.X) + 50, _y(vr.Y) - 8, "arm_len")
    # 46（侧视外接；用 extent 取更稳）
    b.add_extent(vr, 0, _y(vr.X) + 50, _y(vr.Y) - 25, "W")
    b.add_rad(vr, P.HEAD_R, _y(vr.X) - 50, _y(vr.Y) + 5, "R_head")
    b.add_dia(vr, P.PIN_HOLE_D / 2, _y(vr.X) + 30, _y(vr.Y) - 30, "dia_pin")

    # ---- Top ----
    if "D9" not in covered:
        b.add_dia(vt, P.BASE_HOLE_D / 2, _y(vt.X) + 35, _y(vt.Y) + 10, "D9")


# ================= 主流程（通用） =================
b = DrawingBuilder("Bracket", STEP, P.TAG, TD, VIEW_SPECS)
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
