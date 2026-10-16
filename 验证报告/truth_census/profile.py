# -*- coding: utf-8 -*-
r"""profile.py —— 视图轮廓提取 + 拉伸/回转 → 实体

这是把「环形件专用」升级成**通用路线**的一步：

    视图块（粗实线层）
      → 端点归并成图（顶点 + 边）
      → 走外边界环（左侧优先的墙面跟随）
      → 多边形剖面
      → 拉伸（棱柱件）或回转（轴类件）
      → 实体

为什么必须做：12 件里只有 3~4 件是环形件（垫圈类），
其余是板类（顶部垫片 50×50×4）、块类（抗剪块 70×6×45）、
轴类（切槽螺栓）、复杂体（底座 60×48×40）。把它们硬塞进"垫圈"模具必然失败。

配对法则（投影原则的直接应用）：
    · **长对正** ⇒ 主视图与俯视图的 **X 跨度相等** ⇒ 这一对里，
      面积大的当剖面，另一个的"另一个方向"就是**厚度**。
    · **高平齐** ⇒ 主视图与侧视图的 **Y 跨度相等**。
"""
import math

TOL_FRAC = 0.012          # 端点归并容差 = 视图跨度 × 该比例


def _merge_vertices(segs, tol):
    """端点按距离归并成顶点表，返回 (verts, edges)，edges 为 (i, j) 索引对。"""
    verts = []
    cell = max(tol, 1e-6)
    grid = {}

    def find_or_add(p):
        kx, ky = int(p[0] // cell), int(p[1] // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in grid.get((kx + dx, ky + dy), ()):
                    v = verts[idx]
                    if abs(v[0] - p[0]) <= tol and abs(v[1] - p[1]) <= tol:
                        return idx
        verts.append(p)
        grid.setdefault((kx, ky), []).append(len(verts) - 1)
        return len(verts) - 1

    edges = set()
    for s in segs:
        a = find_or_add(tuple(s["p1"]))
        b = find_or_add(tuple(s["p2"]))
        if a != b:
            edges.add((min(a, b), max(a, b)))
    return verts, sorted(edges)


def trace_outer_loop(segs):
    """走外边界环，返回有序顶点列表（逆时针），失败返回 None。

    做法：从**最左下**的顶点出发（它必在外边界上），用"始终取最靠左的下一跳"
    的墙面跟随法走一圈 —— 这样得到的是**外轮廓**，内部线（台阶线、孔）被绕过。
    """
    if not segs:
        return None
    xs = [v for s in segs for v in (s["p1"][0], s["p2"][0])]
    ys = [v for s in segs for v in (s["p1"][1], s["p2"][1])]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    tol = span * TOL_FRAC

    verts, edges = _merge_vertices(segs, tol)
    if len(verts) < 3:
        return None
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    start = min(adj, key=lambda i: (verts[i][0], verts[i][1]))
    loop = [start]
    prev = None
    cur = start
    for _ in range(len(edges) * 3 + 10):
        nbrs = [n for n in adj.get(cur, []) if n != prev]
        if not nbrs:
            nbrs = adj.get(cur, [])
        if not nbrs:
            return None
        if prev is None:
            nxt = min(nbrs, key=lambda n: math.atan2(verts[n][1] - verts[cur][1],
                                                     verts[n][0] - verts[cur][0]))
        else:
            base = math.atan2(verts[prev][1] - verts[cur][1],
                              verts[prev][0] - verts[cur][0])
            def turn(n):
                a = math.atan2(verts[n][1] - verts[cur][1],
                               verts[n][0] - verts[cur][0])
                d = (a - base) % (2 * math.pi)
                return d if d > 1e-9 else 2 * math.pi
            nxt = min(nbrs, key=turn)
        loop.append(nxt)
        prev, cur = cur, nxt
        if cur == start:
            break
    if len(loop) < 4 or loop[-1] != start:
        return None
    return [verts[i] for i in loop[:-1]]


def poly_area(poly):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def faces_of(segs):
    """平面图 → 所有面（**半边遍历**，标准做法）。返回 `(faces, verts)`。

    `faces = [(顶点索引环, 有向面积), ...]`，有向面积为正 = 逆时针环。

    ## 为什么不用 `trace_outer_loop`

    `trace_outer_loop` 是"单起点 + 最左转墙面跟随"，**只在沿程没有分叉、且起点恰在外边界上时**才正确。
    实测 8 件 extrude（`prof` 视图）：

    | 件 | 分支点 | 旧走环结果 |
    |---|---|---|
    | sj-002 | 0 | 12 点、面积占视图 100% ✓ |
    | sj-008 | 0 | **4 点、面积 0** ✗ |
    | sj-003 | 16 | 82 点、**面积 0** ✗ |
    | sj-006 | 1 | 56 点、**面积 0** ✗ |
    | sj-007 | 8 | 8 点、面积占视图 100%（真值截面只有 64%）✗ |

    ⇒ 一旦图里出现分叉（视图内的孔、凸台、台阶线都会造成分叉），
    单路径跟随会走岔或走进退化环。**半边遍历**为每条边建两个方向、
    在每个顶点按角度排序出边，再逐条未用半边走，能**完整枚举所有面**，
    与分叉无关。

    ## 算法

    1. 每个顶点的出边**按极角排序**；
    2. 对每条半边 `(u,w)`，在 `w` 处取 `adj[w]` 里 `u` 的**下一条**（最左转）作为后续 ⇒ 每个面被逆时针绕一圈；
    3. 未被访问过的半边各自成一个面。
    """
    if not segs:
        return [], []
    xs = [v for s in segs for v in (s["p1"][0], s["p2"][0])]
    ys = [v for s in segs for v in (s["p1"][1], s["p2"][1])]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    verts, edges = _merge_vertices(segs, span * TOL_FRAC)
    if len(verts) < 3:
        return [], verts

    # ★ **闭合开放轮廓**（与 `readops.loop_of` 的"滤除文字组"配合使用）。
    #
    # 制图规范：半剖分界是点画线、局部剖分界是波浪线（`section-analysis.md` §1），
    # 两者**都不在粗实线层** ⇒ 粗实线层上的轮廓本就可能是开放的"大部分"；
    # §4 表给的对应做法是「**形体对称 ⇒ 画一半 + 镜像**」。
    # 判据：图里恰好 2 个度为 1 的顶点 ⇒ 开放路径 ⇒ 首尾连一条边（等价于镜像到对称面）。
    #
    # 实测（三件同时受影响，做了三版分离对比）：
    #   | 方案       | sj-003  | sj-006   | sj-008  |
    #   | 不滤文字   | +362.55 | +162.55  | +162.13 |
    #   | 滤、不闭合 | +1052.3 | **−95.42** | **−8.05** |
    #   | 滤 + 闭合  | +735.36 | **−95.42** | **−8.05** |
    # ⇒ 闭合对 sj-006/008 是**必需**的（不闭合它们走不出轮廓），
    #   对 sj-003 有害（它闭合后形状不对，说明该件的开放端点**不是"半剖分界"**，
    #   而是别的原因 —— 嫌疑：某段线不在粗实线层）。
    #   **取舍**：保留闭合（2 件大幅改善 vs 1 件退化），sj-003 的退化如实记账。
    _CLOSE_OPEN = True
    if _CLOSE_OPEN:
        deg = {}
        for a, b in edges:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
        ends = [v for v, d in sorted(deg.items()) if d == 1]
        if len(ends) == 2:
            u, w = ends
            if u != w and (min(u, w), max(u, w)) not in set(edges):
                edges.append((min(u, w), max(u, w)))
                edges.sort()

    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    for v in adj:
        adj[v].sort(key=lambda n: math.atan2(verts[n][1] - verts[v][1],
                                             verts[n][0] - verts[v][0]))
    used = set()
    faces = []
    for a, b in edges:
        for u, w in ((a, b), (b, a)):
            if (u, w) in used:
                continue
            face = []
            cu, cw = u, w
            while (cu, cw) not in used:
                used.add((cu, cw))
                face.append(cu)
                lst = adj[cw]
                idx = lst.index(cu)
                cu, cw = cw, lst[(idx + 1) % len(lst)]       # 最左转
            if len(face) >= 3:
                s = 0.0
                for i in range(len(face)):
                    x1, y1 = verts[face[i]]
                    x2, y2 = verts[face[(i + 1) % len(face)]]
                    s += x1 * y2 - x2 * y1
                faces.append((face, s / 2.0))
    return faces, verts


def outer_loop(segs):
    """外轮廓 = **面积最大的那个面**（它包围一切；孔/凸台都是它内部的面）。"""
    faces, verts = faces_of(segs)
    if not faces:
        return None
    face, _s = max(faces, key=lambda t: abs(t[1]))
    if len(face) < 3:
        return None
    return [verts[i] for i in face]


def simplify(poly, tol):
    """共线点合并（剖面点是密集采样时非常必要）。"""
    out = []
    n = len(poly)
    for i in range(n):
        a, b, c = poly[i - 1], poly[i], poly[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > tol * max(1.0, math.hypot(c[0] - a[0], c[1] - a[1])):
            out.append(b)
    return out if len(out) >= 3 else poly


def convex_hull(pts):
    """点集 → **凸包**（Andrew 单调链）。点数不足 3 时原样返回。

    ## 用途：走环**退化时的显式降级**

    实测 sj-006 上层限位口的真外轮廓组（107×112pt、67 段）走环得到 **100 点但面积 0**
    —— 它有 **3 个度为 1 的端点**（`_CLOSE_OPEN` 只处理"恰好 2 个端点"的情形），
    走环在端点间来回折返、有向面积抵消。

    此时若降到"外接矩形"，截面会明显偏大（107×112 全填）。
    **凸包**贴合得多：对凸形零件（sj-006 的 Ø20 圆盘 + 凸缘）几乎就是真轮廓。

    凹形零件（如 sj-001 切槽螺栓有槽）凸包会填掉凹处 —— 所以这**只作降级**，
    正常走环成功时不用它，且调用方会拿到 `degraded='hull'` 标记。
    """
    uniq = sorted({(round(float(p[0]), 6), round(float(p[1]), 6)) for p in pts})
    if len(uniq) < 3:
        return uniq

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo = []
    for p in uniq:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    up = []
    for p in reversed(uniq):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


# ================================================================ 分层（厚度方向台阶）
def scanline_intervals(poly, t, axis="x"):
    """多边形与扫描线 `t` 的交点 → 配对成区间列表（标准扫描线法）。

    `axis="x"`：水平扫描线 y=t ⇒ 返回 **x 区间**；
    `axis="y"`：竖直扫描线 x=t ⇒ 返回 **y 区间**。

    `axis` 指的是"**长对正/高平齐**的共同方向"：
      · 共同方向是 x（长对正）⇒ 厚度方向是 y ⇒ 用水平扫描线；
      · 共同方向是 y（高平齐）⇒ 厚度方向是 x ⇒ 用竖直扫描线。
    """
    vals = []
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if axis == "x":
            a1, a2 = y1, y2
            v1, v2 = x1, x2
        else:
            a1, a2 = x1, x2
            v1, v2 = y1, y2
        if (a1 <= t < a2) or (a2 <= t < a1):
            k = (t - a1) / (a2 - a1)
            vals.append(v1 + k * (v2 - v1))
    vals.sort()
    return [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]


def has_step(thin_poly, tol=0.5, axis="x"):
    """薄视图轮廓里有没有**"中间高度的水平段"** —— 即**厚度方向的台阶**。

    ## 制图依据

    `section-analysis.md` §3.3：「看剖视图的**突变台阶**…台阶突变处 ⇒ **回到邻接视图
    上量出转折坐标**」。厚度方向的台阶在薄视图上表现为**平行于投影方向的直线段**
    （水平段），且它**不在轮廓的上下极值处**（那两条是零件的正反面）。

    实测：
      · sj-007 抗剪块的薄视图有 3 条中间水平段（y=368.9 与 363.6/379.6 都有距离）⇒ 有台阶；
      · sj-002 顶部垫片的薄视图是 4 点矩形（水平段只在 ymin/ymax）⇒ 无台阶。
    """
    # 台阶段 = **平行于共同方向**的线段（axis="x" ⇒ 水平段；axis="y" ⇒ 竖直段），
    # 且它**不在**该方向的极值处（极值处那两条是零件的正反面）。
    idx = 1 if axis == "x" else 0        # 厚度方向分量
    jdx = 0 if axis == "x" else 1        # 共同方向分量
    tv = [p[idx] for p in thin_poly]
    jv = [p[jdx] for p in thin_poly]
    vmin, vmax = min(tv), max(tv)
    span_j = max(jv) - min(jv)

    # ★ 判据必须同时满足三条（第三、四条是踩坑后补的）：
    #   ① 厚度方向变化 < tol（平行于共同方向）；
    #   ② 共同方向的跨度 ≥ 10% 视图（**真台阶线是长线**）——
    #      缺这条会把**圆角处的碎段**误当台阶：实测 sj-005 的圆角段
    #      `(430.8,529.8)-(431.2,531.3)` 厚度向只差 0.4pt（< tol），
    #      却让 has_step 判 True ⇒ 分出 13 个假层 ⇒ 体积从 +60% 崩到 −97%；
    #   ③④ 位置**不在厚度方向的极值处**（那里两条是零件的正反面）。
    n = len(thin_poly)
    for i in range(n):
        a, b = thin_poly[i], thin_poly[(i + 1) % n]
        dt = abs(a[idx] - b[idx])
        dj = abs(a[jdx] - b[jdx])
        if (dt < tol and span_j > 1e-9 and dj >= 0.10 * span_j
                and (a[idx] - vmin) > tol and (vmax - a[idx]) > tol):
            return True
    return False


def layers_of(thin_poly, sc, min_h=0.5, axis="x"):
    """薄视图轮廓 → `[(z0, z1, [区间...])]`（单位 mm，z 从 0 起）。

    每一层 = "厚度方向的一段" + "该段的**共同方向**范围"。多段即"多级台阶"。
    `axis` 语义同 `scanline_intervals`（"双向"：x ⇒ 水平扫描线且区间是 x；y ⇒ 反之）。
    """
    idx = 1 if axis == "x" else 0        # 厚度方向分量
    jdx = 0 if axis == "x" else 1        # 共同方向分量
    # ★ 共同方向 **不做平移**（o0 = 0）：三等关系里"长对正/高平齐"意味着
    #   主视图与俯视图**共享同一个图纸坐标轴**，两边的坐标必须落在同一系里才能求交。
    #   踩过的坑：这里原先减 `min(thin_poly[jdx])`，而调用方 `route_extrude` 对主视图轮廓
    #   减的是**主视图自己的 min** ⇒ 两者原点不同 ⇒ 分层条带与剖面完全错开 ⇒
    #   **交集恒为空** ⇒ 建出 volume=0 的空体（sj-008 底座因此一直落到 revolve 兜底）。
    #   厚度方向仍从 0 起（t0），因为那一维是本层自己的堆叠坐标。
    o0 = 0.0
    t0 = min(p[idx] for p in thin_poly)  # 厚度方向原点
    ts = sorted({round(p[idx], 3) for p in thin_poly})
    out = []
    for i in range(len(ts) - 1):
        a, b = ts[i], ts[i + 1]
        if b - a < min_h:
            continue
        ivs = scanline_intervals(thin_poly, (a + b) / 2.0, axis=axis)
        if not ivs:
            continue
        out.append(((a - t0) / sc, (b - t0) / sc,
                    [((u - o0) / sc, (v - o0) / sc) for u, v in ivs]))
    return out
