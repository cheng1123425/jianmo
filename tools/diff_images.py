# -*- coding: utf-8 -*-
r"""diff_images.py —— 两张图做像素级对比（出图重构的视觉回归工具）

为什么需要它
------------
出图代码（s2_drawing / s3_render）重构后，闭环照样能 pass —— 因为它校验的是
「尺寸数值」，不是「版面」。标注挪位置、跑出图框这类问题只有看图才知道。
本工具把「逐张人眼审图」压成「看差异区域」，如果改的是行为保持的重构，应该输出 0 差异。

用法
----
    python tools/diff_images.py <基线图> <新图>
    python tools/diff_images.py docs/baseline/before-s3fix/bracket.png parts/bracket/drawing.png

退出码：0 = 完全一致｜1 = 有差异｜2 = 出错
"""
import sys


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(__doc__)
        return 2
    a_path, b_path = argv[0], argv[1]

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("需要 Pillow + numpy（本机 .venv 随 matplotlib 已安装）")
        return 2

    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    print("基线  %-12s %s" % (str(a.size), a_path))
    print("新图  %-12s %s" % (str(b.size), b_path))
    if a.size != b.size:
        print("!! 画布尺寸不同 —— 版面变了")

    w = min(a.size[0], b.size[0])
    h = min(a.size[1], b.size[1])
    A = np.asarray(a.crop((0, 0, w, h)), dtype=np.int16)
    B = np.asarray(b.crop((0, 0, w, h)), dtype=np.int16)
    d = np.abs(A - B).sum(axis=2)
    n = int((d > 0).sum())
    total = w * h
    print("差异像素  %d / %d（%.4f%%）　最大通道差 %d"
          % (n, total, n * 100.0 / total, int(d.max())))

    if n == 0 and a.size == b.size:
        print("=> 完全一致 ✅")
        return 0
    ys, xs = (d > 0).nonzero()
    if len(xs):
        print("=> 差异区域  x[%d, %d]  y[%d, %d]（人工只需看这一块）"
              % (xs.min(), xs.max(), ys.min(), ys.max()))
    return 1


if __name__ == "__main__":
    sys.exit(main())
