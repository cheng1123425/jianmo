# -*- coding: utf-8 -*-
r"""view_map.py —— 给 L2 标注加**视图归属**（机械制图投影原则的落地）

为什么需要：现在的 L2 抽取是**视图盲**的 —— 只把 PDF 里的文字全捞出来，
不知道哪个尺寸属于哪个视图。而没有视图归属就无法判：

  * 这张尺寸标在**主视图**还是**俯视图** ⇒ 它的轴向是 X/Z 还是 X/Y（projection-rules §2）
  * 图上那个数到底管"长"还是管"高"（三等关系的基石）
  * 总高该不该标在主视图（dimension-placement §2「总体靠主视图」）
  * 均布孔的定位圆（PCD）出现在哪个视图

本文件把**投影原则**变成可执行的版面分区：

  1. 按 y 大间隙切出**标题栏**（图纸右下角整块）
  2. 按"技术要求"锚点 + 编号条款簇切出**技术要求块**
  3. 余下的文字簇按 x 间隙切成**视图带**（第一角布局：视图是横向排布的）
  4. 每条标注带 `view`（band 序号）+ 归一化坐标

★ 纪律同 pdf_anno.py：**规则一次写定**，对账结果只许度量、不许回流改这里。

用法
    python view_map.py <文件.pdf> [...]          # 打印版面分区
    python view_map.py --json <出目录> <文件…>   # 落盘 <名>.views.json
"""
import json
import os
import sys
import warnings

# ---------------------------------------------------------------- 坐标提取
def _mul(a, b):
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def positioned_text(pdf_path):
    """返回 [(text, x, y)]。坐标是 PDF 内容空间（各图一致，够做相对分区）。"""
    warnings.filterwarnings("ignore")
    from pypdf import PdfReader
    out = []

    def vis(text, cm, tm, fd, fs):
        if text and text.strip():
            m = _mul([cm[0], cm[1], cm[2], cm[3], cm[4], cm[5]],
                     [tm[0], tm[1], tm[2], tm[3], tm[4], tm[5]])
            out.append((text.strip(), round(m[4], 1), round(m[5], 1)))

    PdfReader(pdf_path).pages[0].extract_text(visitor_text=vis)
    return out


# ---------------------------------------------------------------- 版面分区
def _largest_gap(values, lo=None, hi=None):
    """在一串排序值里找最大间隙，返回 (间隙, 分界值)。"""
    vs = sorted(values)
    if lo is not None:
        vs = [v for v in vs if v >= lo]
    if hi is not None:
        vs = [v for v in vs if v <= hi]
    if len(vs) < 2:
        return 0.0, None
    best, cut = 0.0, None
    for a, b in zip(vs, vs[1:]):
        if b - a > best:
            best, cut = b - a, (a + b) / 2.0
    return best, cut


def split_regions(items):
    """切成 {'title':…, 'notes':…, 'views':…} 三块。"""
    if not items:
        return {"title": [], "notes": [], "views": []}
    ys = [it[2] for it in items]
    ymin, ymax = min(ys), max(ys)
    span = max(ymax - ymin, 1.0)

    # ---- 标题栏：从底部起找最大 y 间隙（标题栏是独立一整块）----
    g, cut = _largest_gap(ys, hi=ymin + span * 0.45)
    title, rest = [], list(items)
    if cut is not None and g > span * 0.08:
        title = [it for it in items if it[2] < cut]
        rest = [it for it in items if it[2] >= cut]

    # ---- 技术要求：以 "技术要求" 为锚，向上下扩展到同 x 带的编号条款 ----
    notes = []
    anchor = [it for it in rest if it[0] == "技术要求"]
    if anchor:
        ax, ay = anchor[0][1], anchor[0][2]
        band = [it for it in rest if abs(it[1] - ax) < span * 0.06]
        notes = band
        rest = [it for it in rest if it not in band]

    # ---- 视图带：对余下文字按 x 间隙聚类 ----
    rest = [it for it in rest if not _is_note_token(it[0])]
    xs = sorted({it[1] for it in rest})
    if len(xs) >= 2:
        gaps = [(b - a, (a + b) / 2.0) for a, b in zip(xs, xs[1:])]
        thr = max(span * 0.035, sorted(g for g, _ in gaps)[len(gaps) // 2] * 2.2)
        cuts = sorted(c for g, c in gaps if g >= thr)
    else:
        cuts = []

    def band_of(x):
        b = 0
        for c in cuts:
            if x > c:
                b += 1
        return b

    views = {}
    for t, x, y in rest:
        views.setdefault(band_of(x), []).append((t, x, y))
    return {"title": title, "notes": notes, "views": views}


def _is_note_token(t):
    import re
    if re.match(r"^\d+\.\D", t):                    # 1.去除毛刺飞边。
        return True
    return any(k in t for k in ("未注", "其余", "全部", "参照数模"))


# ---------------------------------------------------------------- 汇总
def view_summary(pdf_path):
    items = positioned_text(pdf_path)
    reg = split_regions(items)
    bands = []
    for b in sorted(reg["views"]):
        its = reg["views"][b]
        xs = [it[1] for it in its]
        ys = [it[2] for it in its]
        bands.append({
            "band": b, "n": len(its),
            "x_range": [round(min(xs), 1), round(max(xs), 1)],
            "y_range": [round(min(ys), 1), round(max(ys), 1)],
            "texts": [it[0] for it in sorted(its, key=lambda p: (-p[2], p[1]))],
        })
    return {
        "part": os.path.splitext(os.path.basename(pdf_path))[0],
        "source": os.path.abspath(pdf_path),
        "n_title": len(reg["title"]), "n_notes": len(reg["notes"]),
        "bands": bands,
    }


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    as_json = argv[0] == "--json"
    outdir = argv[1] if as_json else None
    files = argv[2:] if as_json else argv
    if as_json:
        os.makedirs(outdir, exist_ok=True)

    for p in files:
        try:
            s = view_summary(p)
        except Exception as e:
            print("%-28s FAIL %s" % (os.path.basename(p)[:28], str(e)[:40]))
            continue
        print("=== %s ===  标题栏 %d 项 / 技术要求 %d 项 / 视图带 %d 个"
              % (s["part"][:28], s["n_title"], s["n_notes"], len(s["bands"])))
        for b in s["bands"]:
            print("  带%d  n=%-3d x[%s~%s] y[%s~%s]"
                  % (b["band"], b["n"], b["x_range"][0], b["x_range"][1],
                     b["y_range"][0], b["y_range"][1]))
            print("       %s" % " ".join(b["texts"][:18]))
        if as_json:
            with open(os.path.join(outdir, s["part"] + ".views.json"), "w",
                      encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
