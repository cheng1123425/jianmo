# -*- coding: utf-8 -*-
r"""
字形分类器（Glyph Classifier）
===============================
图纸上的尺寸标注由「前缀符号 + 数字」组成：
    Φ300   Φ150   R400   4×Φ8   M8   C1
tesseract 的英文模型读不了 Φ / R 这类工程符号，会把「Φ300」读成「300」、
「R400」读成「a7」。所以这里不靠 OCR 认符号，而是**按几何形状认字形**：

  Φ（直径）  ：外轮廓是圆环 + 一条贯穿全高的竖笔
               → 轮廓孔数 == 2，且竖向笔画高度 ≈ 字形高度
  R（半径）  ：宽扁，右侧一条斜腿
               → 孔数 == 0，且 宽/高 ≥ 0.72（数字通常 ≤ 0.65）
  数字       ：交给 OCR（白名单限定为 0-9 . ）

这套「形状规则」是把工程制图的符号约定编码成可判定的几何谓词，
等价于 Drawing-Recode 里让 SVTR 学会的符号识别能力，但不依赖训练。
"""
import cv2
import numpy as np


def glyph_features(mask):
    """单个字形（0/1 掩膜）的几何特征。"""
    h, w = mask.shape
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = 0
    if hier is not None:
        holes = sum(1 for hh in hier[0] if hh[3] != -1)
    col_max = int(mask.sum(axis=0).max())
    return {
        "w": int(w), "h": int(h),
        "area": int(mask.sum()),
        "holes": int(holes),
        "col_max": col_max,
        "aspect": round(w / max(h, 1), 3),
        "vstroke": round(col_max / max(h, 1), 3),   # 竖笔贯穿度
    }


def classify_glyph(mask):
    """
    判定单个字形是 'phi' / 'R' / 'digit' / 'other'。
    """
    f = glyph_features(mask)
    if f["area"] < 20:
        return "other", f
    # Φ：两个孔（环形 + 竖笔把内部切成两半），且竖笔贯穿全高
    if f["holes"] >= 2 and f["vstroke"] >= 0.9:
        return "phi", f
    # 孔数过多 → 汉字碎片，不是工程符号/数字
    if f["holes"] >= 4:
        return "other", f
    # R：无孔，且明显宽扁，竖笔足够直
    if f["holes"] == 0 and f["aspect"] >= 0.72 and f["vstroke"] >= 0.85:
        return "R", f
    return "digit", f


def segment_glyphs(bw_box):
    """
    把一个标注框内的墨迹切成有序字形。
    返回 [(x, y, w, h, mask), ...]，按 x 排序。
    """
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw_box, 8)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 20 or h < 8:
            continue
        mask = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
        comps.append((int(x), int(y), int(w), int(h), mask))
    return sorted(comps, key=lambda c: c[0])


def read_symbol_prefix(bw_box):
    """
    读出一个标注框最前面的符号。
    返回 (symbol, rest_x)：symbol ∈ {'phi','R',None}，
          rest_x 为「符号右边界」在该框内的 x 坐标。
    """
    glyphs = segment_glyphs(bw_box)
    if not glyphs:
        return None, 0
    x0, y0, w0, h0, m0 = glyphs[0]
    kind, _ = classify_glyph(m0)
    if kind == "phi":
        return "phi", x0 + w0
    if kind == "R":
        return "R", x0 + w0
    return None, 0


# ----------------------------------------------------------------------
# 数字结构校正（OCR 纠错）
# ----------------------------------------------------------------------
def digit_structure(mask):
    """
    数字字形的结构特征（用于纠正 OCR 的相似字误认）：
      top / bot      —— 上、下五分带的墨量
      top_span       —— 最上 3 行的横向跨度（占宽比例）
      vstroke        —— 竖笔贯穿度
    """
    h, w = mask.shape
    band = max(1, h // 5)
    top = int(mask[:band].sum())
    bot = int(mask[-band:].sum())
    top_span = int((mask[:3].sum(axis=0) > 0).sum()) / max(w, 1)
    col_max = int(mask.sum(axis=0).max())
    return {
        "top": top, "bot": bot,
        "tb_ratio": round(top / max(bot, 1), 2),
        "top_span": round(top_span, 2),
        "vstroke": round(col_max / max(h, 1), 2),
    }


def correct_digit(mask, ocr_char):
    """
    用结构特征纠正 OCR 的单个数字。
    目前主要修两类系统误认（工程图字体常见）：
      '1' ← 实际是 '7'：顶横长（top_span 高）且顶重底轻（tb_ratio 大）
      '7' ← 实际是 '1'：顶窄且底重（竖笔带底横）
    返回纠正后的字符。
    """
    f = digit_structure(mask)
    if ocr_char in ("1", "l", "I", "7"):
        # 顶部长横 + 顶重底轻 → 是 7
        if f["top_span"] >= 0.75 and f["tb_ratio"] >= 1.8:
            return "7"
        # 顶窄 + 底重 → 是 1
        if f["top_span"] <= 0.6 and f["tb_ratio"] <= 0.8:
            return "1"
    # '9' / '3' / '5' 之间的误认：3 中部开口大、底横长于顶横
    if ocr_char in ("9", "3", "5"):
        if f["tb_ratio"] >= 1.4 and f["top_span"] >= 0.8:
            return "7"
    return ocr_char
