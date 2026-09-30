# -*- coding: utf-8 -*-
r"""s5_collect —— 从投影数据里提取几何特征（铰链支座）"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import run_stage, ref_path


def handler(in_msg):
    data = json.load(open(ref_path(in_msg, "drawing_json"), encoding="utf-8"))
    vt = next(v for v in data["views"] if v["name"] == "Top")
    vf = next(v for v in data["views"] if v["name"] == "Front")
    vr = next(v for v in data["views"] if v["name"] == "Right")

    def span(v, i):
        q = [p[i] for e in v["edges"] for p in e]
        return round(max(q) - min(q), 3)

    def circles(v):
        # 按 (r, cx, cy) 去重
        seen, out = set(), []
        for c in v["circles"]:
            k = (round(c["r"], 2), round(c["cx"], 1), round(c["cy"], 1))
            if k in seen:
                continue
            seen.add(k)
            out.append((c["r"], c["cx"], c["cy"]))
        return out

    return [], {
        "len_x_top": span(vt, 0),
        "len_y_top": span(vt, 1),
        "hgt_front": span(vf, 1),
        "len_x_right": span(vr, 0),
        "len_y_right": span(vr, 1),
        "top_circles": circles(vt),
        "front_circles": circles(vf),
        "right_circles": circles(vr),
        "all_radii": sorted(set(round(c["r"], 2) for v in (vt, vf, vr) for c in v["circles"])),
        "marks": {d["label"]: d["value"] for d in data["dims"]},
    }


if __name__ == "__main__":
    run_stage("s5_collect", handler)