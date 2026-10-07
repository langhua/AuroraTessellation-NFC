@echo off
rem ============================================================================
rem  run_detached.cmd -- 把「长跑脚本」扔到 VS Code 的**外面**去跑 (2026-10-07)
rem
rem  为什么要有它:
rem     VS Code 窗口 OOM 崩掉时, 挂在它终端里的长跑脚本**跟着一起死**
rem     (搜了两天的摆位搜索就是这么没的)。
rem
rem  它怎么做到:
rem     1. 用 start 另开一个**独立控制台**(/min 收起) 跑 tools\detached_run.py;
rem        => 与 VS Code 的终端没有父子关系, 关掉 VS Code 杀不到它;
rem     2. 脚本的 stdout **+ stderr** 全部写进**日志文件** (不经过终端)
rem        => 不喂 VS Code 的内存, 也不怕终端只回显 stdout 把 traceback 吞掉;
rem     3. 跑完**响一声**: rc=0 上行三声 / 非 0 下行两声, 并写一份 .rc 状态文件。
rem
rem  用法:
rem     run_detached.cmd <脚本.py> [参数...]
rem  例:
rem     run_detached.cmd tools\place_drv.py --rot --rot-parts=U1
rem     run_detached.cmd tools\measure.py pixel-pcb-v76.fzz
rem
rem  想换解释器: 先 set LH_PY=py, 再跑 (默认 python)。
rem ============================================================================
setlocal
rem ★ 路径**规范化** ✓（`for %%~fI` 会把 `tools\..\_work` 收成真路径 ✓）——
rem   ✗ 不规范化的话打印出来是 `…\tools\..\_work\logs\…` ✓ 能用但难看 ✗（2026-10-07 实测 ✓）
for %%I in ("%~dp0..") do set "PIX=%%~fI"
set "HERE=%~dp0"
set "PYEXE=python"
if defined LH_PY set "PYEXE=%LH_PY%"

if "%~1"=="" goto usage
set "SCRIPT=%~f1"
shift

set "ARGS="
:args
if "%~1"=="" goto argsdone
set ARGS=%ARGS% "%~1"
shift
goto args
:argsdone

for %%I in ("%SCRIPT%") do set "SNAME=%%~nI"
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "TS=%%T"
set "LOGD=%PIX%\_work\logs"
if not exist "%LOGD%" md "%LOGD%" >nul 2>&1
set "LOG=%LOGD%\%SNAME%-%TS%.log"

echo.
echo   python : %PYEXE%
echo   script : %SCRIPT%
if not "%ARGS%"=="" echo   args   : %ARGS%
echo   log    : %LOG%
echo.

start "langhua:%SNAME%" /min %PYEXE% "%HERE%detached_run.py" --log "%LOG%" -- "%SCRIPT%" %ARGS%

echo   [OK] 已扔到 VS Code 之外 (独立控制台, 收起) => 关掉 VS Code 也杀不掉它
echo   看进度 : Get-Content -Wait "%LOG%"
echo   看结尾 : Get-Content -Tail 30 "%LOG%"
echo   看状态 : Get-Content "%LOG%.rc"
echo.
exit /b 0

:usage
echo 用法: run_detached.cmd ^<脚本.py^> [参数...]
echo   例: run_detached.cmd "%PIX%\tools\place_drv.py" --rot --rot-parts=U1
exit /b 2
