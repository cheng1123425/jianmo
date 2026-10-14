# -*- coding: utf-8 -*-
r"""facelevels —— 从 STEP 实体系统性抽取平面端面标高（供 geom 层校核用）

**为什么需要它**

s6_compare 的几何校验原来只测「圆 + 包围盒」，完全不测「面到面距离」。
于是只要某零件的区分性特征是平面端面间距（例如 ybracket 的底座高 / 沉孔深），
闭环就结构性失明——一个 58≠48 的建模错误会被 n_geom=0 放行。

本模块把「实体所有平面端面在 X/Y/Z 上的标高」如实抽出来，交给 s6_compare 按
ref_spec 声明的 FACE_LEVELS 逐轴核对（子集语义：声明里的每个标高都必须真实存在）。

**为什么从实体抽、而不是从三视图反推**

三视图里的水平线受遮挡/斜切影响并不干净（实测 ybracket 剖视只露出
[0,32,72,86,88,120]，与实体真实端面 [0,32,34,48,88,98,120] 对不上）。
从 STEP 实体直接读平面面，才是可靠、系统性的来源。这与 HANDOFF §4 的探针同法。

隔离：本模块被各零件的 s6_compare（runner=py，venv 内有 build123d）导入，
不触碰消息线，只在传入的 step_path 上做只读几何分析。
"""


def plane_levels(step_path, tol_normal=0.99):
    """返回 {'x':[...], 'y':[...], 'z':[...]}：各轴向上的平面端面标高（去重排序）。"""
    from build123d import import_step           # 延迟 import，避免无建模需求的场景硬依赖

    sh = import_step(step_path)
    out = {"x": set(), "y": set(), "z": set()}
    for f in sh.faces():
        try:
            if f.geom_type.name != "PLANE":
                continue
        except Exception:
            continue
        n = f.normal_at(f.center())
        c = f.center()
        if abs(n.X) > tol_normal:
            out["x"].add(round(c.X, 3))
        if abs(n.Y) > tol_normal:
            out["y"].add(round(c.Y, 3))
        if abs(n.Z) > tol_normal:
            out["z"].add(round(c.Z, 3))
    return {k: sorted(v) for k, v in out.items()}


def check_face_levels(ref, step_path, tol, add):
    """按 ref.FACE_LEVELS（子集语义）核对实体端面标高，缺失则 add 一条 geom。

    FACE_LEVELS 形如 {'z':[0,50,70,100]}；声明里的每个标高都必须在实体对应轴的
    平面端面里真实存在（容差 tol）。未声明 FACE_LEVELS 的零件自动跳过（零影响）。
    """
    want_axes = getattr(ref, "FACE_LEVELS", None)
    if not want_axes:
        return
    try:
        lv = plane_levels(step_path)
    except Exception as e:                       # 读不动 STEP 不能反过来误判模型
        add("geom", "端面标高读取失败", None, None, None,
            "无法从 STEP 抽取端面标高：%s" % e)
        return
    for ax, want in want_axes.items():
        got = lv.get(ax, [])
        for want_lv in want:
            if not any(abs(g - want_lv) <= tol for g in got):
                add("geom", "端面标高 %s=%.1f" % (ax.upper(), want_lv),
                    want_lv, None, None,
                    "模型缺少 %s=%.1f 的平面端面（该轴实测标高 %s）—— "
                    "面到面距离不符，属原 geom 层盲区" % (ax.upper(), want_lv, got))
