@echo off
rem Builds ooz.dll (64-bit) with the Visual Studio C++ compiler. Any edition and version with the C++ tools works.
setlocal
set VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
if not exist "%VSWHERE%" (
  echo Visual Studio wasn't found. Install it with the "Desktop development with C++" workload.
  exit /b 1
)
set VS=
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VS=%%i
if not defined VS (
  echo No Visual Studio with the C++ tools was found.
  exit /b 1
)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
cd /d "%~dp0"
set SRC=%~dp0..\src
cl /nologo /O2 /EHsc /LD /wd4244 /wd4267 /wd4146 /wd4018 /FIsys/types.h /FIsys/stat.h /I"%SRC%" "%SRC%\kraken.cpp" "%SRC%\lzna.cpp" "%SRC%\bitknit.cpp" /Fe:ooz.dll /link /DEF:ooz.def
if errorlevel 1 (
  echo The build failed.
  exit /b 1
)
del /q *.obj ooz.exp ooz.lib 2>nul
echo Built ooz.dll
