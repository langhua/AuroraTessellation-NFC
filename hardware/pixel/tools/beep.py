# -*- coding: utf-8 -*-
r"""★ 长跑脚本「收工**响一声**」✓（2026-10-06 用户要的 ✓）

用户原话 ✓：「这种长时间跑的脚本，跑完了，发一声 beep 吧？提醒下我」✓

⇒ 用 **Windows 自带 `winsound`** ✓（✗ 不装第三方包 ✗）：
   · **成功** ✓ = 上行三声 ✓（`G5 → C6 → E6` ✓ —— 不用看屏幕就知道"好了" ✓）
   · **失败/崩了** ✗ = 下行两声 ✓（正在忙别的也听得出来要去看看 ✓）

★★ 只给**顶层长跑脚本**用 ✓（`place_drv.py` ✓ / `measure.py` ✓ / `place_greedy.py` ✓）；
   ✗✗ **绝不要**加进 `gen_routes.py` ✗ —— 它被搜索脚本**调用几百次** ✗
   ⇒ 会响几百声 ✗✗（这是"响一声提个醒"的**反面** ✗）。
"""
import sys

_OK = [(784, 110), (1047, 110), (1319, 260)]      # 上行三声 ✓
_BAD = [(660, 180), (494, 380)]                    # 下行两声 ✓


def done(ok=True):
    """收工提示音 ✓ —— ✗ 绝不抛异常 ✗（无声卡 / 非 Windows ⇒ 退回 BEL ✓）。"""
    try:
        import winsound
    except ImportError:
        sys.stdout.write("\a")
        sys.stdout.flush()
        return
    try:
        for freq, ms in (_OK if ok else _BAD):
            winsound.Beep(int(freq), int(ms))
    except Exception:                              # noqa: BLE001
        try:
            winsound.MessageBeep()
        except Exception:                          # noqa: BLE001
            sys.stdout.write("\a")
            sys.stdout.flush()


if __name__ == "__main__":
    # 自测 ✓：`py -3.13 tools\beep.py` ⇒ 上行三声 ✓；加 `bad` ⇒ 下行两声 ✓
    # ★ `--exit N` ✓（2026-10-07 补 ✓）：给 `run_detached.cmd` 用 ✓ ——
    #   把被跑脚本的**退出码**带进来 ✓ ⇒ **0 响上行 ✓、非 0 响下行 ✓**（不用看屏幕 ✓）。
    _a = sys.argv[1:]
    _rc = 0
    if "--exit" in _a:
        try:
            _rc = int(_a[_a.index("--exit") + 1])
        except (IndexError, ValueError):
            _rc = 1
    _ok = ("bad" not in _a) and _rc == 0
    done(ok=_ok)
    print("beep ✓" if _ok else "beep ✗")
