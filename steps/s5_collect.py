# -*- coding: utf-8 -*-
r"""s5_collect —— 从投影数据里提取几何特征（不做任何判断）

入参 refs: drawing_json
产出 data: 外接尺寸、圆特征、高度层、标注实测值
说明：本步**不依赖原图基准**，只把"当前三维投影长什么样"如实提炼出来；
      该不该、对不对，全部交给 s6_compare。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path        # noqa: E402


def handler(in_msg):
    data = json.load(open(ref_path(in_msg, "drawing_json"), encoding="utf-8"))
    vt = next(v for v in data["views"] if v["name"] == "Top")
    vf = next(v for v in data["views"] if v["name"] == "Front")

    tx = [q[0] for e in vt["edges"] for q in e]
    ty = [q[1] for e in vt["edges"] for q in e]
    fy = [q[1] for e in vf["edges"] for q in e]

    # 中心凸台顶线：最长的、x 居中的水平线（对应 z 最大处）
    boss_w, boss_y = None, None
    for h in vf["hlines"]:
        if abs((h["x0"] + h["x1"]) / 2.0) < 1.0:
            w = h["x1"] - h["x0"]
            if boss_w is None or w > boss_w:
                boss_w, boss_y = w, h["y"]

    lev = sorted(set(round(h["y"], 3) for h in vf["hlines"]))
    # 视图 y 轴方向不保证（可能朝下）→ 用「中心凸台顶」判断并归一
    if boss_y is not None and len(lev) > 1 and abs(boss_y - lev[0]) < abs(boss_y - lev[-1]):
        lev = sorted(round(lev[0] + lev[-1] - y, 3) for y in lev)
    steps = [round(lev[i + 1] - lev[i], 3) for i in range(len(lev) - 1)]

    # 圆特征按几何去重（同一个圆会被投影切成多段弧）；**不过滤任何半径**，交给 s6 判断
    seen, circ = set(), []
    for c in vt["circles"]:
        key = (round(c["r"], 3), round(c["cx"], 3), round(c["cy"], 3))
        if key in seen:
            continue
        seen.add(key)
        circ.append((c["r"], c["cx"], c["cy"]))

    return [], {
        "len_x": round(max(tx) - min(tx), 3),
        "len_y": round(max(ty) - min(ty), 3),
        "height": round(max(fy) - min(fy), 3),
        "steps": steps,
        "boss_w": boss_w,
        "top_circles": circ,
        "all_radii": sorted(set(round(c["r"], 3) for c in vt["circles"])),
        "marks": {d["label"]: d["value"] for d in data["dims"]},
    }


if __name__ == "__main__":
    run_stage("s5_collect", handler)
