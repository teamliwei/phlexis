@echo off
setlocal enabledelayedexpansion
REM push_to_gh.bat - stage, commit, and push this project to GitHub.
REM Reads GITHUB_TOKEN from .env (never echoed, never stored in .git/config).
REM Usage: push_to_gh.bat ["optional commit message"]

cd /d "%~dp0"

REM --- repo bootstrap ---
if not exist .git git init -b main
git remote get-url origin >nul 2>&1
if errorlevel 1 git remote add origin https://github.com/teamliwei/phlexis.git

REM --- load token from .env (must never be committed) ---
if not exist .env (
  echo ERROR: .env not found next to this script.
  exit /b 1
)
set "TOKEN="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b "GITHUB_TOKEN=" .env`) do set "TOKEN=%%B"
if "!TOKEN!"=="" (
  echo ERROR: GITHUB_TOKEN is empty - set it in .env first.
  exit /b 1
)

REM --- current branch (default main) ---
set "BRANCH=main"
for /f %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"

REM --- stage everything not gitignored ---
git add -A

REM --- commit only if there is something staged ---
git diff --cached --quiet
if errorlevel 1 (
  set "MSG=%~1"
  if "!MSG!"=="" set "MSG=update %DATE% %TIME%"
  git commit -m "!MSG!"
  if errorlevel 1 exit /b 1
) else (
  echo Nothing to commit - working tree matches HEAD.
)

REM --- push using the token inline (origin URL stays clean) ---
git push https://x-access-token:!TOKEN!@github.com/teamliwei/phlexis.git !BRANCH!
if errorlevel 1 (
  echo PUSH FAILED - check the token scope [Contents read/write] and repo access.
  exit /b 1
)

echo Pushed branch !BRANCH! to github.com/teamliwei/phlexis.git
endlocal
