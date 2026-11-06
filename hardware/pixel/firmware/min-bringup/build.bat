@echo off
rem build.bat -- 找 MounRiver Studio 2 自带的 RISC-V gcc，然后 make
rem 产物: build\min-bringup.hex  (WCH-LinkUtility 直接烧这个)
setlocal

set "TC=F:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC12\bin"
set "PFX=riscv-wch-elf-"
if exist "%TC%\%PFX%gcc.exe" goto found

set "TC=F:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC15\bin"
set "PFX=riscv32-wch-elf-"
if exist "%TC%\%PFX%gcc.exe" goto found

echo [ERR] 找不到 MounRiver 的 RISC-V gcc。
echo       请手动指定: make TC_DIR="D:/xx/bin" PREFIX=riscv-wch-elf-
exit /b 1

:found
echo [OK] toolchain = "%TC%"  prefix = %PFX%
where make >nul 2>nul
if errorlevel 1 (
  echo [ERR] 找不到 make（GNU make）。装一个，或直接在 MounRiver Studio 里建工程编译。
  exit /b 1
)
make TC_DIR="%TC%" PREFIX=%PFX%
