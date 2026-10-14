# -*- coding: utf-8 -*-
"""图纸解析工具 — 按 Drawing-Recode 思路的轻量复现。

几何层与标注层分离提取，再显式接地（AGL 的传统CV等价物）。
不依赖任何神经网络权重。
"""
from . import geometry, annotation, grounding

__all__ = ["geometry", "annotation", "grounding", "parse"]
__version__ = "0.1.0"


def parse(img_path, known_scale=None, verbose=False):
    """
    从图纸图片解析出：几何 + 标注 + 接地关系。

    参数
    ----
    img_path     : 图纸图片路径（png/jpg）
    known_scale  : 可选标定 {"mm": 550, "px": 1234}，不给则自动推断
    verbose      : 打印过程

    返回
    ----
    dict: {geometry, annotations, mm_per_px, scale_method, grounded, summary}
    """
    geo = geometry.extract(img_path)
    annos = annotation.extract(img_path)

    mm_per_px, method = grounding.calibrate(geo, annos, known_scale)
    if verbose:
        print("[标定] mm/px = %s （方式: %s）" % (mm_per_px, method))

    grounded = []
    if mm_per_px:
        grounded = grounding.ground(geo, annos, mm_per_px, img_path=img_path)
        grounded = grounding.attach_mm(grounded, mm_per_px, geo)

    matched = sum(1 for g in grounded if g.get("target"))
    summary = {
        "circles": len(geo["circles"]),
        "lines": len(geo["lines"]),
        "annotations": len(annos),
        "matched": matched,
        "match_rate": round(matched / len(annos), 3) if annos else 0.0,
    }

    return {
        "geometry": geo,
        "annotations": annos,
        "mm_per_px": mm_per_px,
        "scale_method": method,
        "grounded": grounded,
        "summary": summary,
    }
