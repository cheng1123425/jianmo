# -*- coding: utf-8 -*-
r"""
标注层提取器（Annotation Layer Extractor）
===========================================
对应 Drawing-Recode 的「YOLO 检测标注框 + SVTR 文字识别」。

本实现不依赖神经网络，改用：
  - 标注框检测 → 形态学「闭运算」把同一处的字符连成块 + 连通域分析
  - 文字识别   → tesseract OCR（--psm 7 单行），并做符号归一化
  - 符号修复   → φ/Φ/⌀ 常被 OCR 吞掉或误认，用「数字前孤立细笔画」规则补回
  - 中文过滤   → 视图名（主视图/俯视图/轴测图）、标题栏等非尺寸文本剔除

产出：标注表（每条标注的 文字 / 中心坐标 / 边界框 / 类型）
"""
import subprocess
import os
import tempfile
import re

import cv2
import numpy as np


# 尺寸标注的语义分类（图纸上的符号约定）
_SYMBOL_RULES = [
    (r'^([\d.]+)\s*[×xX*]\s*[Φφ⌀Øøϕ]\s*([\d.]+)$', "pattern_dia"),  # 4×Φ8
    (r'^[Rr]\s*([\d.]+)$',              "radius"),      # R6 / R400
    (r'^[Φφ⌀Øøϕ]\s*([\d.]+)$',          "diameter"),    # φ300 / Φ8
    (r'^[Cc]\s*([\d.]+)$',              "chamfer"),     # C1
    (r'^[Mm]\s*([\d.]+)$',              "thread"),      # M8
    (r'^\d+\s*:\s*\d+$',                "scale"),       # 1:4
    (r'^([\d.]+)\s*[±\+\-]\s*([\d.]+)$', "tolerance"),  # 10±0.05
    (r'^([\d.]+)$',                     "linear"),      # 纯数字
]

# 直径符号的各种写法（tesseract 可能吐出任一种）
_DIA_SYMS = "Φφ⌀Øøϕɸ𝛷𝜙"
_RAD_SYMS = "Rr"


def classify(text):
    """按图纸符号约定判断标注类型。返回 (type, 解析出的值列表)。"""
    t = normalize(text)
    for pat, kind in _SYMBOL_RULES:
        m = re.match(pat, t, re.IGNORECASE)
        if m:
            vals = []
            for g in m.groups():
                try:
                    vals.append(float(g))
                except (TypeError, ValueError):
                    pass
            return kind, vals
    return "unknown", []


def normalize(text):
    """归一化：去空格、统一符号、修常见 OCR 误认。"""
    t = (text or "").strip().replace("\n", "").replace(" ", "")
    # 常见误认：0↔O、l↔1、S↔5、B↔8 在尺寸数字里
    t = t.replace("O", "0").replace("o", "0").replace("l", "1")
    # φ 的各种写法统一成 Φ
    for s in "φϕɸ":            # 小写形式
        t = t.replace(s, "Φ")
    for s in "⌀Øø":           # 直径符号
        t = t.replace(s, "Φ")
    # Φ 后跟数字，或 R 后跟数字
    t = re.sub(r'^[Φ]\s*', "Φ", t)
    t = re.sub(r'^[Rr]\s*', "R", t)
    return t


def is_cjk(ch):
    """判断是否 CJK 字符（用于剔除视图名/标题栏文字）。"""
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x303F) or \
           (0xFF00 <= o <= 0xFFEF)


def has_cjk(text):
    return any(is_cjk(c) for c in (text or ""))


# ----------------------------------------------------------------------
# 标注框检测
# ----------------------------------------------------------------------
def remove_lines(bw, min_len=70, thickness=7):
    """
    把图上的长直线（尺寸线/引线/轮廓）抹掉，只留文字。

    标注文字常与尺寸线/引线相接触，直接做连通域会把「文字+线」连成一块，
    导致文字无法切分。这里先用 HoughLinesP 找出所有长直线，再按线宽抹去，
    剩下的就是孤立的字形。注意：抹线会有副作用（圆的直线部分也被抹），
    所以这个清理版只用于**标注框检测**，不用于几何层。
    """
    h, w = bw.shape
    lines = cv2.HoughLinesP(bw, 1, np.pi / 360, threshold=60,
                            minLineLength=min_len, maxLineGap=4)
    mask = np.zeros_like(bw)
    if lines is not None:
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            cv2.line(mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, thickness)
    return cv2.bitwise_and(bw, cv2.bitwise_not(mask))


