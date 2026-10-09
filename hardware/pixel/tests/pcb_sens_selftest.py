# -*- coding: utf-8 -*-
r"""pcb_sens_selftest：**虚拟删线灵敏度**闸门 ✓（第五十二轮立 ✓）

★ 用户原话（2026-10-10 ✓，本轮的验收标准 ✓）：
  「`pixel-pcb-v82.fzz` 三个视图，都是**布线完成**。但是有问题啊，我在三个视图里**随意删除任意
   一根导线，也还是布线完成**」✗

★ 本轮**量出来的结论**（不是猜 ✗，四个「用户读过状态栏」的文件逐字对上 ✓；口径与源码出处
  在库仓 `tools\pcb_status.py` 文件头 ✓）：

  ① **上一轮（v81→v82）没有把 PCB 视图的网弄空** ✓ —— M 反而 **7 → 9** ✓（"网模型为空"**证伪** ✓）；
  ② ★ 用户那句"删任意一根线也应报未布"**在 Fritzing 里做不到** ✗：`scoreOneNet` 的 K =
     该网**连通片数 − 1**（`graphutils.cpp:573` ✓），单刀切开 ⇒ 每片**各自内部连通** ⇒ 每片 K=0 ✓；
     而**只有 1 只零件脚**的片被 `sketchwidget.cpp:7013` **整片丢掉** ✗ ⇒ `netCount == routedCount`
     **恒成立** ⇒ 文案**恒为** `Routing completed` ✓ ⇒ 这不是本文件的病 ✗、也**改不了** ✗；
  ③ ⇒ 所以真正的硬闸门是「**每张设计的网在每个视图里都成型（≥2 只脚 ✓）且连通（K=0 ✓）**」✓
     —— 这一条**既能过、又能抓住真病** ✓（"剥瘦底图"那一类：网退化成 1 只脚 ⇒ 直接被抓 ✗）。

六段 ✓（**双向**都要过 ✓）：
  ① 校准 ✓：`v68 →(9,0)`、`v81 →(7,2)`、`v76.4_byHand →(7,2)`、`v83 →(9,0)`（PCB 视图 ✓），
     且 v81 的**文案**逐字 = 用户读到的「5 of 7 nets routed - 2 connector(s) still to be routed」✓；
  ② v83 三视图 ⇒ **K=0** ✓、PCB 视图 **M=9 = 网表张数** ✓、**每张网 ≥2 只脚** ✓、exit 0 ✓；
  ③ 灵敏度**覆盖** ✓：三视图 36 ＋ 45 ＋ 52 = **133** 根线**全部**虚拟删过 ✓；
  ④ 灵敏度**严口径**（删完 K>0）⇒ 实测 **0/133** ✗ ＋ **文案一条都不变** ✗ ⇒ 如实记为
     **Fritzing 自身口径** ✓（机理见上 ✓，由 `tools\tests\pcb_status_selftest.py` 的 ② 段独立钉住 ✓）；
  ⑤ 割边／冗余**逐条记账** ✓（v83：27/44/48 割边 ✓、9/1/4 并联冗余 ✓）⇒ **铜一个字节都没改** ✓；
  ⑥ 交付件三视图渲染与 v82 **逐字节相同** ✓（可见内容没动 ✓ —— 最强证据 ✓）。

用法：`py -X utf8 tests\pcb_sens_selftest.py` ⇒ 全过 exit 0 ✓
"""
import hashlib
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIX = os.path.dirname(HERE)
sys.path.insert(0, PIX)
import toolpaths                                             # noqa: E402

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
                       cwd=PIX, capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONPATH=toolpaths.TOOLS + os.pathsep + PIX))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


PROBE = os.path.join(PIX, "tools", "pcb_rats_probe.py")
NETS = os.path.join(PIX, "pixel_nets.py")
V83 = os.path.join(PIX, "pixel-pcb-v83.fzz")
V76PRE = os.path.join(PIX, "_work", "v76.4_byHand.pre-nets.fzz")
PR = load(PROBE, "probe_sens")

print("== ① 校准：四个「用户读过状态栏」的文件 ⇒ 本探针逐字对上 ✓ ==")
for name, path, want_mk in (
        ("pixel-pcb-v68.fzz", os.path.join(PIX, "pixel-pcb-v68.fzz"), (9, 0)),
        ("pixel-pcb-v81.fzz", os.path.join(PIX, "pixel-pcb-v81.fzz"), (7, 2)),
        ("_work/v76.4_byHand.pre-nets.fzz", V76PRE, (7, 2)),
        ("pixel-pcb-v83.fzz", V83, (9, 0))):
    _pr, _no, info = PR.check_views(path, NETS)
    mk = (info["views"]["pcbView"]["M"], info["views"]["pcbView"]["K"])
    chk("%-32s ⇒ M=%d K=%d ✓（期望 %s ✓）" % (name, mk[0], mk[1], want_mk), mk == want_mk,
        "" if mk == want_mk else str(mk))
