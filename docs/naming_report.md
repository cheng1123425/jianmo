
params.py
    ! [W3] R_OUT_CEN      量型「R」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 R_XXX → XXX_R）
    ! [W3] R_SIDE         量型「R」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 R_XXX → XXX_R）
    ✗ [E3] D_SIDE         D 只表示直径；注释是「侧凸台中心到零件中心的距离 (孔心距)」——中心距请改用 P
    ! [W3] D_SIDE         量型「D」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 D_XXX → XXX_D）
    ! [W3] R_NECK         量型「R」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 R_XXX → XXX_R）
    ! [W2] BASE_T         量型 T 必然沿某轴量，但没写 X/Y/Z —— 加上轴向可防轴混淆 bug
    ! [W2] H_WING         量型 H 必然沿某轴量，但没写 X/Y/Z —— 加上轴向可防轴混淆 bug
    ! [W3] H_WING         量型「H」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 H_XXX → XXX_H）
    ! [W2] H_CEN          量型 H 必然沿某轴量，但没写 X/Y/Z —— 加上轴向可防轴混淆 bug
    ! [W3] H_CEN          量型「H」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 H_XXX → XXX_H）
    ! [W3] R_BOSS         量型「R」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 R_XXX → XXX_R）
    ! [W3] D_HOLE_CEN     量型「D」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 D_XXX → XXX_D）
    ! [W3] D_HOLE_SIDE    量型「D」在首位 —— 规范是 部位_[修饰_]量型[_方向]（如 D_XXX → XXX_D）

parts/bracket/params.py
    ✓ 全部符合规范

parts/lbracket/params.py
    ✓ 全部符合规范

parts/ybracket/params.py
    ✓ 全部符合规范

================================================================
扫描 4 个 params.py、71 个参数：1 个 error、12 个 warning
命名检查未通过（改法见 docs/v3-命名规范与逻辑分层.md §2.6 对照表）。