def detect_boxes(bw, min_h=14, max_h_ratio=0.08, aspect_max=4.0,
                 use_line_removal=True):
    """
    检测标注框 —— 「字形优先」策略：

    1) 先抹掉长直线（尺寸线/引线），让文字与线分离；
    2) 把剩下的**紧凑连通域**当作候选字形（数字/符号都是紧凑块），
       排除细长形状；
    3) 把邻近的字形按行聚成标注框。

    这样即使文字压在线上，也能正确切出「Φ300」「R400」等标注。
    """
    h, w = bw.shape
    max_h = int(h * max_h_ratio)

    work = remove_lines(bw) if use_line_removal else bw

    n, lab, stats, _ = cv2.connectedComponentsWithStats(work, 8)
    glyphs = []
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if hh < min_h or hh > max_h:
            continue
        if area < 40:
            continue
        asp = ww / max(hh, 1)
        if asp > aspect_max:            # 细长 → 线条，跳过
            continue
        if ww > w * 0.3:
            continue
        # 填充度过滤：真字形是实笔画（fill 0.3~0.55）；
        # 被去线切出来的「残影/描边」（fill < 0.18）不是字。
        fill = area / float(ww * hh)
        if fill < 0.18:
            continue
        glyphs.append((int(x), int(y), int(ww), int(hh)))

    # 丢弃「全是残影、没有一个实心字形」的簇（解线后留下的细描边）
    return _cluster_glyphs(glyphs, min_glyphs=2)


