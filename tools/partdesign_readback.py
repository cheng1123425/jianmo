# -*- coding: utf-8 -*-
r"""tools/partdesign_readback.py —— FreeCAD PartDesign ──▶ 回读 IR（E）
=====================================================================

D（`tools/ir2partdesign.py`）把 IR 物化成 FreeCAD 真特征树。本工具走**反方向**：

    FCStd ──[打开]──▶ 读特征树(Sketch/Pad/Pocket) + Spreadsheet 参数
                  ──▶ 映射回 IR 结构（feature: fid / tree op / 绑定参数）
                  ──▶ 演示「改 Spreadsheet 单元格 → recompute → 实体跟着变」
                  ──▶ 演示「圆柱面 → 几何谓词 {kind:circle,r,center}」（选边翻谓词）

这就是路线文档 **E** 阶段（FreeCAD 交互面回写 IR 的前半段）。用户在 FreeCAD GUI 里
手改参数 → 本工具把改动读回 IR → 再由 C/D 重生成，两端因此能对上。

跑法（需在 FreeCAD 无头环境）：
    "D:\\cad2024\\FreeCAD 1.1\\bin\\freecadcmd.exe" tools/partdesign_readback.py
脚本内硬编码输入/输出路径（freecadcmd 不透传命令行参数——见项目坑点记录）。

隔离：算法层（tools/），只读 FCStd、写 JSON 报告，不改 FCStd（除非显式开 demo）。
"""

import json
import os
import traceback

# ---- 硬编码路径（freecadcmd 不透传 argv）----
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FCSTD = os.path.join(ROOT, "_pd_tmp", "lbracket_pd.FCStd")
OUT_JSON = os.path.join(ROOT, "_pd_tmp", "readback.json")
IR_JSON = os.path.join(ROOT, "parts", "lbracket", "ir.json")

report = {}

try:
    import FreeCAD as App

    doc = App.openDocument(FCSTD)
    body = None
    sheet = None
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body":
            body = o
        elif o.TypeId == "Spreadsheet::Sheet":
            sheet = o
    if body is None:
        raise RuntimeError("FCStd 里没有 PartDesign Body")

    # ---- 1. 读 Spreadsheet 参数表 ----
    params = []
    if sheet is not None:
        r = 2
        while True:
            fid = sheet.get("A%d" % r) if sheet.getContents("A%d" % r) else None
            if not fid:
                break
            params.append({"fid": fid, "param": sheet.get("B%d" % r),
                           "value": sheet.get("C%d" % r), "cell": "C%d" % r})
            r += 1
    report["spreadsheet_params"] = params

    # ---- 2. 读特征树 → 映射回 IR 结构 ----
    feats = []
    for o in body.Group:
        tid = o.TypeId.split("::")[-1]
        if tid in ("Pad", "Pocket"):
            fid = o.Name.split("_")[-1]
            prof = getattr(o, "Profile", None)
            if isinstance(prof, (tuple, list)):   # FreeCAD 返回 (obj, [subs])
                prof = prof[0] if prof else None
            entry = {"fid": fid, "tree_op": tid,
                     "length": round(o.Length.Value, 3) if hasattr(o, "Length") else None,
                     "reversed": getattr(o, "Reversed", None),
                     "profile": getattr(prof, "Name", None)}
            feats.append(entry)
    report["feature_tree"] = feats

    # ---- 3. 与原始 IR 对照 ----
    if os.path.exists(IR_JSON):
        with open(IR_JSON, encoding="utf-8") as f:
            ir = json.load(f)
        ir_map = {f["id"]: (f.get("tree") or [None])[-1][0] for f in ir.get("features", [])}
        report["ir_tree_map"] = ir_map
        report["tree_matches_ir"] = all(
            e["tree_op"] == ir_map.get(e["fid"]) for e in feats)

    # ---- 4. 演示：改 Spreadsheet 单元格 → recompute → 体积变 ----
    vol_before = round(body.Shape.Volume, 3)
    demo = {"volume_before": vol_before}
    # 找一个 Pad 的 Length 单元格做联动演示
    target = None
    for p in params:
        if p["param"] == "Length":
            target = p
            break
    if target is not None and sheet is not None:
        old = sheet.get(target["cell"])
        newv = round(float(old) + 3.0, 3)
        sheet.set(target["cell"], repr(newv))
        doc.recompute()
        demo.update({"edited": {"fid": target["fid"], "cell": target["cell"],
                                "old": old, "new": newv},
                     "volume_after": round(body.Shape.Volume, 3)})
        demo["volume_changed"] = (demo["volume_after"] != vol_before)
        # 复原
        sheet.set(target["cell"], repr(old))
        doc.recompute()
        demo["volume_restored"] = round(body.Shape.Volume, 3)
    report["param_edit_demo"] = demo

    # ---- 5. 演示：圆柱面 → 几何谓词（选边翻谓词）----
    preds = []
    try:
        for i, f in enumerate(body.Shape.Faces):
            surf = f.Surface
            if hasattr(surf, "Radius") and str(type(surf)).find("Cylinder") >= 0:
                c = surf.Center
                preds.append({"kind": "circle", "r": round(surf.Radius, 4),
                              "center": [round(c.x, 3), round(c.y, 3), round(c.z, 3)],
                              "axis": [round(surf.Axis.x, 3), round(surf.Axis.y, 3),
                                       round(surf.Axis.z, 3)]})
            if len(preds) >= 4:
                break
    except Exception:
        pass
    report["circle_predicates"] = preds
    report["ok"] = True
except Exception:
    report["ok"] = False
    report["error"] = traceback.format_exc()[-1200:]

try:
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
except Exception:
    pass