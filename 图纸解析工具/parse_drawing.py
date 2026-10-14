#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
图纸解析工具 — 命令行入口
=========================
按 Drawing-Recode 思路复现：几何层 / 标注层分离提取 + 显式接地。

用法
----
    python parse_drawing.py <图纸.png> [--scale-mm 550 --scale-px 1234] [--json out.json]
    python parse_drawing.py 图纸.png --visual out_preview.png

示例
----
    python parse_drawing.py /workspace/jianmo/drawing.png
    python parse_drawing.py 图纸.png --json result.json --visual marked.png
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dwg_parser import parse


def print_report(res):
    s = res["summary"]
    print("=" * 62)
    print("图纸解析结果")
    print("=" * 62)
    print("几何层： 圆 %d 个 ｜ 直线 %d 条 ｜ 轮廓 %d 个"
          % (s["circles"], s["lines"], len(res["geometry"]["contours"])))
    print("标注层： %d 条" % s["annotations"])
    print("标定：   mm/px = %s （%s）" % (
        round(res["mm_per_px"], 5) if res["mm_per_px"] else None,
        res["scale_method"]))
    print("接地：   %d/%d 已匹配（%.0f%%）"
          % (s["matched"], s["annotations"], s["match_rate"] * 100))
    print("-" * 62)

    print("\n【标注 → 几何 接地表】")
    print("%-14s %-12s %-22s %-8s %s" % ("标注", "类型", "绑定几何", "置信", "方式"))
    for g in res["grounded"]:
        a = g["annotation"]
        t = g.get("target")
        if t and t["kind"] == "circle":
            tgt = "圆 r=%.1fpx" % t["r_px"]
            if t.get("d_mm"):
                tgt = "圆 ⌀%.2fmm" % t["d_mm"]
        elif t and t["kind"] == "line":
            tgt = "线 %.1fpx" % t["len_px"]
            if t.get("len_mm"):
                tgt = "线 %.2fmm" % t["len_mm"]
        else:
            tgt = "—"
        print("%-14s %-12s %-22s %-8s %s" % (
            a["text"], a["type"], tgt, g["confidence"], g["method"]))


def make_visual(img_path, res, out_path):
    """把检测结果画到图上，便于人工核对。"""
    import cv2
    img = cv2.imread(img_path)
    # 几何：圆
    for c in res["geometry"]["circles"]:
        cv2.circle(img, (int(c["cx"]), int(c["cy"])), int(c["r_px"]),
                   (0, 160, 0), 2)
    # 标注框
    for g in res["grounded"]:
        a = g["annotation"]
        x, y, w, h = a["box_px"]
        color = (0, 0, 220) if g.get("target") else (120, 120, 120)
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
        # 画接地连线
        t = g.get("target")
        if t:
            cx, cy = a["center_px"]
            if t["kind"] == "circle":
                cv2.line(img, (int(cx), int(cy)),
                         (int(t["cx"]), int(t["cy"])), (220, 0, 220), 1)
    cv2.imwrite(out_path, img)


def main():
    ap = argparse.ArgumentParser(description="图纸解析工具（Drawing-Recode 思路）")
    ap.add_argument("image", help="图纸图片路径")
    ap.add_argument("--scale-mm", type=float, default=None, help="标定：实际毫米")
    ap.add_argument("--scale-px", type=float, default=None, help="标定：像素")
    ap.add_argument("--json", dest="json_out", default=None, help="输出 JSON 路径")
    ap.add_argument("--visual", default=None, help="输出标注预览图路径")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    known = None
    if args.scale_mm and args.scale_px:
        known = {"mm": args.scale_mm, "px": args.scale_px}

    res = parse(args.image, known_scale=known, verbose=not args.quiet)

    if not args.quiet:
        print_report(res)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print("\nJSON 已写出: %s" % args.json_out)

    if args.visual:
        make_visual(args.image, res, args.visual)
        print("预览图已写出: %s" % args.visual)


if __name__ == "__main__":
    main()
