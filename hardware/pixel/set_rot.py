# -*- coding: utf-8 -*-
r"""给某个**元件**加旋转 ✓（2026-09-28 ✓）—— 按 **Fritzing 自己的格式**写 ✓，不自创 ✗

★★ 格式（2026-09-28 ✓ 从**用户转过的文件**里挖出来的 ✓，`_scratch/t43.py` ✓）：
    旋转是 `schematicView/geometry` 的**子元素** ✗ **不是属性** ✗：
        <schematicView layer="schematic">
            <geometry z="2.50001" x="-55.8423" y="-27.3187">
                <transform m11="-1" m12="0" m13="0"
                           m21="0" m22="-1" m23="0"
                           m31="19.8425" m32="36.4252" m33="1" />
            </geometry>
        …
    实测两例 ✓：J1 默认就是 **180° 翻转**（`m11=m22=-1` ✓）；用户按 Ctrl+R 转 45° 后
    变成 `m11=m22=-0.7071…`、`m12=-m21=-0.7071…` ✓。
    ★ 别按"属性名里找 rotate"去查 ✗ —— 那种写法**查不到**这个子元素 ✓（我为此白查两轮 ✗）。

★★ 我们的工具链**本来就认它** ✓：`part_box.tf_of()` 就是"读 `<transform m11…m32>` ✓，
   没有就当单位阵 ✓" ⇒ **渲染器 / 量测 / 布线器都会自动跟着转** ✓ ⇒ 只差"设置"这一步 ✓。

★★ 用法与**必踩的坑** ✓：
    1) `py -3.13 set_rot.py <in.fzz> <out.fzz> [J1=180 [C2=90 …]]`（不给角度 ⇒ 原样复制 ✓）
    2) ★ **旋转后脚位/本体框全变了** ✗ ⇒ **必须重新生成 pins 文件** ✓：
           render_sch.py <改过的.fzz> <out.png> --pins-out=<新pins.py>
       ★★ 那个选项**必须带等号** ✗ —— 写成 `--pins-out <file>` 会被当成第 3 个位置参数
          （`px宽`）而报 `ValueError` ✓（`_scratch/t44.py` 第一版就踩了这个 ✓）。
    3) 再 `gen_schematic_layout3.py <改过的.fzz> <layout.fzz> --pins=<新pins.py>` ✓ → 尺子 → 布线 ✓。
       实测：这样重生成的**基线档**与 v18 **逐项相同** ✓ ⇒ 这条路**等价、可用** ✓。

★ 已实测的结论 ✓（`_scratch/t44.py` ✓，3 档）：`J1=180` ⇒ 重叠 0 ｜ 贴脚 **26** ✗✗ ｜ 交叉 18 ✗ ｜
  穿体 **4** ✓ ｜ 总长 **1882** ✓✓ ｜ 画布 **80.5** ✓✓ ｜ **告警 1** ✗ ⇒ **按判据不采纳** ✗
  （根因：`gen_schematic_layout3.layout()` 里那几条对齐规则是按**旧朝向**手写的 ✗
    ⇒ 下一手应是**朝向感知的摆位规则** ✓，不是继续调布线器 ✗；详见 `README.md` 第十手 ✓）。
"""
import math
import os
import sys
import zipfile
import xml.etree.ElementTree as ET


def tag(e):
    return e.tag.split("}")[-1]


def fmt(v):
    s = "%.6f" % v
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def get_tf(geo):
    t = next((c for c in geo if tag(c) == "transform"), None)
    if t is None:                              # 没有就补一个单位阵 ✓（与 Fritzing 同形 ✓）
        t = ET.SubElement(geo, "transform")
        t.attrib.update({"m11": "1", "m12": "0", "m13": "0", "m21": "0", "m22": "1",
                         "m23": "0", "m31": "0", "m32": "0", "m33": "1"})
    return t


def rotate(t, deg):
    r"""`M' = R(deg)·M` ✓ —— **只动线性部分** ✓、**平移 (m31,m32) 不动** ✓
    ⇒ 语义 = “**绕这件自己的局部原点转**” ✓（转完落点会变 ✓，随后由摆位脚本按**新脚位**
      重新摆 ✓ —— 所以那一步不能省 ✓）。"""
    def g(k, d):
        try:
            return float(t.get(k))
        except (TypeError, ValueError):
            return d
    a, b = g("m11", 1.0), g("m12", 0.0)
    c, d = g("m21", 0.0), g("m22", 1.0)
    th = math.radians(deg)
    ca, sa = math.cos(th), math.sin(th)
    t.set("m11", fmt(ca * a - sa * b))
    t.set("m12", fmt(sa * a + ca * b))
    t.set("m21", fmt(ca * c - sa * d))
    t.set("m22", fmt(sa * c + ca * d))
    t.set("m13", t.get("m13") or "0")
    t.set("m23", t.get("m23") or "0")
    t.set("m33", t.get("m33") or "1")
    for k in ("m31", "m32"):
        if t.get(k) is None:
            t.set(k, "0")


def main(src, dst, spec):
    want = {}
    for s in spec:
        if "=" in s:
            k, v = s.split("=", 1)
            want[k.strip()] = float(v)
    z = zipfile.ZipFile(src)
    nm = [n for n in z.namelist() if n.endswith(".fz")][0]
    root = ET.fromstring(z.read(nm))
    done = []
    for el in root.iter("instance"):
        ttl = (el.findtext("title") or "").strip()
        if ttl not in want:
            continue
        for ch in el:
            if tag(ch) != "views":
                continue
            for sub in ch:
                if tag(sub) != "schematicView":
                    continue
                for geo in sub:
                    if tag(geo) == "geometry":
                        rotate(get_tf(geo), want[ttl])
                        done.append((ttl, want[ttl]))
    body = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as o:
        for n in z.namelist():
            o.writestr(n, body if n.endswith(".fz") else z.read(n))
    print("set_rot ✓：%s → %s ✓ 转了 %s ✓（没找到的：%s）"
          % (os.path.basename(src), os.path.basename(dst),
             ", ".join("%s=%g°" % d for d in done) or "(无 ✓)",
             ", ".join(k for k in want if k not in {d[0] for d in done}) or "无 ✓"))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
