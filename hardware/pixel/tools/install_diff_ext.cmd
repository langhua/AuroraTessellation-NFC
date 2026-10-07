@echo off
rem ============================================================================
rem  install_diff_ext.cmd -- 把 hardware\pixel\vscode-diff 装成 VS Code 扩展
rem
rem  为什么这么做：不想让你去按 F5 开"扩展开发宿主"，也不想打包 .vsix
rem  （那还得先装 vsce）。VS Code 启动时会扫**用户扩展目录**
rem     %USERPROFILE%\.vscode\extensions\<publisher>.<name>-<version>\
rem  ⇒ 直接把文件夹拷进去、**重载窗口**就生效，跟从市场装的一样。
rem
rem  用法：
rem     tools\install_diff_ext.cmd            装 / 更新（覆盖）
rem     tools\install_diff_ext.cmd uninstall  卸载（删掉那个目录）
rem ============================================================================
setlocal
set "SRC=%~dp0..\vscode-diff"
set "DST=%USERPROFILE%\.vscode\extensions\langhua.pixel-diff-0.0.1"

if /i "%~1"=="uninstall" (
  if exist "%DST%" ( rmdir /s /q "%DST%" & echo [OK] 已卸载：%DST% )
  echo 记得重载窗口：Ctrl+Shift+P → Reload Window
  exit /b 0
)

if not exist "%SRC%\package.json" (
  echo [X] 找不到 %SRC%\package.json
  exit /b 2
)
if not exist "%USERPROFILE%\.vscode\extensions" mkdir "%USERPROFILE%\.vscode\extensions"

robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo [X] 拷贝失败 & exit /b 3 )

echo.
echo   [OK] 装好了
echo       源：%SRC%
echo       到：%DST%
echo.
echo   现在**重载窗口**：Ctrl+Shift+P -^> Reload Window
echo   然后命令面板搜 "比较两版"（或 "Pixel 差异"）。
echo.
echo   卸载：tools\install_diff_ext.cmd uninstall
exit /b 0
