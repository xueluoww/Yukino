@echo off
rem ASCII only - see the note in the launcher .bat file.
chcp 65001 >nul
setlocal
title Stop Yukino 0.9
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
echo   stopping the Yukino 0.9 game service ...
echo.

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\bootstrap.ps1" -Stop -PackageRoot "%~dp0." %*
set "yukino_code=%errorlevel%"

echo.
if "%yukino_code%"=="0" (echo   done.) else (echo   Stop did not finish. See the message above; no process was force-killed.)
popd
endlocal & exit /b %yukino_code%
