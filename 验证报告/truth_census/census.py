# -*- coding: utf-8 -*-
r"""census.py —— 真值/模型 STEP 的「面普查」，产出可对拍的锚点表

定位：这是「锚点驱动」方案（方案④）的第 1 刀。**不训练、纯解析**——
把 STEP 的每个面拆成解析参数（平面的法线+偏移、圆柱的半径+轴向、圆锥的半角+顶点、
球的半径+球心），两张表就能对拍。

为什么不采样体素：体素比对慢、且不可解释；逐面解析参数又快又能直接读出
「半径 13.9 的圆柱：真值 1 个，我 2 个」这种能指导修图的差异。

用法
----
    python census.py <文件.step> [...]          # 打印汇总表
    python census.py --json <输出目录> <文件…> # 落盘 JSON

产出
----
    每件一个 <名>.census.json：
      {"part":..., "source":..., "solids":n, "faces":n, "volume":..., "bbox":[...],
       "groups": {"cylinder": [...], "plane": [...], "cone": [...], ...}}

隔离约定：只读输入 STEP，不写回；不 import 项目任何模块；不碰 steps/ 与 lib/。
"""
import json
import os
import sys

MATCH_TOL = 0.35   # 对拍时的默认匹配容差（mm）—— 图纸标注四舍五入到 0.1 量级
ANG_TOL = 1e-3


# ---------------------------------------------------------------- 轴向/法向归一
def canon_dir(d):
    """把方向向量归一到「确定的方向」：首个非零分量为正，避免轴向 ±号造成重复组。"""
    comps = [d.X(), d.Y(), d.Z()]
    for c in comps:
        if abs(c) > 1e-6:
            return tuple(round(c if c > 0 else -c, 4) for c in comps)
    return (0.0, 0.0, 0.0)


def _key(tup, ndigits=3):
    return tuple(round(float(t), ndigits) for t in tup)


