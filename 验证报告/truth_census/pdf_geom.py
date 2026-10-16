# -*- coding: utf-8 -*-
r"""pdf_geom.py —— 从矢量 PDF 抽**带图层的线几何**

为什么必须要这一步：视图分区做不出来，是因为**文字太稀疏**——视图边界在**线**里。
而矢量 PDF 白送了栅格路线要靠线宽去猜的东西：
  * 每条图元带**图层**（`/OC /ocN BDC` → ocN → 图层名）
  * 线宽（`w`）、颜色（`RG`）
  * 线段精确坐标（PDF 坐标 = 物理尺寸，1pt = 1/72 inch）

实测（外罩）：图层 5 个 —— 粗实线层 / 剖面线层 / 中心线层 / 尺寸线层 / 细实线层。
**粗实线层 = 可见轮廓** ⇒ 拿它聚类就是视图分区。

用法
    python pdf_geom.py <文件.pdf> [...]              # 打印图层统计
    python pdf_geom.py --json <出目录> <文件…>       # 落盘 <名>.geom.json

纪律：只读，不改；规则一次写定。
"""
import json
import os
import re
import sys
import warnings

# ---------------------------------------------------------------- 矩阵（PDF 行向量约定）
def mat_mul(a, b):
    """(x,y) → (a0*x + a2*y + a4, a1*x + a3*y + a5)"""
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


IDENT = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

# ---------------------------------------------------------------- 词法
TOK = re.compile(rb"""
      <[0-9A-Fa-f\s]*>              # hex string
    | \[ | \]                      # array delimiters
    | /[^\s/\[\]()<>{}]*           # name
    | \( (?: \\. | [^\\()] )* \)   # literal string
    | [-+]?(?:\d+\.\d*|\.\d+|\d+)  # number
    | [A-Za-z'"*][A-Za-z0-9'"*]*   # operator
""", re.X | re.S)

PAINT = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
STROKE = {b"S", b"s", b"B", b"B*", b"b", b"b*"}


def _num(b):
    try:
        return float(b)
    except ValueError:
        return None


