# -*- coding: utf-8 -*-
r"""★「监工」✓：把长跑脚本的**输出写进日志** ✓、**跑完响一声** ✓（2026-10-07 用户要的 ✓）

用户原话 ✓：「要一个 run_detached.cmd」✓ —— 起因 ✓：VS Code 窗口 **OOM 崩了** ✗
⇒ 挂在它终端里的长跑脚本**跟着一起死** ✗（搜了两天的摆位搜索就这么没了 ✓）。

⇒ 本文件**不直接给用户用** ✓ —— 入口是 `tools\run_detached.cmd` ✓。
   `run_detached.cmd` 用 `start` 把**本文件**扔到**另一个控制台**里跑 ✓ ⇒
   ① 与 VS Code 的终端**没有任何父子关系** ✓ ⇒ **关掉 VS Code 也杀不掉它** ✓；
   ② 它的输出**不经过终端** ✓ ⇒ 进日志文件 ✓ ⇒ **不喂 VS Code 的内存** ✓（OOM 的两大成因都断了 ✓）。

★★ 日志**编码**（2026-10-07 实测踩到 ✗）：日志里全是 `✓`/`✗` ✓，而 PowerShell 5.1 的
   `Get-Content` **默认按 GBK 读** ✗ ⇒ 打开就是**乱码** ✗（实测 ✓）。修法两条 ✓：
   ① 日志写成 **UTF-8 带 BOM** ✓ ⇒ PowerShell **自己认出来** ✓（✗ 不用记着加 `-Encoding` ✗）；
   ② 给子进程 `PYTHONIOENCODING=utf-8` ✓ ⇒ 被跑的脚本**不管自己有没有 reconfigure** ✓
      写进来的都是 utf-8 ✓（否则它按本机 GBK 写 ⇒ 同一份日志混两种编码 ✗）。

它做三件事 ✓：
   ① `subprocess.call([python, "-u", 脚本, …])` ✓ ⇒ stdout **+ stderr** 一起进日志 ✓
      （★ 必须合并 ✗：VS Code 的任务终端**只回显 stdout** ✗ ⇒ Python traceback 会被吞掉 ✗ ——
       这是本仓踩过的坑 ✓，`_work/_run.py` 就是这么写的 ✓）；
   ② 往日志**末尾追加一行收工结算** ✓（`rc` ＋ **用时秒数** ✓）⇒ 看 tail 就知道成没成 ✓；
   ③ 响一声 ✓（`0` ⇒ 上行三声 ✓、非 0 ⇒ 下行两声 ✓）。

用法 ✓（给 `run_detached.cmd` 调）：
  py -3.13 tools\detached_run.py --log <日志路径> -- <脚本.py> [脚本参数…]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _split(argv):
    """`--log X -- 后面全是脚本的参数` ✓（✗ 不吞参数 ✗）。"""
    log, rest = None, None
    if "--log" in argv:
        i = argv.index("--log")
        log = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if "--" in argv:
        i = argv.index("--")
        rest = argv[i + 1:]
    if not rest:
        rest = argv
    return log, rest


def main(argv):
    log, rest = _split(list(argv))
    if not rest:
        sys.stderr.write(__doc__ or "")
        return 2
    script = rest[0]
    if log is None:
        log = os.path.join(os.path.dirname(os.path.abspath(script)),
                           os.path.basename(script) + ".log")
    d = os.path.dirname(os.path.abspath(log))
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError:
            pass

    t0 = time.time()
    rc = 1
    try:
        with open(log, "w", encoding="utf-8-sig", errors="replace") as fh:
            fh.write("===== 起 %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            fh.write("     %s %s\n\n" % (os.path.basename(sys.executable), " ".join(rest)))
            fh.flush()
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            rc = subprocess.call([sys.executable, "-u", script] + list(rest[1:]),
                                 stdout=fh, stderr=subprocess.STDOUT, cwd=os.getcwd(),
                                 env=env)
    except OSError as e:                     # 日志都写不进去 ✓（别静默 ✗）
        sys.stderr.write("写日志失败 %s：%s\n" % (log, e))
    sec = time.time() - t0

    # ★ 收工结算**追加**进日志 ✓ —— 一眼看得出成没成 / 跑了多久 ✓
    try:
        with open(log, "a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n===== 收工 rc=%d ✓ 用时 %.1f 秒 =====\n" % (rc, sec))
    except OSError:
        pass
    # ★ 另存一份 `.rc` ✓：`run_detached.cmd` 自己（或用户）不看日志也能查状态 ✓
    try:
        with open(log + ".rc", "w", encoding="utf-8") as fh:
            fh.write("rc=%d\nsec=%.1f\nscript=%s\n" % (rc, sec, script))
    except OSError:
        pass

    try:
        import beep
        beep.done(ok=(rc == 0))
    except Exception:                        # noqa: BLE001  ✗ 响铃失败绝不影响退出码 ✗
        pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
