# -*- coding: utf-8 -*-
r"""假连线**出厂检查** ✓（几何 vs 连接表 ✓）—— 机器守 ✓，判据用渲染器那**唯一一份** ✓

用法（短命令 ✓）：
    py -3.13 check_fake_wires.py <sketch.fzz> [<sketch2.fzz> …]
    py -3.13 check_fake_wires.py pixel-schematic-v15.fzz        # 相对本目录 ✓
产出：每份文件的 (A)/(B) 计数 ✓ + 不合格时**逐条明细** ✓；**退出码 0 = 全过** ✓
      （1 = 有假连线 ✗ ／ 2 = 跑不起来 ✗ ⇒ **绝不静默放行** ✗）。

★ 为什么要有它 ✗（本仓记过一条硬事实 ✓）：
  **Fritzing 的连接只记在 `<connects>` 里** ⇒ `check_netlist.py`（只看连接表 ✗）
  **结构上永远看不见“图上的假象”** ✗✗ —— 于是要**拿几何去对表** ✓：
    (A) 表里声明接了某脚 ✗ 而线**根本没画到**那只脚上 ⇒ 图上看着**断开** ✗
        （`px = 1/90 in` 那个 bug 就是这种 ✓：当时连接表报“45/45 全配上”✓
         而用户截图里线悬在半空 ✗）；
    (B) 线**画在**某脚上（端点落在脚上 ✓ 或线身**正好穿过**脚 ✓）而表里**没那条** ✗
        ⇒ 读图的人以为接上了 ✓、电气上是**断的** ✗（最阴的一种 ✓）。

★ **不重复实现判据** ✓：几何判定与链语义都在 `render_sch.py` 里（唯一一份 ✓），
  本脚本只负责**跑它 + 取数 + 判合格线** ✓ —— 这里**不写**第二份几何代码 ✗。
★ **不静默退化** ✓：取不到 (A)/(B) 数字就报错退出 ✗（宁可吵，也不许“没解析到 = 通过” ✗）。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "render_sch.py")
WORK = os.path.join(HERE, "_work")

ARGV = sys.argv[1:]
if not ARGV:
    print(__doc__.strip().splitlines()[3].strip())
    print("\n请给至少一个 .fzz ✓（如：py -3.13 check_fake_wires.py pixel-schematic-v15.fzz）")
    raise SystemExit(2)

SEC_RE = re.compile(r"^\s*\(([ABC])\)[^\n]*?\*\*(\d+) (?:处|根)\*\*")
END_RE = re.compile(r"^\s*\([ABC]\)|^── |^   [^ ]")


def section(lines, letter):
    """取 (A)/(B)/(C) 那一段 ✓ —— 取不到返回 None ✗（= 渲染器版本不对 ✓，要报错 ✗）"""
    i = next((k for k, ln in enumerate(lines) if SEC_RE.match(ln) and
              SEC_RE.match(ln).group(1) == letter), None)
    if i is None:
        return None, None, []
    j = next((k for k in range(i + 1, len(lines)) if END_RE.match(lines[k])), len(lines))
    seg = lines[i:j]
    return i, int(SEC_RE.match(seg[0]).group(2)), [ln for ln in seg[1:] if ln.strip().startswith("✗")]


def run_one(path):
    """跑渲染器 ⇒ (A, B, A明细, B明细, 关键指标行) ✓"""
    png = os.path.join(WORK, "_check_fake_wires.png")
    os.makedirs(WORK, exist_ok=True)
    r = subprocess.run([sys.executable, "-X", "utf8", RENDER, path, png],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       cwd=HERE)
    if r.returncode:
        raise RuntimeError("渲染器失败 ✗（退出码 %d）\n%s" % (r.returncode, (r.stdout or "")[-1200:]))
    lines = ((r.stdout or "") + (r.stderr or "")).splitlines()
    _, na, da = section(lines, "A")
    _, nb, db = section(lines, "B")
    _, nc, dc = section(lines, "C")
    if na is None or nb is None:
        raise RuntimeError("报告里没有 (A)/(B) 段 ✗ ⇒ 渲染器版本不对 ✓（不要当通过 ✗）")
    key = [ln.strip() for ln in lines
           if any(z in ln for z in ("十字交叉", "穿过别的元件本体", "不相连的引脚",
                                    "悬空导线端", "总长", "画布"))]
    return na, nb, da, db, key, nc, dc


print("══ 假连线出厂检查 ✓（判据 = `render_sch.py` 唯一一份 ✓）")
bad = []
for t in ARGV:
    fzz = t if os.path.isabs(t) else os.path.join(HERE, t)
    name = os.path.basename(fzz)
    if not os.path.exists(fzz):
        print("\n── %s ✗ 文件不存在 ✗" % name)
        bad.append((name, 2, 0, ["文件不存在 ✗"]))
        continue
    try:
        na, nb, da, db, key, nc, dc = run_one(fzz)
    except RuntimeError as ex:
        print("\n── %s ✗ 跑不起来 ✗\n%s" % (name, ex))
        bad.append((name, 2, 0, [str(ex).splitlines()[0]]))
        continue
    ok = (na == 0 and nb == 0)
    print("\n── %s ： (A) **%d 处** %s ｜ (B) **%d 处** %s ｜ (C) 退化为点 **%d 根** %s  %s"
          % (name, na, "✓" if na == 0 else "✗✗", nb, "✓" if nb == 0 else "✗✗",
             nc if nc is not None else -1, "✓" if nc == 0 else "⚠ 请人看一眼",
             "✅ 合格 ✓" if ok else "❌ 不合格 ✗"))
    for ln in da + db:
        print("     " + ln.strip()[:130])
    for ln in key:
        print("     · " + ln[:120])
    if not ok:
        bad.append((name, na, nb, da + db))

print("\n══ 汇总 ✓（%d 份）" % len(ARGV))
for name, na, nb, det in bad:
    print("   ❌ %-32s (A)=%s ｜ (B)=%s" % (name, na, nb))
print("   %s" % ("★ 全部合格 ✓（(A)=0 且 (B)=0 ✓）" if not bad
                 else "★ 有假连线 ✗ ⇒ 见上面逐条明细 ✓（判定 = `render_sch.py` ✓）"))
raise SystemExit(1 if bad else 0)
