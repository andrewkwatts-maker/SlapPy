@echo off
REM SetVersion.bat — bump the engine version across pyproject.toml, Cargo.toml,
REM and python\slappyengine\__init__.py in one call.
REM
REM Usage:
REM     SetVersion.bat 0.3.0
REM     SetVersion.bat 0.3.0a1
REM     SetVersion.bat 0.4.0-rc.1
REM
REM The PEP 440 (Python) and SemVer (Cargo) variants are derived automatically.

if "%~1"=="" (
    echo usage: SetVersion.bat ^<version^>
    echo   e.g.  SetVersion.bat 0.3.0
    echo         SetVersion.bat 0.3.0a1
    exit /b 2
)

python "%~dp0scripts\set_version.py" "%~1"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Running version-consistency tripwire...
set PYTHONPATH=%~dp0python
python -m pytest "%~dp0tests\test_version_consistency.py" -v --no-header
exit /b %errorlevel%