def _cluster_glyphs(glyphs, gap_x=1.6, gap_y=0.6, min_glyphs=1):
    """
    把字形按「同一行、间距不大」聚成标注框。
    gap_x / gap_y 为最大间隔（相对字高）。
    """
    if not glyphs:
        return []
    # 以字高为基准排序
    hmed = sorted(g[3] for g in glyphs)[len(glyphs) // 2]
    gx = gap_x * hmed
    gy = gap_y * hmed

    glyphs = sorted(glyphs, key=lambda g: (g[1], g[0]))
    clusters = []
    counts = []
    used = [False] * len(glyphs)
    for i, g in enumerate(glyphs):
        if used[i]:
            continue
        cur = list(g)
        cnt = 1
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, g2 in enumerate(glyphs):
                if used[j]:
                    continue
                # 垂直方向重叠（同一行）且水平靠近
                y_ov = min(cur[1] + cur[3], g2[1] + g2[3]) - max(cur[1], g2[1])
                if y_ov <= 0.4 * min(cur[3], g2[3]):
                    continue
                xgap = max(g2[0] - (cur[0] + cur[2]),
                           cur[0] - (g2[0] + g2[2]), 0)
                if xgap <= gx:
                    nx1 = min(cur[0], g2[0]); ny1 = min(cur[1], g2[1])
                    nx2 = max(cur[0] + cur[2], g2[0] + g2[2])
                    ny2 = max(cur[1] + cur[3], g2[1] + g2[3])
                    cur = [nx1, ny1, nx2 - nx1, ny2 - ny1]
                    used[j] = True
                    cnt += 1
                    changed = True
        clusters.append(tuple(cur))
        counts.append(cnt)
    out = []
    pad = 4
    for c, cnt in zip(clusters, counts):
        if cnt < min_glyphs:
            continue
        out.append((max(0, c[0] - pad), max(0, c[1] - pad),
                    c[2] + 2 * pad, c[3] + 2 * pad))
    return out


def _split_by_gaps(boxes, bw, gap_ratio=0.8, pad=3):
    """把过宽的框按列投影的间隙切开（一个框里挤了多条标注时）。"""
    h, w = bw.shape
    out = []
    for (x, y, ww, hh) in boxes:
        sub = bw[y:y + hh, x:x + ww]
        colsum = sub.sum(axis=0)
        if colsum.max() == 0:
            continue
        thr = 0.05 * colsum.max()
        on = colsum > thr
        # 找连续 off 段（>gap_ratio*hh）作为切点
        gaps = []
        run = 0
        for j, v in enumerate(on):
            if not v:
                run += 1
            else:
                if run >= gap_ratio * hh:
                    gaps.append(j - run // 2)
                run = 0
        if not gaps:
            out.append((max(0, x - pad), max(0, y - pad),
                        ww + 2 * pad, hh + 2 * pad))
            continue
        cuts = [0] + gaps + [ww]
        for a, b in zip(cuts[:-1], cuts[1:]):
            if b - a < 8:
                continue
            out.append((max(0, x + a - pad), max(0, y - pad),
                        (b - a) + 2 * pad, hh + 2 * pad))
    return _merge_overlapping(out)


def _merge_overlapping(boxes, iou_th=0.3):
    """合并重叠框。"""
    def iou(a, b):
        ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
        bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        if inter == 0:
            return 0.0
        return inter / (a[2] * a[3] + b[2] * b[3] - inter)

    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        out, used = [], [False] * len(merged)
        for i in range(len(merged)):
            if used[i]:
                continue
            cur = merged[i]
            for j in range(i + 1, len(merged)):
                if used[j]:
                    continue
                if iou(cur, merged[j]) > iou_th:
                    x1 = min(cur[0], merged[j][0]); y1 = min(cur[1], merged[j][1])
                    x2 = max(cur[0] + cur[2], merged[j][0] + merged[j][2])
                    y2 = max(cur[1] + cur[3], merged[j][1] + merged[j][3])
                    cur = (x1, y1, x2 - x1, y2 - y1)
                    used[j] = True
                    changed = True
            out.append(cur)
        merged = out
    return merged


# ----------------------------------------------------------------------
# OCR
# ----------------------------------------------------------------------
_WHITELIST = ("0123456789.," + "Rr" + "Φφϕɸ⌀Øø" +
              "xX*×±:+-CcMm")


def ocr_box(gray_img, box, psm=7, upscale=4, whitelist=None,
            prefer_digits=False):
    """
    对单个区域做 OCR。返回识别文字（失败返回 ""）。

    图纸本身是「黑字白底」，所以**原图灰度直接送 tesseract 往往最准**；
    二值化/反相只在原图对比度差时才需要。这里把几种预处理都试一遍，
    取「最像目标」的结果（prefer_digits 时偏好纯数字串）。
    """
    x, y, w, h = [int(v) for v in box]
    x, y = max(0, x), max(0, y)
    w, h = max(2, w), max(2, h)
    roi = gray_img[y:y + h, x:x + w]
    if roi.size == 0:
        return ""

    wl = whitelist if whitelist is not None else _WHITELIST
    variants = _preprocess_variants(roi, upscale)
    results = []
    with tempfile.TemporaryDirectory() as td:
        for tag, img in variants:
            p = os.path.join(td, tag + ".png")
            cv2.imwrite(p, img)
            for attempt in (psm, 7, 8, 6, 13):
                try:
                    r = subprocess.run(
                        ["tesseract", p, "stdout", "--psm", str(attempt),
                         "-c", "tessedit_char_whitelist=" + wl],
                        capture_output=True, text=True, timeout=20)
                    txt = (r.stdout or "").strip().replace("\n", "").replace(" ", "")
                    if txt:
                        results.append(txt)
                except Exception:
                    continue
    if not results:
        return ""
    # 投票：出现次数最多者优先；prefer_digits 时偏好纯数字
    from collections import Counter
    if prefer_digits:
        dig = [t for t in results if re.fullmatch(r'\d+(?:\.\d+)?', t)]
        if dig:
            return Counter(dig).most_common(1)[0][0]
    return Counter(results).most_common(1)[0][0]


def _preprocess_variants(roi, upscale):
    """产出多种预处理版本的 ROI（原图 / 二值 / 反相 / 去噪）。"""
    out = []
    # 1) 原图直送（最常最准）
    up = cv2.resize(roi, None, fx=upscale, fy=upscale,
                    interpolation=cv2.INTER_CUBIC)
    out.append(("raw", _pad(up)))
    # 2) Otsu 二值（黑字白底）
    _, otsu = cv2.threshold(up, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out.append(("otsu", _pad(otsu)))
    # 3) 反相（白字黑底时用）
    out.append(("inv", _pad(cv2.bitwise_not(otsu))))
    # 4) 原图 + 轻度锐化
    blur = cv2.GaussianBlur(up, (0, 0), 1.0)
    sharp = cv2.addWeighted(up, 1.6, blur, -0.6, 0)
    out.append(("sharp", _pad(sharp)))
    return out


def _pad(img, p=25):
    return cv2.copyMakeBorder(img, p, p, p, p,
                              cv2.BORDER_CONSTANT, value=255)


def _glyph_cluster(bw_box, min_area=25, max_aspect=3.0):
    """
    从标注框里挑出「像字符」的连通域，返回它们的联合包围盒。
    用来把引线/尺寸线（细长）从文字里剔除 —— 否则 OCR 会把线段读成 "1"。

    判据：字形的「高宽比」不会太极端。真字形 w/h 大约 0.4~1.3；
    尺寸线/引线通常 w/h > 3（水平线）或 < 0.2（竖线）。
    返回 (x0, y0, x1, y1) 或 None。
    """
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw_box, 8)
    sel = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or h < 8:
            continue
        asp = w / max(h, 1)
        # 细长线（水平或竖直）→ 剔除
        if asp > max_aspect or asp < 1.0 / max_aspect:
            continue
        sel.append((x, y, x + w, y + h))
    if not sel:
        return None
    x0 = min(s[0] for s in sel); y0 = min(s[1] for s in sel)
    x1 = max(s[2] for s in sel); y1 = max(s[3] for s in sel)
    return (x0, y0, x1, y1)


def read_annotation(gray, bw, box):
    """
    读一个标注框：先按字形判前缀符号（Φ / R），再 OCR 后面的数字。
    返回 (text, type, values)。失败返回 None。
    """
    from .glyphs import read_symbol_prefix
    x, y, w, h = [int(v) for v in box]
    x, y = max(0, x), max(0, y)
    bw_box = (bw[y:y + h, x:x + w] > 0).astype(np.uint8)
    if bw_box.size == 0:
        return None

    # 先把引线/尺寸线剥掉，得到纯净的文字簇
    cl = _glyph_cluster(bw_box)
    if cl is None:
        return None
    cx0, cy0, cx1, cy1 = cl
    clean = np.zeros_like(bw_box)
    clean[cy0:cy1, cx0:cx1] = bw_box[cy0:cy1, cx0:cx1]

    # 含「非尺寸字形」（汉字碎片等）→ 直接判非尺寸
    if _has_invalid_glyph(clean):
        return None

    sym, rest_x = read_symbol_prefix(clean)

    if sym in ("phi", "R"):
        # rest_x 是「符号右边界」在整框内的绝对 x 坐标
        if rest_x >= clean.shape[1] - 4:
            return None
        # 数字区（相对框内的坐标）
        dx0 = rest_x + 2
        dy0 = cy0
        dw = cx1 - rest_x - 2
        dh = cy1 - cy0
        if dw < 6 or dh < 6:
            return None
        digit_mask = clean[dy0:dy0 + dh, dx0:dx0 + dw]
        txt = read_digits(digit_mask, gray, x + dx0, y + dy0)
        if not txt:
            # 退化：整块 OCR
            txt = _crude_digits(ocr_box(gray, (x + dx0, y + dy0, dw, dh),
                                        whitelist="0123456789. ",
                                        prefer_digits=True))
        if not txt:
            return None
        try:
            val = float(txt)
        except ValueError:
            return None
        if sym == "phi":
            return "Φ" + txt, "diameter", [val]
        return "R" + txt, "radius", [val]

    # 无前缀：整框 OCR（用紧包围盒，避免引线）
    tight = (x + cx0, y + cy0, cx1 - cx0, cy1 - cy0)
    raw = ocr_box(gray, tight)
    if not raw:
        return None
    txt = normalize(raw)
    if has_cjk(txt) or has_cjk(raw):
        return None
    if not re.search(r'\d', txt):
        return None
    kind, vals = classify(txt)
    return txt, kind, vals


def _has_invalid_glyph(clean_mask):
    """
    框里是否有「非尺寸字形」：
      - 汉字碎片：孔数≥4（复杂字形）或 phi 形孔数≠2
      - 字形尺寸极不一致（汉字的笔画长短悬殊）
      - 出现超宽字形（汉字常达 30~50px 宽，数字只有 18~20px）
    """
    from .glyphs import segment_glyphs, glyph_features
    glyphs = segment_glyphs(clean_mask)
    core = []
    widths = []
    for g in glyphs:
        f = glyph_features(g[4])
        if f["area"] < 20:
            continue
        if f["holes"] >= 4:
            return True
        # Φ 形但孔数不是 2（= 汉字里带方框的部件）
        if f["holes"] >= 3:
            return True
        core.append(f)
        widths.append(f["w"])
    if len(core) < 2:
        return False
    hs = sorted(f["h"] for f in core)
    hmed = hs[len(hs) // 2]
    if hmed <= 0:
        return False
    # 高度离散度
    disp = np.std([f["h"] / hmed for f in core])
    if disp > 0.4:
        return True
    # 宽度异常：超过中位宽 1.8 倍（汉字部件）
    wmed = sorted(widths)[len(widths) // 2]
    if wmed > 0 and max(widths) > 1.8 * wmed and max(widths) > 28:
        return True
    return False


def _crude_digits(txt):
    """从 OCR 结果里抠出数字串（含小数点）。"""
    m = re.findall(r'\d+(?:\.\d+)?', txt or "")
    if not m:
        return ""
    # 取最长的一段
    return max(m, key=len)


def read_digits(bw_box, gray, ox, oy):
    """
    逐字符读数字串：对每个字形单独 OCR，再用结构特征纠错。
    比整行 OCR 稳得多 —— 整行 OCR 的相似字误认（7↔1、5↔9）会被逐字校正拦住。

    bw_box : 该数字区的二值掩膜（0/1）
    gray   : 原灰度图（用于 OCR 裁切）
    ox, oy : bw_box 左上角在原图中的坐标
    返回数字字符串。
    """
    from .glyphs import segment_glyphs, correct_digit, classify_glyph

    glyphs = segment_glyphs(bw_box)
    # 只保留高度接近主流的字形（去掉残留的分隔符/线段）
    if not glyphs:
        return ""
    hs = sorted(g[3] for g in glyphs)
    hmed = hs[len(hs) // 2]
    glyphs = [g for g in glyphs if 0.55 * hmed <= g[3] <= 1.6 * hmed]

    out = ""
    for (gx, gy, gw, gh, m0) in glyphs:
        kind, _ = classify_glyph(m0)
        # 前缀符号已在调用方剥离；此处再出现的 phi/R 形状，
        # 实际上是数字（如 R400 末尾的 0 会被误判成 R）→ 当数字处理
        # 用字号自适应 upscale，保证送到 tesseract 的字高 ~120px
        up = max(2, int(120 / max(gh, 1)))
        sub = (ox + gx - 2, oy + gy - 2, gw + 4, gh + 4)
        t = ocr_box(gray, sub, whitelist="0123456789.",
                    prefer_digits=True, upscale=up)
        t = _crude_digits(t)
        if not t:
            continue
        ch = t[0]
        ch = correct_digit(m0, ch)
        # 小数点：字形很矮且很扁 → '.'
        if m0.shape[1] < 0.35 * m0.shape[0]:
            ch = "."
        out += ch
    return out


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------
def extract(img_path, geometry_of_interest=None, exclude_title_block=True):
    """主入口：返回标注层结构。"""
    from .geometry import load_binary
    gray, bw = load_binary(img_path)
    work = remove_lines(bw)
    boxes = detect_boxes(bw)

    tb = _detect_title_block(bw) if exclude_title_block else None

    annos = []
    for box in boxes:
        if tb and _inside(box, tb):
            continue
        res = read_annotation(gray, work, box)
        if not res:
            continue
        txt, kind, vals = res
        # 汉字几何过滤：汉字字形大小不一、笔画碎片多
        if _looks_like_cjk(work, box):
            continue
        # 字形一致性过滤：残影/箭头碎片不具备「一致字符排布」的特征
        x, y, w, h = [int(v) for v in box]
        bb = (work[y:y + h, x:x + w] > 0).astype(np.uint8)
        from .glyphs import segment_glyphs
        glyphs = [g for g in segment_glyphs(bb) if g[2] * g[3] >= 40]
        # 尺寸箭头残影：整簇只由直笔画构成
        if _is_stroke_cluster(bb):
            continue
        if len(glyphs) >= 2 and not _glyphs_uniform(bb):
            continue
        cx = box[0] + box[2] / 2.0
        cy = box[1] + box[3] / 2.0
        annos.append({
            "text": txt,
            "type": kind,
            "values": vals,
            "box_px": [int(v) for v in box],
            "center_px": [round(float(cx), 1), round(float(cy), 1)],
        })
    return _dedup(annos)


def _detect_title_block(bw):
    """
    自动识别标题栏：图框右下角由长直线围成的矩形格。
    用水平/竖直长线求交，取右下角那片的最大空白矩形外框。
    返回 (x0, y0, x1, y1) 或 None。
    """
    h, w = bw.shape
    horiz = cv2.morphologyEx(
        bw, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.06), 1)))
    vert = cv2.morphologyEx(
        bw, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.04))))
    # 竖直长线的 x 位置（右下角区域）
    vcols = np.where(vert[:, int(w * 0.5):].any(axis=0))[0] + int(w * 0.5)
    hrows = np.where(horiz[int(h * 0.6):, :].any(axis=1))[0] + int(h * 0.6)
    if len(vcols) == 0 or len(hrows) == 0:
        return None
    x0 = int(vcols.min())
    y0 = int(hrows.min())
    x1 = int(vcols.max())
    y1 = int(hrows.max())
    if (x1 - x0) < w * 0.1 or (y1 - y0) < h * 0.05:
        return None
    return (x0, y0, x1, y1)