# ---------------------------------------------------------------- 单面普查
def face_record(face, solid_wrap):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_IN

    ad = BRepAdaptor_Surface(face.wrapped)
    t = ad.GetType()
    bb = face.bounding_box()
    rec = {
        "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
        "area": round(face.area, 4),
    }

    if t == GeomAbs_SurfaceType.GeomAbs_Plane:
        pln = ad.Plane()
        d = canon_dir(pln.Axis().Direction())
        loc = pln.Axis().Location()
        rec["type"] = "plane"
        rec["dir"] = d
        # 平面偏移 = 法线·平面上一点（原点到平面的有向距离）
        rec["offset"] = round(d[0] * loc.X() + d[1] * loc.Y() + d[2] * loc.Z(), 3)

    elif t == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        c = ad.Cylinder()
        d = canon_dir(c.Axis().Direction())
        loc = c.Axis().Location()
        rec["type"] = "cylinder"
        rec["r"] = round(c.Radius(), 3)
        rec["dir"] = d
        # ★ 位置：轴线到原点的**垂直矢量**（对轴上取点不敏感）
        #   早前用 Axis().Location() 的 X/Y 投影是错的：对轴沿 Y 的圆柱，
        #   该点可以离零件很远（外罩 r=24 曾报出 (0,-109.87)，而 bbox 只到 ±24）。
        v = (loc.X(), loc.Y(), loc.Z())
        proj = v[0] * d[0] + v[1] * d[1] + v[2] * d[2]
        rec["axis_rel"] = [round(v[i] - proj * d[i], 3) for i in range(3)]
        rec["axis_r"] = round(sum((v[i] - proj * d[i]) ** 2 for i in range(3)) ** 0.5, 3)
        # ★ 真实轴向长度：圆柱面的 v 参数就是沿轴的毫米数（OCCT 规范参数化）
        try:
            from OCP.BRepTools import BRepTools
            _u0, _u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
            rec["axial_lo"] = round(v0, 3)
            rec["axial_hi"] = round(v1, 3)
            rec["axial_len"] = round(v1 - v0, 3)
        except Exception:
            rec["axial_len"] = round(bb.max.Z - bb.min.Z, 3)
        # ★ 内孔 / 外形柱 分类（用**点分类**，不依赖任何法线朝向约定）
        #   在面上取中点 P，沿径向往轴心挪 δ，得试验点 T：
        #     T 落在材料里  ⇒ 面外侧是空的 ⇒ 这是**外形柱**（boss，图纸标总长/总高）
        #     T 落在空处    ⇒ 面内侧是空的 ⇒ 这是**内孔**（hole，"孔深"概念才成立）
        #   早前用 SLProps.Normal() 判是错的：它给的是**曲面**法线（恒背离轴心），
        #   不含面朝向 ⇒ 全部误判成 boss。改用 MaterialOutside/MaterialInside 由点分类终结。
        rec["form"] = "cylinder"
        try:
            from OCP.BRepClass3d import BRepClass3d_SolidClassifier
            from OCP.BRepLProp import BRepLProp_SLProps
            from OCP.gp import gp_Pnt
            _u0, _u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
            pr = BRepLProp_SLProps(ad, (_u0 + _u1) / 2, (v0 + v1) / 2, 1, 1e-7)
            p = pr.Value()
            ar = rec["axis_rel"]
            rad = (p.X() - ar[0], p.Y() - ar[1], p.Z() - ar[2])
            ax = sum(rad[i] * d[i] for i in range(3))
            rad = tuple(rad[i] - ax * d[i] for i in range(3))     # 去掉轴向分量
            rl = sum(c * c for c in rad) ** 0.5
            if rl > 1e-6:
                delta = min(0.1, rec["r"] / 4.0)
                t = gp_Pnt(p.X() - delta * rad[0] / rl,
                           p.Y() - delta * rad[1] / rl,
                           p.Z() - delta * rad[2] / rl)
                sc = BRepClass3d_SolidClassifier(solid_wrap, t, 1e-7)
                rec["form"] = "boss" if sc.State() == TopAbs_IN else "hole"
        except Exception:
            pass

    elif t == GeomAbs_SurfaceType.GeomAbs_Cone:
        co = ad.Cone()
        d = canon_dir(co.Axis().Direction())
        ap = co.Apex()
        rec["type"] = "cone"
        rec["semi_angle"] = round(abs(co.SemiAngle()), 5)
        rec["dir"] = d
        rec["apex"] = [round(ap.X(), 3), round(ap.Y(), 3), round(ap.Z(), 3)]

    elif t == GeomAbs_SurfaceType.GeomAbs_Sphere:
        sp = ad.Sphere()
        c = sp.Location()
        rec["type"] = "sphere"
        rec["r"] = round(sp.Radius(), 3)
        rec["center"] = [round(c.X(), 3), round(c.Y(), 3), round(c.Z(), 3)]

    elif t == GeomAbs_SurfaceType.GeomAbs_Torus:
        to = ad.Torus()
        c = to.Location()
        rec["type"] = "torus"
        rec["R"] = round(to.MajorRadius(), 3)
        rec["r"] = round(to.MinorRadius(), 3)
        rec["center"] = [round(c.X(), 3), round(c.Y(), 3), round(c.Z(), 3)]

    else:
        # ★ 未解析面（B样条/裁剪面）——**不许编造半径**。
        #   实测：这些面的 UV 域被归一成 [0,1]²，曲率在所有采样点恒为 -1.000000
        #   （退化/合成参数化），拿它反算 R 会给出假值。
        #   如实记为 unresolved，并把面积占比报出来，让盲区可见。
        rec["type"] = "unresolved:%s" % str(t).split(".")[-1].replace("GeomAbs_", "")
        rec["resolved"] = False
    return rec


