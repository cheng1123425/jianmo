# -*- coding: utf-8 -*-
r"""s0b_dwgread —— 输入层：从二维图纸读出几何 / 标注 / 接地关系

**这是整条流水线唯一读原图的步骤。** 后面所有步骤都只消费它产出的
dwg_semantics.json，谁也不再直接碰 drawing.png —— 语义只能来自图纸本身，
不能靠人事先告知（否则就成了"人告诉系统这是什么"）。

对应 HANDOFF §4.4 中间表示里的 `drawing` 字段（3D↔2D 的对应关系）。

隔离约定
--------
* 只通过消息通信：读 refs 里声明的 drawing_png，sha256 不符即报错
* 不 import params / ref_spec / dims_spec（那是人的输入，与本步无关）
* 不 import 其他 s*_ 步骤
* 不改 params.py（驱动器运行时强制，只有 s8_apply 能改）
* 产出只写自己的 out.json + 一个 json 文件

实现：**两条并行路线，按零件提供的输入自动择一**
  A. **矢量路线**（`drawing.pdf`）→ `tools/pdf_vector`
     原图是 CAD 打印的矢量 PDF 时走这条。坐标即物理尺寸、文字带 ToUnicode
     直接解码（**不用 OCR**）、AutoCAD 图层作为 PDF OCG 保留。
  B. **栅格路线**（`drawing.png`）→ `tools/dwg_parser`（Drawing-Recode 思路的传统 CV 复现）
     几何层：两级霍夫 + 圆周覆盖率验证 + 同心圆径向扫描
     标注层：连通域 + 字形几何分类 + tesseract OCR
     接地层：半径投票标定 + 引线追踪 + 圆角相切求解 + 外轮廓弧段
两条路的产出**同一契约**（本文件 _pick / _pick_pdf），所以下游 s0_plan /
s5b_dimchain **零改动**；同一零件同时给两份图时**优先矢量**。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))            # 项目根，为了 import msgio
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))   # dwg_parser / pdf_vector

from msgio import run_stage, ref_path, ref_data      # noqa: E402


def _pick_pdf(sem):
    """矢量路线的结果 → 消息里真正要用的字段（丢掉重几何，只留语义）。

    与 `_pick()` 同形；`mm_per_px` 的 "px" 在矢量路线里是 **PDF 点(pt)**。
    """
    return {
        "mm_per_px": sem["mm_per_px"],
        "scale_method": sem["scale_method"],
        "summary": sem["summary"],
        "circles": sem["circles"],
        "dims": sem["dims"],
        # 附加（下游可忽略）：图层分布 + 标定证据
        "layers": sem.get("layers", {}),
        "geometry_hint": {"n_lines": sem.get("summary", {}).get("n_lines"),
                          "n_texts": sem.get("summary", {}).get("n_texts")},
    }


def _pick(res):
    """把 parse() 的结果压成「后续步骤真正用得上的」语义，避免把 10 万点的
    原始投影灌进消息文件。"""
    mp = res.get("mm_per_px") or 0.0
    dims = []
    for g in res.get("grounded", []):
        a = g.get("annotation", {})
        t = g.get("target") or {}
        dims.append({
            "text": a.get("text"),
            "type": a.get("type"),
            "values": a.get("values"),
            "box_px": [round(float(v), 1) for v in (a.get("box_px") or [])],
            "center_px": [round(float(v), 1) for v in (a.get("center_px") or [])],
            "grounded": bool(t),
            "kind": t.get("kind"),
            "cx": t.get("cx"), "cy": t.get("cy"),
            "r_px": t.get("r_px"),
            "d_mm": t.get("d_mm"),
            "measured_mm": g.get("measured_mm"),
            "method": g.get("method"),
            "confidence": g.get("confidence"),
            "note": g.get("note"),
            "p1": t.get("p1"), "p2": t.get("p2"), "len_mm": t.get("len_mm"),
            "ends": t.get("ends"),
        })
    return {
        "mm_per_px": round(float(mp), 6),
        "scale_method": res.get("scale_method"),
        "summary": res.get("summary", {}),
        "circles": [{"cx": c["cx"], "cy": c["cy"], "r_px": c["r_px"],
                     "r_mm": round(c["r_px"] * mp, 3),
                     "d_mm": round(2 * c["r_px"] * mp, 3)}
                    for c in res.get("geometry", {}).get("circles", [])],
        "dims": dims,
    }


def handler(in_msg):
    try:
        png = ref_path(in_msg, "drawing_png")
    except KeyError:
        png = None                          # 零件没有图纸（可选入参被跳过）
    try:
        pdf = ref_path(in_msg, "drawing_pdf")
    except KeyError:
        pdf = None
    if pdf and not os.path.exists(pdf):
        pdf = None
    known = ref_data(in_msg, "known_scale")           # 可选：{"mm":..,"px":..}
    verbose = bool(ref_data(in_msg, "verbose", False))
    mode = ref_data(in_msg, "read_mode") or "auto"    # auto|vector|raster

    out_dir = ref_data(in_msg, "out_dir") or os.path.dirname(png or pdf or ".")
    out_path = os.path.join(out_dir, "dwg_semantics.json")

    has_png = bool(png and os.path.exists(png))
    # 选路规则（**默认不改老零件行为**）：
    #   read_mode="vector" → 强制矢量（没有 pdf 就退回栅格并告警）
    #   read_mode="raster" → 强制栅格
    #   auto（默认）      → **PNG 优先，PDF 兜底**：只有当零件没有 PNG 时
    #                        才用 PDF。这样老零件（TechDraw 同时产出
    #                        drawing.png + drawing.pdf）行为完全不变。
    if mode == "vector":
        use_vector, why = bool(pdf), "read_mode=vector"
        if not pdf:
            print("[输入层] read_mode=vector 但零件没有 drawing.pdf → 退回栅格")
    elif mode == "raster":
        use_vector, why = False, "read_mode=raster"
    else:
        use_vector = bool(pdf) and not has_png
        why = "auto：仅 PDF（无 PNG）" if use_vector else "auto：PNG"

    # ---------- 路线 A：矢量 PDF ----------
    if use_vector:
        import pdf_vector
        sem = _pick_pdf(pdf_vector.parse(pdf, known_scale=known, verbose=verbose))
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sem, f, ensure_ascii=False, indent=2)
        s = sem["summary"]
        print("[输入层·矢量] mm/pt = %.5f（%s，k=%s）｜%s"
              % (sem["mm_per_px"], sem["scale_method"], s.get("calib_k"), why))
        print("[输入层·矢量] 线段 %s｜文字 %s｜圆 %d 个｜标注 %d 条｜接地 %d 条（%.0f%%）"
              % (s.get("n_lines"), s.get("n_texts"), s.get("circles", 0),
                 s.get("annotations", 0), s.get("matched", 0),
                 100 * s.get("match_rate", 0.0)))
        for d in sem["dims"]:
            if d["grounded"]:
                print("      ✓ %-10s → %-7s %.2fmm  (%s)"
                      % (d["text"], d["kind"], d.get("measured_mm") or 0.0, d["method"]))
        return [("dwg_semantics", out_path)], {
            "mm_per_px": sem["mm_per_px"], "scale_method": sem["scale_method"],
            "source": "vector_pdf",
            "n_circles": s.get("circles", 0), "n_annotations": s.get("annotations", 0),
            "n_grounded": s.get("matched", 0), "match_rate": s.get("match_rate", 0.0),
        }

    import dwg_parser    # 路线 B 才需要（避免无谓加载 cv2/tesseract）

    # 没有图纸的零件（纯文字/参数输入）：不报错，产出一份带标记的空语义，
    # 让下游按「无图纸语义」处理（s5b 会跳过原图侧校验）。
    if not png or not os.path.exists(png):
        sem = {"no_drawing": True, "mm_per_px": 0.0, "scale_method": "none",
               "circles": [], "dims": [],
               "summary": {"circles": 0, "annotations": 0, "matched": 0,
                           "match_rate": 0.0}}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sem, f, ensure_ascii=False, indent=2)
        print("[输入层] 本零件没有二维图纸（drawing.png 缺失）→ 空语义，跳过读图")
        return [("dwg_semantics", out_path)], {
            "mm_per_px": 0.0, "scale_method": "none", "n_circles": 0,
            "n_annotations": 0, "n_grounded": 0, "match_rate": 0.0,
            "no_drawing": True,
        }

    res = dwg_parser.parse(png, known_scale=known, verbose=verbose)
    sem = _pick(res)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sem, f, ensure_ascii=False, indent=2)

    s = sem["summary"]
    print("[输入层] 标定 mm/px = %.5f（%s）" % (sem["mm_per_px"], sem["scale_method"]))
    print("[输入层] 圆 %d 个｜标注 %d 条｜接地成功 %d 条（%.0f%%）"
          % (s.get("circles", 0), s.get("annotations", 0),
             s.get("matched", 0), 100 * s.get("match_rate", 0.0)))
    for d in sem["dims"]:
        if d["grounded"]:
            print("      ✓ %-8s → %-8s %.2fmm  (%s, conf=%.3f)"
                  % (d["text"], d["kind"], d.get("measured_mm") or 0.0,
                     d["method"], d["confidence"]))
        else:
            print("      ✗ %-8s 未接地" % d["text"])

    return [("dwg_semantics", out_path)], {
        "mm_per_px": sem["mm_per_px"],
        "scale_method": sem["scale_method"],
        "n_circles": s.get("circles", 0),
        "n_annotations": s.get("annotations", 0),
        "n_grounded": s.get("matched", 0),
        "match_rate": s.get("match_rate", 0.0),
    }


if __name__ == "__main__":
    run_stage("s0b_dwgread", handler)