def _inside(box, region, margin=6):
    """box 的中心是否落在 region 内。"""
    cx = box[0] + box[2] / 2.0
    cy = box[1] + box[3] / 2.0
    x0, y0, x1, y1 = region
    return (x0 - margin) <= cx <= (x1 + margin) and \
           (y0 - margin) <= cy <= (y1 + margin)


def _looks_like_cjk(bw, box):
    """
    几何判汉字：汉字的笔画被切成大小不一的多个连通域（h 从个位数到全高都有），
    而数字/符号的字形高度高度一致。用「字形高度一致性」区分。

    判据：字形高度相对离散度 > 0.35 且 字形数 >= 4 → 汉字。
    """
    from .glyphs import segment_glyphs
    x, y, w, h = [int(v) for v in box]
    sub = (bw[y:y + h, x:x + w] > 0).astype(np.uint8)
    if sub.sum() == 0:
        return True
    glyphs = segment_glyphs(sub, )
    hs = [g[3] for g in glyphs]
    if len(hs) == 0:
        return True
    # 剔除明显是线段的碎片（极扁或极细）
    ws = [g[2] for g in glyphs]
    core = [(a, b) for a, b in zip(ws, hs)
            if b >= 8 and a / max(b, 1) < 3]
    if len(core) < 3:
        return False
    hs2 = sorted(b for a, b in core)
    hmed = hs2[len(hs2) // 2]
    disp = np.std([b / max(hmed, 1) for b in hs2])
    # 汉字的碎片高度差异大 → 离散度高
    return disp > 0.35 and len(core) >= 5


def _glyphs_uniform(clean_mask, tol=0.28):
    """
    判定框内字形是否「一致的字符排布」：
    真标注的字符应有接近的字高、字宽，且水平方向基本不重叠。
    被去线切碎的形状（如箭头→两片残影）往往相互重叠或尺寸悬殊。

    注意：只统计「主干字形」—— 一个字符可能被去线切成主块 + 细碎片
    （如 R400 里的 '0' 被切成 26px 主体 + 15px 碎片），碎片会污染统计。
    """
    from .glyphs import segment_glyphs
    gs = [g for g in segment_glyphs(clean_mask) if g[2] * g[3] >= 40]
    if len(gs) < 2:
        return False
    hmed = sorted(g[3] for g in gs)[len(gs) // 2]
    if hmed <= 0:
        return False
    # 只保留主干字形（高度接近主流），碎片忽略
    core = [g for g in gs if 0.7 * hmed <= g[3] <= 1.45 * hmed]
    if len(core) < 2:
        return False
    hs = [g[3] for g in core]
    ws = [g[2] for g in core]
    hmed = sorted(hs)[len(hs) // 2]
    if hmed <= 0:
        return False
    # 字高、字宽都要接近
    if max(abs(a - hmed) / hmed for a in hs) > tol:
        return False
    wmed = sorted(ws)[len(ws) // 2]
    if wmed > 0 and max(abs(a - wmed) / wmed for a in ws) > 0.6:
        return False
    # 水平方向不应大幅重叠（真正的字符是横向依次排列）
    xs = sorted(core, key=lambda g: g[0])
    for a, b in zip(xs[:-1], xs[1:]):
        if b[0] < a[0] + 0.5 * a[2]:       # 明显重叠
            return False
    return True


def _stroke_score(mask):
    """
    判定一个连通域是否「一根直笔画」。

    用墨点二阶矩（PCA）的次轴/主轴比衡量：
      - 直笔画（箭头的斜边、尺寸线残段）→ 次轴极小，score ≈ 0.26~0.28
      - 真字形（数字/符号有弯折与分支）→ score ≥ 0.39（实测 '7' 最低 0.393）
    """
    pts = np.argwhere(mask > 0)
    if len(pts) < 8:
        return 1.0
    pts = pts[:, [1, 0]].astype(np.float64)
    pts = pts - pts.mean(axis=0)
    ev = np.linalg.eigvalsh(np.cov(pts.T))[::-1]
    if ev[0] <= 1e-9:
        return 1.0
    return float((ev[1] / ev[0]) ** 0.5)


def _is_stroke_cluster(mask, stroke_th=0.32, min_glyphs=2, min_h=12):
    """
    整个框是否「只由直笔画构成」—— 尺寸箭头（两条斜边）的典型特征。

    尺寸箭头被去线后会留下两片斜笔画；它们的高宽都接近，靠
    _glyphs_uniform 拦不住，但 PCA 直线度能干净区分（0.27 vs 数字≥0.39）。
    要求簇内**所有**字形都是直笔画，避免误杀含数字的标注。
    """
    from .glyphs import segment_glyphs
    gs = [g for g in segment_glyphs(mask)
          if g[2] * g[3] >= 40 and g[3] >= min_h]
    if len(gs) < min_glyphs:
        return False
    return all(_stroke_score(g[4]) <= stroke_th for g in gs)


def _dedup(annos, tol=25):
    """同一处的重复识别合并（保留更完整/更长的文本）。"""
    kept = []
    for a in sorted(annos, key=lambda x: -len(x["text"])):
        cx, cy = a["center_px"]
        if not any(abs(cx - k["center_px"][0]) < tol and
                   abs(cy - k["center_px"][1]) < tol for k in kept):
            kept.append(a)
    return sorted(kept, key=lambda x: (x["center_px"][1], x["center_px"][0]))