def parse_stream(data, layer_map, ctm0=None):
    """解析内容流 → 线段列表。"""
    segs = []
    st = {"ctm": list(ctm0 or IDENT), "lw": 1.0, "rgb": (0.0, 0.0, 0.0),
          "layer": None, "q": []}
    stack = []
    cur = []                       # 当前路径的点（已变换）
    start = None
    in_text = False
    reading = []                   # 操作数缓冲区

    def T(p):
        m = st["ctm"]
        return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])

    def flush(paint):
        """★ cur 里存的是**内容坐标原始点**；变换放在这里统一做。
        早期在 append 时就变换，导致贝塞尔的控制点（内容坐标）与端点（页面坐标）
        量纲不一致 —— 曲线会算错。"""
        nonlocal cur, start
        if paint in STROKE and len(cur) >= 2:
            tp = [T(p) for p in cur]
            for a, b in zip(tp, tp[1:]):
                segs.append({"p1": [round(a[0], 2), round(a[1], 2)],
                             "p2": [round(b[0], 2), round(b[1], 2)],
                             "lw": round(st["lw"], 3),
                             "rgb": [round(c, 3) for c in st["rgb"]],
                             "layer": st["layer"]})
        cur, start = [], None

    for m in TOK.finditer(data):
        t = m.group(0)
        if t[:1] in b"0123456789+-.[/<(":
            reading.append(t)
            continue
        op = t
        nums = [n for n in (_num(x) for x in reading) if n is not None]
        names = [x[1:] for x in reading if x[:1] == b"/"]
        reading = []

        if op == b"q":
            stack.append(dict(st))
        elif op == b"Q":
            if stack:
                st = stack.pop()
        elif op == b"cm" and len(nums) >= 6:
            st["ctm"] = mat_mul(st["ctm"], nums[-6:])
        elif op == b"w" and nums:
            st["lw"] = nums[-1]
        elif op in (b"RG", b"rg") and len(nums) >= 3:
            st["rgb"] = tuple(nums[-3:])
        elif op == b"BDC" and names:
            # /OC /ocN BDC —— 名字表形如 [b'OC', b'ocN']。
            # ★ 坑：词法器给的是 bytes，而 layer_map 的键是 str —— 必须 decode，
            #   否则 `b'oc1' in {'oc1':…}` 恒为 False，图层会全部丢失（踩过）。
            for nm in names:
                key = nm.decode("latin1") if isinstance(nm, bytes) else nm
                if key in layer_map:
                    st["layer"] = layer_map[key]
                    break
        elif op == b"EMC":
            st["layer"] = None
        elif op == b"BT":
            in_text = True
        elif op == b"ET":
            in_text = False
        elif op in (b"m", b"l") and len(nums) >= 2 and not in_text:
            p = (nums[-2], nums[-1])          # 原始（内容坐标）
            if op == b"m":
                cur = [p]
            else:
                if not cur:
                    cur = [p]
                else:
                    cur.append(p)
        elif op == b"re" and len(nums) >= 4 and not in_text:
            x, y, w, h = nums[-4:]
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            cur = pts + [pts[0]]
        elif op in (b"c", b"v", b"y") and len(nums) >= 4 and not in_text:
            # 曲线必须**离散化**，不能只取末端点。
            #   踩过的坑：圆是用 4 段四分之一贝塞尔（`c`）画的；早期只取每段末端点，
            #   4 段塌成 4 个点 ⇒ 圆被读成**正方形**（合金管垫片实测：
            #   Ø12 读成半对角 80.1 的方块、Ø6.5 读成 43.35 的方块，比值 1.848 才对）。
            #   PDF 定义：c=(c1,c2,end)  v=(c1=当前点,c2,end)  y=(c1,c2=end,end)
            if not cur:
                continue
            p0 = cur[-1]
            if op == b"c":
                a, bb, e = (nums[-6], nums[-5]), (nums[-4], nums[-3]), (nums[-2], nums[-1])
            elif op == b"v":
                a, bb, e = p0, (nums[-4], nums[-3]), (nums[-2], nums[-1])
            else:                                   # y
                a, bb, e = (nums[-4], nums[-3]), (nums[-2], nums[-1]), (nums[-2], nums[-1])
            for k in range(1, 9):                   # 8 段离散
                t = k / 8.0
                mt = 1.0 - t
                cur.append((mt ** 3 * p0[0] + 3 * mt ** 2 * t * a[0]
                            + 3 * mt * t ** 2 * bb[0] + t ** 3 * e[0],
                            mt ** 3 * p0[1] + 3 * mt ** 2 * t * a[1]
                            + 3 * mt * t ** 2 * bb[1] + t ** 3 * e[1]))
        elif op in PAINT:
            flush(op)
        elif op == b"n":
            cur, start = [], None
        elif op == b"W":
            # 裁剪路径：后续 n 会清掉，且不属 STROKE ⇒ 不会被吐出
            pass
    return segs


# ---------------------------------------------------------------- 入口
def _resolve(obj):
    """pypdf 的 IndirectObject 要显式 get_object()，否则取不到键值。"""
    return obj.get_object() if hasattr(obj, "get_object") else obj


def layer_map_of(page):
    # ★ 坑：page.get("/Resources") 拿到的是 IndirectObject，直接 .get("/Properties") 会拿空
    #   （曾因此让 1246 条线段的图层全部变成「无图层」）。必须逐级 get_object()。
    res = _resolve(page.get("/Resources", {}))
    props = _resolve(res.get("/Properties")) if hasattr(res, "get") else None
    out = {}
    for k, v in (props or {}).items():
        try:
            nm = _resolve(v).get("/Name")
            if nm:
                out[str(k).lstrip("/")] = str(nm)
        except Exception:
            pass
    return out


