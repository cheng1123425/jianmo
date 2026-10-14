# -*- coding: utf-8 -*-
"""最小闭环 —— ② 中间表示（IR）

对应交接文档 §4.2 / §4.4：一个 IR 要同时装三层
  语义层 semantic   —— 这是什么（必须标注，供出图 + 3D↔2D 对应）
  结构层 structural —— 主体/加法/减法/边处理（可自动）
  操作层 impl       —— rect/extrude/cut…（可自动，供 ③ 脚本）

这就是文档 §4.4 说的「缺的那一环」：drawing 字段 = 3D↔2D 对应关系。
"""
import json

IR = {
    "part": "底板+4孔",
    "features": [
        {
            "id": "F1",
            "semantic": {"type": "base_plate", "role": "主体",
                         "dims": {"L": 120, "W": 80, "T": 12}},
            "structural": {"kind": "主体"},
            "impl": [("rect", (120, 80)), ("extrude", (12,))],
            "drawing": None,          # 主体本身不直接标注
        },
        {
            "id": "F2",
            "semantic": {"type": "hole_pattern", "pattern": "rectangular",
                         "count": 4, "dia": 10, "role": "安装孔", "位置": "四角"},
            "structural": {"kind": "减法", "target": "F1"},
            # 孔位：中心距 90 × 60（即离边 15）
            "impl": [("grid_locations", (90, 60, 2, 2)), ("circle", (4,)), ("extrude", (-12,))],
            "drawing": {"annotation": "4×Φ8", "view": "plan"},   # ← 3D↔2D 对应关系
        },
        {
            "id": "F3",
            "semantic": {"type": "edge_fillet", "role": "边处理", "R": 6},
            "structural": {"kind": "边处理", "target": "F1"},
            "impl": [("fillet", ("|Z", 6))],
            "drawing": {"annotation": "R6", "view": "plan"},
        },
    ],
}

if __name__ == "__main__":
    print(json.dumps(IR, ensure_ascii=False, indent=2))