# ---------------------------------------------------------------- 聚成可对拍的组
def group(records):
    """把同类型的面按**形状参数**归并 —— 对拍时比的是「分布」不是「逐索引」。

    面数不一样是常态（多一个筋就多 3 个面），逐索引比会满屏差异。

    ★ 键只放形状参数，不放位置：
      - 圆柱：半径 + 轴向（位置进 instances）—— 否则每个孔自成一组，分布看不出来
      - 平面：法线 + 偏移 —— 偏移**必须**进键，它是形状参数（"z=52 的平面有没有"正是关键）
      - 球：半径 + 球心（球心是形状参数）
    ★ 归并粒度用 0.01mm。**早前用 5mm 量化是 bug**：会把 r=6.0 与 r=3.25 压成同一个组，
      导致对账 0% 命中、且装配体反查变成假通过。
    """
    Q = 2          # 归并到 0.01mm
    buckets = {}
    for r in records:
        t = r["type"]
        if t == "plane":
            k = ("plane", _key(r["dir"]), round(r["offset"], Q))
        elif t == "cylinder":
            k = ("cylinder", r.get("form", "?"), round(r["r"], Q), _key(r["dir"]))
        elif t == "cone":
            k = ("cone", round(r["semi_angle"], 6), _key(r["dir"]))
        elif t == "sphere":
            k = ("sphere", round(r["r"], Q), _key(r["center"]))
        elif t == "torus":
            k = ("torus", round(r["R"], Q), round(r["r"], Q))
        else:
            k = (t,)
        b = buckets.setdefault(k, {"n": 0, "area": 0.0, "bbox": None, "instances": []})
        b["n"] += 1
        b["area"] += r["area"]
        bb = r["bbox"]
        b["bbox"] = bb if b["bbox"] is None else [
            min(b["bbox"][0], bb[0]), min(b["bbox"][1], bb[1]), min(b["bbox"][2], bb[2]),
            max(b["bbox"][3], bb[3]), max(b["bbox"][4], bb[4]), max(b["bbox"][5], bb[5]),
        ]
        if t == "cylinder":
            b["instances"].append({
                "axis_rel": r.get("axis_rel"),
                "len": r.get("axial_len"),
            })
        elif t == "plane":
            b["instances"].append(round(r["offset"], Q))
    for b in buckets.values():
        b["instances"] = b["instances"][:24]      # 只留前 24 个，避免 JSON 爆掉
    return buckets

# ---------------------------------------------------------------- 主流程
def census(path):
    from build123d import import_step
    s = import_step(path)
    bb = s.bounding_box()
    sw = s.solids()[0].wrapped if s.solids() else s.wrapped
    recs = [face_record(f, sw) for f in s.faces()]
    total_area = sum(r["area"] for r in recs)
    unres_area = sum(r["area"] for r in recs if not r.get("resolved", True))
    return {
        "part": os.path.splitext(os.path.basename(path))[0],
        "source": os.path.abspath(path),
        "solids": len(s.solids()),
        "faces": len(recs),
        "volume": round(s.volume, 3),
        "bbox": [round(v, 3) for v in
                 (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)],
        "types": {t: sum(1 for r in recs if r["type"] == t)
                  for t in sorted({r["type"] for r in recs})},
        # ★ 盲区量化：未解析面（B样条）的面积占比 —— 这些面里可能藏着 R 标注
        "unresolved": {
            "faces": sum(1 for r in recs if not r.get("resolved", True)),
            "area": round(unres_area, 3),
            "area_frac": round(unres_area / total_area, 4) if total_area else 0.0,
        },
        "groups": {"|".join(str(x) for x in k): v for k, v in group(recs).items()},
    }


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    as_json = False
    if argv[0] == "--json":
        as_json = True
        outdir = argv[1]
        argv = argv[2:]
        os.makedirs(outdir, exist_ok=True)

    print("%-18s %6s %6s %12s  %s" % ("part", "solids", "faces", "volume", "面类型分布"))
    print("-" * 78)
    for p in argv:
        try:
            c = census(p)
        except Exception as e:
            print("%-18s  FAIL  %s" % (os.path.basename(p)[:18], str(e)[:40]))
            continue
        dist = " ".join("%s×%d" % (k.replace("GeomAbs_", ""), v)
                        for k, v in sorted(c["types"].items(),
                                           key=lambda kv: -kv[1]))
        print("%-18s %6d %6d %12.1f  %s"
              % (c["part"][:18], c["solids"], c["faces"], c["volume"], dist))
        if as_json:
            with open(os.path.join(outdir, c["part"] + ".census.json"), "w",
                      encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
