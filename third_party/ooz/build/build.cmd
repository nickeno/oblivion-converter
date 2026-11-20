@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
set SRC=%~dp0..\src
cl /nologo /O2 /EHsc /LD /FIsys/types.h /FIsys/stat.h /I"%SRC%" "%SRC%\kraken.cpp" "%SRC%\lzna.cpp" "%SRC%\bitknit.cpp" /Fe:ooz.dll /link /DEF:ooz.def 2>&1 | findstr /v /c:"warning C4"
