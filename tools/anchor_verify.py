# -*- coding: utf-8 -*-
r"""tools/anchor_verify.py —— 2D↔3D 语义锚点校核（G 阶段 · 闭环校核升级）
=====================================================================

给 `parts/*/ir_anchors.json` 里的每个锚点做两项校核（路线文档 §2.2）：

    ① 绑定存在性：按几何谓词（圆半径 / 整体范围 / 同径圆间距）能否在投影里定位到边；
    ② 指对性：定位到的边**实测几何** vs 锚点声明的期望值（expected）。

这补上了原闭环的两个盲区：
  * 原 `s6_compare` 只比 FreeCAD 的标注值（`dims`），**不看图上印的字**；
  * 且**从不校验"这个标注绑的边对不对"**——只要有一个 r=4 的圆就算过。

跑法（freecadcmd 无头；路径硬编码，因 freecadcmd 不透传 argv）：
    "D:\\3d\\新建文件夹\\FreeCAD 1.1\\bin\\freecadcmd.exe" tools/anchor_verify.py

隔离：算法层（tools/），只读 STEP + anchors，写 JSON 报告，不改任何源文件。
"""
import json
import os
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 与各零件 s2_drawing 的 VIEW_SPECS 保持一致（scale 固定 1.0：谓词按模型 mm，不受缩放干扰）
VIEW_DIRS = {
    "Top":   dict(dir=(0, 0, 1),  xdir=None),
    "Front": dict(dir=(0, -1, 0), xdir=None),
    "Right": dict(dir=(1, 0, 0),  xdir=(0, 1, 0)),
}

TEMPLATE = r"D:\3d\新建文件夹\FreeCAD 1.1\data\Mod\TechDraw\Templates\ISO\A3_Landscape_TD.svg"

TOL = 0.51   # 指对性判定容差(mm)：与 ref_spec.TOL=0.6 同量级，略严


def _view_geom(view):
    """从视图的可见边提取：① 圆列表[(r,cx,cy)] ② 整体范围 {'x':(min,max),'y':(min,max)}"""
    circles = []
    xs, ys = [], []
    for e in view.getVisibleEdges():
        c = e.Curve
        if "Circle" in c.__class__.__name__:
            circles.append((float(c.Radius), float(c.Center.x), float(c.Center.y)))
        # 采样端点与中点，累积整体范围（circle 的采样点也在其上，天然覆盖）
        try:
            f0, f1 = e.FirstParameter, e.LastParameter
            for t in (f0, (f0 + f1) / 2.0, f1):
                p = e.valueAt(t)
                xs.append(float(p.x)); ys.append(float(p.y))
        except Exception:
            pass
    extent = None
    if xs and ys:
        extent = {"x": (min(xs), max(xs)), "y": (min(ys), max(ys))}
    return circles, extent


def verify(anchors, views, ):
    results = []
    for a in anchors:
        label = a.get("label")
        view_name = a.get("view")
        geom = a.get("geom") or {}
        expected = a.get("expected")
        rec = {"label": label, "fid": a.get("fid"), "view": view_name,
               "dim_kind": a.get("dim_kind"), "geom": geom, "expected": expected}
        if view_name not in views:
            rec.update({"exists": False, "pass": False, "why": "视图不存在"})
            results.append(rec); continue
        circles, extent = views[view_name]
        kind = geom.get("kind")
        try:
            if kind == "extent":
                axis = geom.get("axis", "x")
                if not extent:
                    rec.update({"exists": False, "pass": False, "why": "视图无几何"}); results.append(rec); continue
                lo, hi = extent[axis]
                measured = hi - lo
                rec.update({"exists": True, "measured": round(measured, 3),
                            "range": [round(lo, 3), round(hi, 3)]})
            elif kind == "circle":
                want = float(geom.get("r"))
                hit = [c for c in circles if abs(c[0] - want) < 0.3]
                if not hit:
                    rec.update({"exists": False, "pass": False,
                                "why": "没找到 r=%.2f 的圆" % want,
                                "circles_found": [[round(x, 3) for x in c] for c in circles]})
                    results.append(rec); continue
                # 指对性：直径 = 2r 与期望比；并记录命中的圆心供人工核对是"哪个"孔
                measured = 2.0 * hit[0][0]
                rec.update({"exists": True, "measured": round(measured, 3),
                            "n_matched": len(hit),
                            "centers": [[round(c[1], 3), round(c[2], 3)] for c in hit]})
            elif kind == "level_pair":
                want = float(geom.get("r"))
                axis = geom.get("axis", "x")
                hit = [c for c in circles if abs(c[0] - want) < 0.3]
                if len(hit) < 2:
                    rec.update({"exists": False, "pass": False,
                                "why": "同径圆不足 2 个(找到%d)" % len(hit)})
                    results.append(rec); continue
                cs = sorted(c[1] if axis == "x" else c[2] for c in hit)
                measured = cs[-1] - cs[0]
                rec.update({"exists": True, "measured": round(measured, 3),
                            "coords": [round(v, 3) for v in cs]})
            else:
                rec.update({"exists": False, "pass": False, "why": "未知谓词 %r" % kind})
                results.append(rec); continue
            # 指对性判定
            if expected is not None:
                ok = abs(rec["measured"] - float(expected)) <= TOL
                rec["pass"] = bool(ok)
                rec["delta"] = round(rec["measured"] - float(expected), 3)
            else:
                rec["pass"] = None
        except Exception:
            rec.update({"exists": None, "pass": False,
                        "why": traceback.format_exc()[-200:]})
        results.append(rec)
    return results


def main():
    import FreeCAD as App
    import Part
    import glob

    out_json = os.path.join(ROOT, "_pd_tmp", "anchor_verify.json")
    report = {"parts": {}, "tol": TOL}

    # 遍历所有带 ir_anchors.json 的零件（通用：不硬编码具体零件）
    anchor_files = sorted(glob.glob(os.path.join(ROOT, "parts", "*", "ir_anchors.json")))
    for af in anchor_files:
        part = os.path.basename(os.path.dirname(af))
        step = os.path.join(ROOT, "parts", part, "models", part + ".step")
        if not os.path.exists(step):
            report["parts"][part] = {"error": "缺 STEP %s" % step}
            continue
        with open(af, encoding="utf-8") as f:
            anchors = json.load(f)["anchors"]

        doc = App.newDocument("av_" + part)
        shape = Part.Shape(); shape.read(step)
        obj = doc.addObject("Part::Feature", "part"); obj.Shape = shape
        page = doc.addObject("TechDraw::DrawPage", "Page")
        tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        tpl.Template = TEMPLATE
        page.Template = tpl
        views = {}
        for name, spec in VIEW_DIRS.items():
            v = doc.addObject("TechDraw::DrawViewPart", "V" + name)
            v.Source = [obj]
            v.Direction = spec["dir"]
            if spec["xdir"]:
                v.XDirection = spec["xdir"]
            page.addView(v)
            v.Scale = 1.0
            views[name] = v
        doc.recompute()
        geom_cache = {name: _view_geom(v) for name, v in views.items()}

        results = verify(anchors, geom_cache)
        report["parts"][part] = {
            "n_anchors": len(anchors),
            "n_exist": sum(1 for r in results if r.get("exists")),
            "n_pass": sum(1 for r in results if r.get("pass")),
            "results": results,
        }
        App.closeDocument(doc.Name)

    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


try:
    main()
except Exception:
    r = {"fatal": traceback.format_exc()[-1500:]}
    try:
        with open(os.path.join(ROOT, "_pd_tmp", "anchor_verify.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
    except Exception:
        pass