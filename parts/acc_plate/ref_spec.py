# -*- coding: utf-8 -*-
r"""acc_plate —— 闭环基准（几何期望 + 标注清单）

`s6_compare` 用它逐项核对模型；`s5b_dimchain` 用它校验尺寸链自洽。
数值应与 params.py / 图纸一致。
"""

CALIB_NOTE = "待填：从原图量得的 px/mm 标定说明"
TOL = 0.5                                        # 判定容差 (mm)

TOP = {
    "len_x": 60.0,                               # 俯视外接 X
    "len_y": 40.0,                               # 俯视外接 Y
}

FRONT = {
    "height": 10.0,                              # 主视总高
}

RIGHT = {}

#: 平面端面标高（子集语义：声明的每个标高必须真实存在）。键必须小写 x/y/z。
FACE_LEVELS = {
    "z": [0.0, 10.0],
}

#: 图上必须出现的标注（闭环核对其数值）
MARKS = {
    "L": 60.0,
    "W": 40.0,
    "H_total": 10.0,
    "D8": 8.0,
}
