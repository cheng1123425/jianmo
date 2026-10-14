# -*- coding: utf-8 -*-
r"""s5_collect —— 从投影数据里提取几何特征（零件无关 · SHARED）

入参 refs: drawing_json
产出 data: 外接尺寸、圆特征、高度层、标注实测值

说明：本步**不依赖原图基准**，只把"当前三维投影长什么样"如实提炼出来；
      该不该、对不对，全部交给 s6_compare。

实现见 `lib/collect.py` —— **按视图存在性自适应**，所以三个零件（含 Right 视图）
与垫片（无 Right 视图）可以共用同一份实现，无需零件自带副本。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path           # noqa: E402
from lib.collect import collect                 # noqa: E402


def handler(in_msg):
    data = json.load(open(ref_path(in_msg, "drawing_json"), encoding="utf-8"))
    return [], collect(data)


if __name__ == "__main__":
    run_stage("s5_collect", handler)
