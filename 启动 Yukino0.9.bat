@echo off
rem ---------------------------------------------------------------
rem  Yukino 0.9 launcher (ASCII only on purpose: cmd.exe reads .bat
rem  files byte by byte with the console code page, so putting
rem  non-ASCII text here corrupts line offsets and breaks parsing.
rem  All Chinese messages live in launcher\bootstrap.ps1 instead.)
rem ---------------------------------------------------------------
chcp 65001 >nul
setlocal
title Yukino 0.9
pushd "%~dp0"

if not exist "%~dp0launcher\bootstrap.ps1" (
  echo.
  echo   launcher\bootstrap.ps1 not found. Please extract the whole archive again.
  echo.
  pause
  popd
  endlocal
  exit /b 1
)

set "PS=powershell.exe"
where pwsh.exe >nul 2>&1
if not errorlevel 1 set "PS=pwsh.exe"

echo.
echo   Yukino 0.9 test build
echo   checking runtime environment ...
echo.

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\bootstrap.ps1" -PackageRoot "%~dp0." %*
set "yukino_code=%errorlevel%"

if not "%yukino_code%"=="0" (
  echo.
  echo   Startup did not finish. Exit code %yukino_code%.
  echo.
  pause
)
popd
endlocal & exit /b %yukino_code%
