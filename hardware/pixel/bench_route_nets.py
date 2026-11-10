# -*- coding: utf-8 -*-
"""**只给布线器用**的临时网表：把 `RC` 拆成上下两半 ✓（不是交付物 ✗）

为什么 ✗：布线器对 `RC` 这条"跨中缝"的网搜不到解 ✓（试过 `--near-hole` / `--straight` ✓ 都不行 ✓），
但**它自己布的 `COIL_A` 就跨过去了** ✓ ⇒ 只是这一处搜不到 ✓。
⇒ 先用这个文件让它把**其余全部布好并写盘** ✓，再由 `add_rc_cross.py` 手工补那两根线 ✓，
最后用**真网表** `pixel_bench_nets.py` 复核（`bb_probe` 必须判 `RC` 连通 ✓）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, r"f:\git\AuroraTessellation-NFC\hardware\pixel")

import pixel_bench_nets as B   # noqa: E402

NETS = {k: list(v) for k, v in B.NETS.items()}
NETS.pop("RC")
# RC 的两半：上（R1/C1/D4 阳极）／下（U1 的 PD5、PD6）
NETS["RC_U"] = [("R1", "#2"), ("C1", "#1"), ("D4", "anode")]
NETS["RC_L"] = [("U1", "PD6"), ("U1", "PD5")]

EXPECT = {k: set(v) for k, v in B.EXPECT.items()}
EXPECT.pop("RC")
EXPECT["RC_U"] = {"R1.connector1", "C1.connector0", "D4.connector1"}
EXPECT["RC_L"] = {"U1.connector19", "U1.connector18"}

COLOR = dict(B.COLOR)
COLOR.pop("RC", None)
COLOR["RC_U"] = "#ef6100"
COLOR["RC_L"] = "#ef6100"
POWER = B.POWER
POWER_SPEC = B.POWER_SPEC