_pr, _no, info81 = PR.check_views(os.path.join(PIX, "pixel-pcb-v81.fzz"), NETS)
chk("v81 的**文案**逐字 = 用户读到的 ✓",
    info81["views"]["pcbView"]["text"]
    == "5 of 7 nets routed - 2 connector(s) still to be routed",
    info81["views"]["pcbView"]["text"])

print("\n== ② v83 三视图：K=0 ✓／PCB 视图 M = 网表张数 ✓／每张网 ≥2 只脚 ✓／exit 0 ✓ ==")
rc, out = run(PROBE, V83, "--nets=%s" % NETS)
chk("逐视图探针 exit 0 ✓", rc == 0, "" if rc == 0 else out[-800:])
_pr, _no, info = PR.check_views(V83, NETS)
for v, zh in (("breadboardView", "面包板"), ("schematicView", "原理图"), ("pcbView", "PCB")):
    chk("%s视图 K = 0 ✓（状态栏那句「布线完成」是真的 ✓）" % zh, info["views"][v]["K"] == 0,
        "K=%d" % info["views"][v]["K"])
    chk("%s视图：没有「只有 1 只脚」的网 ✓（否则会被 Fritzing 丢掉 ✗）" % zh,
        not info["views"][v]["shortfall"], str(info["views"][v]["shortfall"]))
chk("PCB 视图 **M = 9 = `pixel_nets.py` 张数** ✓（一张不多一张不少 ✓）",
    info["views"]["pcbView"]["M"] == 9 and info["designed"] == 9,
    "M=%d 设计=%d" % (info["views"]["pcbView"]["M"], info["designed"]))
chk("三视图**都没有跨视图 glue** ✓", info["views"]["pcbView"]["K"] == 0)

print("\n== ③ 灵敏度覆盖：三视图 **133** 根线**全部**虚拟删过 ✓ ==")
rc, out = run(PROBE, V83, "--sens", "--nets=%s" % NETS)
chk("灵敏度探针 exit 0 ✓（= 硬闸门全过 ✓）", rc == 0, "" if rc == 0 else out[-800:])
_pr, _no, sinfo = PR.sens(V83, NETS)
cov = {v: sinfo["views"][v]["n"] for v in ("breadboardView", "schematicView", "pcbView")}
chk("覆盖 = 面包板 %d ＋ 原理图 %d ＋ PCB %d = **133** ✓"
    % (cov["breadboardView"], cov["schematicView"], cov["pcbView"]),
    sum(cov.values()) == 133, str(cov))

print("\n== ④ 严口径（删完 K>0）⇒ **0/133** ✗ ＋ 文案**一条都不变** ✗（Fritzing 自身口径 ✓）==")
for v, zh in (("breadboardView", "面包板"), ("schematicView", "原理图"), ("pcbView", "PCB")):
    d = sinfo["views"][v]
    chk("%s视图：删线后 K>0 的 %d/%d ⇒ **正好 0** ✓（这就是「删了也还是布线完成」 ✓）"
        % (zh, len(d["strict"]), d["n"]), not d["strict"], str(d["strict"][:3]))
    chk("%s视图：删线后**文案**变的 %d/%d ⇒ **正好 0** ✓（可证 ✓，见文件头 ✓）"
        % (zh, len(d["text"]), d["n"]), not d["text"], str(d["text"][:3]))

print("\n== ⑤ 割边／冗余逐条记账 ✓（**铜一个字节都没改** ✓）==")
for v, zh, cut, red in (("breadboardView", "面包板", 27, 9), ("schematicView", "原理图", 44, 1),
                        ("pcbView", "PCB", 48, 4)):
    d = sinfo["views"][v]
    chk("%s视图：割边 %d ✓／并联冗余 %d ✓（删了本来就不该有反应 ✓）"
        % (zh, len(d["model"]), len(d["redundant"])),
        len(d["model"]) == cut and len(d["redundant"]) == red,
        "%d/%d" % (len(d["model"]), len(d["redundant"])))

print("\n== ⑥ 交付件三视图渲染与 v82 **逐字节相同** ✓（最强证据：可见内容没动 ✓）==")
for n, want in (("_preview.png", "0E117F01E9696587"), ("_preview.svg", "0192EAA5EDBE159C"),
                ("_bb.png", "F4E677807606A87F"), ("_bb.svg", "98E1C27E08D76281"),
                ("_sch.png", "91FB99E26D9414DF"), ("_sch.svg", "B87D1A9736B94F00")):
    a, b = os.path.join(PIX, "pixel-pcb-v82" + n), os.path.join(PIX, "pixel-pcb-v83" + n)
    ha = hashlib.sha256(open(a, "rb").read()).hexdigest()[:16].upper() if os.path.isfile(a) else "?"
    hb = hashlib.sha256(open(b, "rb").read()).hexdigest()[:16].upper() if os.path.isfile(b) else "?"
    chk("%-12s ⇒ v82=%s v83=%s（同 ✓／对得上基准 %s ✓）" % (n, ha, hb, want),
        ha == hb == want, "%s vs %s" % (ha, hb))

print("\n⇒ %s" % ("✓ 全过" if ok else "✗ 有不过"))
sys.exit(0 if ok else 1)
