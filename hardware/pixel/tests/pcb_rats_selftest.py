# -*- coding: utf-8 -*-
r"""pcb_rats_selftest：**Fritzing 状态栏那把尺子**（`tools\pcb_rats_probe.py` ✓）的单元自测 ✓

★ 为什么要有它 ✗（2026-10-10 用户报的件 ✓）：本项目原来三套闸门**全过** ✓，可 Fritzing 仍报
  「**2 个连接仍然需要布线**」✗ ⇒ 说明**少了这一把尺子** ✓ ⇒ 现在就钉住它 ✓。

四段 ✓（**双向**都要过 ✓ —— 只会"放行"的尺子等于没尺子 ✗）：
  ① **有病要报** ✓：`pixel-pcb-v81.fzz` ⇒ **M=7 / K=2** ✓（＝用户读到的状态栏 ✓）
     且能指出**根因证据**（面包板孔/bus 把网并起来 ✓）；
  ② **治好要过** ✓：`pixel-pcb-v82.fzz` ⇒ **M=9 / K=0** ✓、exit 0 ✓、**没有 glue 证据** ✓；
  ③ **网表闸门同步** ✓：`tools\net_group_check.py` 在 v81 = exit 1 ✗、在 v82 = exit 0 ✓
     （用**同一个** `check()` ✓，不许两份实现 ✗）；
  ④ **修法器可复现** ✓：`tools\fz_deglue_records.py v81 → 临时件` ⇒ 与 `pixel-pcb-v82.fzz` **逐字节相同** ✓
     ＋ `--check` 在 v82 = exit 0 ✓、在 v81 = exit 1 ✓。

用法：py -X utf8 tests\pcb_rats_selftest.py
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                            # noqa: E402

ok = True


def chk(name, cond, extra=""):
    global ok
    print("  %s %s %s" % ("✓" if cond else "✗", name, extra))
    if not cond:
        ok = False


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(script, *args):
    r = subprocess.run([sys.executable, "-X", "utf8", script] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONPATH=toolpaths.TOOLS))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


NETS = os.path.join(PIX, "pixel_nets.py")
V81 = os.path.join(PIX, "pixel-pcb-v81.fzz")
V82 = os.path.join(PIX, "pixel-pcb-v82.fzz")
PROBE = os.path.join(PIX, "tools", "pcb_rats_probe.py")
GATE = os.path.join(PIX, "tools", "net_group_check.py")
FIX = os.path.join(PIX, "tools", "fz_deglue_records.py")

PR = load(PROBE, "pcb_rats_probe_t")
print("== ① 有病要报：`pixel-pcb-v81.fzz` ⇒ M=7 / K=2 ✓（＝用户读到的状态栏 ✓）==")
probs, _notes, info = PR.check(V81, NETS)
chk("M = 7 ✓（『7 中的 5 网络布线完成』✓）", info["M"] == 7, "M=%d" % info["M"])
chk("K = 2 ✓（『2 个连接仍然需要布线』✓）", info["K"] == 2, "K=%d" % info["K"])
chk("指出根因证据（面包板孔/bus 把网并起来 ✓）", len(info["glue"]) > 0,
    "证据 %d 条" % len(info["glue"]))
chk("点出被并的两对网（`BR+`、`GND` ✓ ＋ `COIL_A`、`RC` ✓）",
    {frozenset(r["names"]) for r in info["nets"] if len(r["names"]) > 1}
    == {frozenset(("BR+", "GND")), frozenset(("COIL_A", "RC"))},
    str([r["names"] for r in info["nets"] if len(r["names"]) > 1]))

print("\n== ② 治好要过：`pixel-pcb-v82.fzz` ⇒ M=9 / K=0 ✓、exit 0 ✓ ==")
#   ★ 第五十二轮 ✓：探针默认改成**逐视图版** ✓（三视图一起报 ✓）⇒ 这一段要那套"PCB 单视图"的
#     老文案 ⇒ 显式 `--pcb-only` ✓（口径是同一份 `check()` ✓，没换尺子 ✗）。
rc, out = run(PROBE, V82, "--nets=%s" % NETS, "--pcb-only")
chk("探针 exit 0 ✓", rc == 0, "" if rc == 0 else out[-800:])
chk("M = 9 ✓（『9 中的 9 网络布线完成』✓）", "M（Fritzing 会算成几张网）= 9" in out)
chk("K = 0 ✓（没有鼠线 ✓）", "K（还剩几条没布）= 0" in out)
chk("**跨视图 glue 证据 0 条** ✓", "跨视图 glue 证据 0 条" in out)
rc, out = run(PROBE, V82, "--nets=%s" % NETS)
chk("**逐视图版** exit 0 ✓（三视图都 K=0 ✓）", rc == 0,
    "" if rc == 0 else out[-800:])
chk("逐视图版报了三视图 ✓", all(("── %s ──" % zh) in out for zh in ("面包板", "原理图", "PCB")))

print("\n== ③ 网表闸门同步：`tools\\net_group_check.py`（用**同一份** `check()` ✓）==")
rc1, o1 = run(GATE, V81)
rc2, o2 = run(GATE, V82)
chk("在 v81 ⇒ exit 1 ✗（并网被抓住 ✓）", rc1 == 1, "exit=%d" % rc1)
chk("在 v82 ⇒ exit 0 ✓", rc2 == 0, "" if rc2 == 0 else o2[-800:])
chk("报的是 A/B（并网 ✗＋碎成 2 块 ✗）", "B 网" in o1 and "碎成" in o1)
chk("两份实现只有一份（入口 import 探针 ✓）",
    "import pcb_rats_probe" in open(GATE, encoding="utf-8").read())

print("\n== ④ 修法器可复现：`fz_deglue_records.py` v81 ⇒ 应＝`pixel-pcb-v82.fzz` 逐字节 ✓ ==")
tmp = os.path.join(PIX, "_work", "_selftest_v82.fzz")
os.makedirs(os.path.dirname(tmp), exist_ok=True)
rcf, outf = run(FIX, V81, tmp)
chk("修法器 exit 0 ✓", rcf == 0, "" if rcf == 0 else outf[-600:])
same = (os.path.isfile(tmp)
        and open(tmp, "rb").read() == open(V82, "rb").read())
chk("产出与交付件**逐字节相同** ✓（可复现 ✓）", same)
rcv2, _ = run(FIX, V82, "--check")
chk("`--check` 在 v82 = exit 0 ✓", rcv2 == 0, "exit=%d" % rcv2)
rcv1, _ = run(FIX, V81, "--check")
chk("`--check` 在 v81 = exit 1 ✗（查得出病 ✓）", rcv1 == 1, "exit=%d" % rcv1)
if os.path.isfile(tmp):
    os.remove(tmp)

print("\n⇒ %s" % ("✓ 全过" if ok else "✗ 有不过"))
sys.exit(0 if ok else 1)