def geometry_of(pdf_path):
    warnings.filterwarnings("ignore")
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    page = reader.pages[0]
    lmap = layer_map_of(page)
    try:
        data = page.get_contents().get_data()
    except Exception:
        data = b""
    segs = parse_stream(data, lmap)

    # ---- ★ 图层回退：没有 BDC 图层标记时，按【颜色 + 线宽】推断 ----
    #   实测有两类 PDF：
    #     A 类（如 sj-010/012）：页面 /Resources/Properties 有 oc1..ocN，内容流带
    #       `/OC /ocN BDC` ⇒ 直接拿图层名。
    #     B 类（如 sj-001/002）：文档 /OCProperties 有图层定义，但**页面 /Properties 缺失、
    #       内容流 0 个 BDC** ⇒ 图层信息根本没写进内容（出图时没勾）。
    #   但两类的**颜色与线宽约定完全一致**（实测 13 件）：
    #       绿(0,1,0)=尺寸线层  红(1,0,0)=中心线层  青(0,1,1)=剖面线层
    #       黑且线宽最大 = 粗实线层（可见轮廓）    其余黑细 = 细实线层
    #   于是 B 类可以安全回退，两类走同一条下游。
    mx = max([s["lw"] for s in segs], default=0.0)

    def infer(s):
        r, g, b = s["rgb"]
        if g > 0.5 and r < 0.3 and b < 0.3:
            return "尺寸线层"
        if r > 0.5 and g < 0.3 and b < 0.3:
            return "中心线层"
        if g > 0.5 and b > 0.5 and r < 0.3:
            return "剖面线层"
        if r < 0.1 and g < 0.1 and b < 0.1 and s["lw"] >= mx * 0.8 and mx > 0:
            return "粗实线层"
        return "细实线层"

    n_inferred = 0
    for s in segs:
        if not s.get("layer"):
            s["layer"] = infer(s)
            n_inferred += 1

    stats = {}
    for s in segs:
        k = s["layer"] or "(无图层)"
        d = stats.setdefault(k, {"n": 0, "lw": {}, "rgb": {}})
        d["n"] += 1
        d["lw"][str(s["lw"])] = d["lw"].get(str(s["lw"]), 0) + 1
        rc = ",".join(str(c) for c in s["rgb"])
        d["rgb"][rc] = d["rgb"].get(rc, 0) + 1

    xs = [p for s in segs for p in (s["p1"][0], s["p2"][0])]
    ys = [p for s in segs for p in (s["p1"][1], s["p2"][1])]
    return {
        "part": os.path.splitext(os.path.basename(pdf_path))[0],
        "source": os.path.abspath(pdf_path),
        "layer_map": lmap,
        "n_segments": len(segs),
        "layer_source": "bdc" if n_inferred == 0 else
                         ("inferred" if n_inferred == len(segs) else "mixed"),
        "extent": [round(min(xs), 2), round(min(ys), 2),
                   round(max(xs), 2), round(max(ys), 2)] if segs else None,
        "layers": {k: {"n": v["n"],
                       "lw": sorted(v["lw"].items(), key=lambda kv: -kv[1])[:3],
                       "rgb": sorted(v["rgb"].items(), key=lambda kv: -kv[1])[:2]}
                   for k, v in sorted(stats.items(), key=lambda kv: -kv[1]["n"])},
        "segments": segs,
    }



# ---------------------------------------------------------------- 视图分区
def cluster_views(segs, layer="粗实线层", tol_frac=0.02):
    """用**粗实线层**（可见轮廓）做连通聚类 → 视图分区。

    依据：机械制图的三个基本视图在图纸上是**彼此分离的图形块**，
    轮廓之间没有连线 ⇒ 按端点距离做连通聚类，自然分出视图。
    这是栅格路线要靠线宽聚类去猜、而矢量路线白送图层才能稳做的一步。
    """
    pts = [s for s in segs if s.get("layer") == layer]
    if not pts:
        return []
    xs = [v for s in pts for v in (s["p1"][0], s["p2"][0])]
    ys = [v for s in pts for v in (s["p1"][1], s["p2"][1])]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    tol = span * tol_frac

    par = list(range(len(pts)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            par[a] = b

    # 端点网格哈希，避免 O(n^2)
    cell = max(tol, 1e-6)
    grid = {}
    def key(p):
        return (int(p[0] // cell), int(p[1] // cell))

    for i, s in enumerate(pts):
        for p in (s["p1"], s["p2"]):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    k = (key(p)[0] + dx, key(p)[1] + dy)
                    for j in grid.get(k, ()):
                        q = pts[j]
                        for a in (q["p1"], q["p2"]):
                            if abs(a[0] - p[0]) <= tol and abs(a[1] - p[1]) <= tol:
                                union(i, j)
        for p in (s["p1"], s["p2"]):
            grid.setdefault(key(p), []).append(i)

    # ---- 第二遍：**嵌套且同心**的组才合并 ----
    #   为什么需要：同心圆的端点不接触，纯端点连通会把同一个视图里的
    #   外圆与内孔圆拆成两块（实测合金管垫片：Ø12 的 160 方块与 Ø6.5 的 86.7 方块，
    #   而 160×6.5/12 = 86.7 正说明它们同心）。
    #   ★ 判据必须收窄成「嵌套 + 同心」：
    #     先试过「bbox 相交就合并」，**过头了** —— 图纸边框的 bbox 包含一切，
    #     结果整张图被并成一块（外罩 490 段全进一块）。边框与视图只是包含、不同心。
    def groups_of():
        g = {}
        for i in range(len(pts)):
            g.setdefault(find(i), []).append(i)
        return {gid: (min(v for i in idxs for v in (pts[i]["p1"][0], pts[i]["p2"][0])),
                      min(v for i in idxs for v in (pts[i]["p1"][1], pts[i]["p2"][1])),
                      max(v for i in idxs for v in (pts[i]["p1"][0], pts[i]["p2"][0])),
                      max(v for i in idxs for v in (pts[i]["p1"][1], pts[i]["p2"][1])),
                      len(idxs))
                for gid, idxs in g.items()}

    def area(b):
        return max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))

    for _ in range(8):
        bb = groups_of()
        ids = sorted(bb, key=lambda k: -area(bb[k]))
        merged = False
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                A, B = bb[ids[a]], bb[ids[b]]
                big, small = (A, B) if area(A) >= area(B) else (B, A)
                # 嵌套：小的完全落在大的里面（留 2% 余量）
                eps = 0.02 * max(big[2] - big[0], big[3] - big[1])
                inside = (small[0] >= big[0] - eps and small[1] >= big[1] - eps
                          and small[2] <= big[2] + eps and small[3] <= big[3] + eps)
                if not inside:
                    continue
                # 同心：两组中心很接近
                dcx = abs((small[0] + small[2]) - (big[0] + big[2])) / 2.0
                dcy = abs((small[1] + small[3]) - (big[1] + big[3])) / 2.0
                tol_c = 0.15 * max(small[2] - small[0], small[3] - small[1], 1.0)
                if dcx <= tol_c and dcy <= tol_c:
                    union(ids[a], ids[b])
                    merged = True
        if not merged:
            break

    # ---- 第三遍：剥掉图纸边框 ----
    #   边框的 bbox 大、且**包含**其他块的中线；判据：面积最大 且 包含 ≥2 个别的块的中心。
    bb = groups_of()
    ids = sorted(bb, key=lambda k: -area(bb[k]))
    frame = None
    if len(ids) >= 3:
        cand = bb[ids[0]]
        contained = 0
        for k in ids[1:]:
            o = bb[k]
            cx, cy = (o[0] + o[2]) / 2.0, (o[1] + o[3]) / 2.0
            if (cand[0] <= cx <= cand[2]) and (cand[1] <= cy <= cand[3]):
                contained += 1
        if contained >= 2:
            frame = ids[0]

    groups = {}
    for i in range(len(pts)):
        groups.setdefault(find(i), []).append(i)

    views = []
    for gid, idxs in groups.items():
        if frame is not None and gid == frame:
            continue
        gx = [v for i in idxs for v in (pts[i]["p1"][0], pts[i]["p2"][0])]
        gy = [v for i in idxs for v in (pts[i]["p1"][1], pts[i]["p2"][1])]
        views.append({"n_seg": len(idxs),
                      "bbox": [round(min(gx), 1), round(min(gy), 1),
                               round(max(gx), 1), round(max(gy), 1)],
                      "w": round(max(gx) - min(gx), 1),
                      "h": round(max(gy) - min(gy), 1)})
    views.sort(key=lambda v: -v["n_seg"])
    return views


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    as_json = argv[0] == "--json"
    outdir = argv[1] if as_json else None
    files = argv[2:] if as_json else argv
    if as_json:
        os.makedirs(outdir, exist_ok=True)
    show_views = os.environ.get("GEOM_VIEWS") == "1"

    for p in files:
        try:
            g = geometry_of(p)
        except Exception as e:
            print("%-26s FAIL %s" % (os.path.basename(p)[:26], str(e)[:44]))
            continue
        print("=== %s ===  %d 段  范围 %s" % (g["part"][:26], g["n_segments"], g["extent"]))
        for k, v in g["layers"].items():
            print("    %-10s n=%-6d 线宽%s 色%s" % (k, v["n"], v["lw"], v["rgb"]))
        if show_views:
            vs = cluster_views(g["segments"])
            print("    ★ 粗实线层聚类 → %d 个视图块" % len(vs))
            for i, v in enumerate(vs[:8]):
                print("       视图%d  %s  宽%.1f 高%.1f  段%d"
                      % (i, v["bbox"], v["w"], v["h"], v["n_seg"]))
        if as_json:
            with open(os.path.join(outdir, g["part"] + ".geom.json"), "w",
                      encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
