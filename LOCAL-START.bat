@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Krexion - Local Deploy
color 0B

echo ============================================================
echo   Krexion - Local One-Click Deploy (Windows / No Docker)
echo ============================================================
echo   Script: %~f0
echo   Folder: %~dp0
echo ============================================================
echo.

:: Disable Microsoft Store python.exe stub for this session
set "PATH=%PATH:C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps=%"

:: ============ Detect first-time setup ============
if exist ".installed" (
    echo [INFO] Already installed. Services start kar raha hoon...
    goto :START_SERVICES
)

:: ============ FIRST-TIME SETUP ============
echo [SETUP] Pehli baar setup chal raha hai - approx 8-12 minute.
echo         (Python + Node + MongoDB + dependencies install hongi)
echo.

:: ---- Check winget ----
where winget >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] winget nahi mila.
    echo         Microsoft Store khol kar "App Installer" install karein.
    pause
    exit /b 1
)

:: ====================================================================
:: STEP 1: Install Python 3.11 (force install via winget, ignore stubs)
:: ====================================================================
echo.
echo [SETUP] [1/5] Python 3.11 install ho raha hai (skip agar exist)...
set "PY_EXE="
if exist "C:\Python311\python.exe" set "PY_EXE=C:\Python311\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
if exist "%ProgramFiles%\Python311\python.exe" set "PY_EXE=%ProgramFiles%\Python311\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
if exist "%ProgramFiles(x86)%\Python311\python.exe" set "PY_EXE=%ProgramFiles(x86)%\Python311\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
if exist "C:\Python312\python.exe" set "PY_EXE=C:\Python312\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
if exist "C:\Python313\python.exe" set "PY_EXE=C:\Python313\python.exe"
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    if "!PY_EXE!"=="" set "PY_EXE=%%P"
)
if not "!PY_EXE!"=="" goto :PYTHON_FOUND
for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%P | findstr /i /v "WindowsApps" >nul
    if not errorlevel 1 if "!PY_EXE!"=="" set "PY_EXE=%%P"
)
if not "!PY_EXE!"=="" goto :PYTHON_FOUND

echo         winget se Python 3.11 install ho raha hai...
winget install -e --id Python.Python.3.11 --silent --scope user --accept-package-agreements --accept-source-agreements
if exist "C:\Python311\python.exe" set "PY_EXE=C:\Python311\python.exe"
if "!PY_EXE!"=="" if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if "!PY_EXE!"=="" if exist "%ProgramFiles%\Python311\python.exe" set "PY_EXE=%ProgramFiles%\Python311\python.exe"
if "!PY_EXE!"=="" (
    for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if "!PY_EXE!"=="" set "PY_EXE=%%P"
)

if "!PY_EXE!"=="" (
    color 0C
    echo [ERROR] Python 3.11 install fail ho gaya.
    echo         Script path: %~f0
    echo         Sahi file:   %~dp0LOCAL-START.bat  (repo ROOT se chalao)
    echo         Python check: C:\Python311\python.exe
    if exist "C:\Python311\python.exe" (
        echo         [HINT] Python file EXISTS — purani LOCAL-START copy chal rahi hai.
        echo         frontend\public ya frontend\build wali file mat use karo.
    )
    echo         Manually install karein: https://www.python.org/downloads/
    pause
    exit /b 1
)

:PYTHON_FOUND
echo         [OK] Python at: !PY_EXE!

:: ====================================================================
:: STEP 2: Install Node.js 20 LTS
:: ====================================================================
echo.
echo [SETUP] [2/5] Node.js 20 LTS install ho raha hai...
set "NODE_EXE="
if exist "%ProgramFiles%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
if "!NODE_EXE!"=="" if exist "%ProgramFiles(x86)%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles(x86)%\nodejs\node.exe"

if "!NODE_EXE!"=="" (
    echo         winget se Node.js install ho raha hai...
    winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    if exist "%ProgramFiles%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
)

if "!NODE_EXE!"=="" (
    color 0C
    echo [ERROR] Node.js install fail.
    echo         Manually: https://nodejs.org/
    pause
    exit /b 1
)
set "NODE_DIR=%ProgramFiles%\nodejs"
echo         [OK] Node at: !NODE_EXE!

:: ====================================================================
:: STEP 3: Install MongoDB Community 7
:: ====================================================================
echo.
echo [SETUP] [3/5] MongoDB Community 7 install ho raha hai...
set "MONGO_OK="
sc query MongoDB >nul 2>&1
if not errorlevel 1 set "MONGO_OK=1"
if "!MONGO_OK!"=="" (
    netstat -an | findstr ":27017" | findstr "LISTENING" >nul
    if not errorlevel 1 set "MONGO_OK=1"
)
if "!MONGO_OK!"=="" (
    echo         winget se MongoDB install ho raha hai...
    winget install -e --id MongoDB.Server --silent --accept-package-agreements --accept-source-agreements
    timeout /t 5 /nobreak >nul
)
set "MONGO_OK="
sc query MongoDB >nul 2>&1
if not errorlevel 1 set "MONGO_OK=1"
if "!MONGO_OK!"=="" (
    netstat -an | findstr ":27017" | findstr "LISTENING" >nul
    if not errorlevel 1 set "MONGO_OK=1"
)
if "!MONGO_OK!"=="" (
    color 0C
    echo [ERROR] MongoDB service install fail.
    pause
    exit /b 1
)
echo         [OK] MongoDB OK

:: Refresh PATH
set "PATH=!NODE_DIR!;%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%ProgramFiles%\MongoDB\Server\7.0\bin;%ProgramFiles%\MongoDB\Server\6.0\bin;%PATH%"

:: ====================================================================
:: STEP 4: Install yarn + serve globally via npm
:: ====================================================================
echo.
echo [SETUP] [4/5] Yarn + serve install...
call "%NODE_DIR%\npm.cmd" install -g yarn serve --silent
if errorlevel 1 (
    color 0E
    echo [WARN] Yarn/serve install mein issue, retrying...
    call "%NODE_DIR%\npm.cmd" install -g yarn serve
)
set "YARN_CMD=%AppData%\npm\yarn.cmd"
set "SERVE_CMD=%AppData%\npm\serve.cmd"
if not exist "!YARN_CMD!" (
    color 0C
    echo [ERROR] Yarn install fail.
    pause
    exit /b 1
)
echo         [OK] Yarn at: !YARN_CMD!

:: ====================================================================
:: STEP 5: Generate .env files + admin password
:: ====================================================================
echo.
echo [SETUP] [5/5] .env files + admin password generate...

set "JWT_SECRET="
for /f "delims=" %%i in ('powershell -NoProfile -Command "-join ((48..57)+(65..90)+(97..122) ^| Get-Random -Count 48 ^| %% {[char]$_})"') do set "JWT_SECRET=%%i"
if "!JWT_SECRET!"=="" set "JWT_SECRET=krexion-%random%%random%%random%-jwt"

set "ADMIN_PASS="
for /f "delims=" %%i in ('powershell -NoProfile -Command "$c='abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'; -join (1..16 ^| %% { $c[(Get-Random -Maximum $c.Length)] })"') do set "ADMIN_PASS=%%i"
if "!ADMIN_PASS!"=="" set "ADMIN_PASS=Admin@%random%%random%"

set "POSTBACK_TOK="
for /f "delims=" %%i in ('powershell -NoProfile -Command "-join ((48..57)+(65..90)+(97..122) ^| Get-Random -Count 24 ^| %% {[char]$_})"') do set "POSTBACK_TOK=%%i"
if "!POSTBACK_TOK!"=="" set "POSTBACK_TOK=pb-%random%%random%"

> backend\.env (
    echo MONGO_URL=mongodb://localhost:27017
    echo DB_NAME=krexion
    echo JWT_SECRET_KEY=!JWT_SECRET!
    echo ADMIN_EMAIL=admin@krexion.local
    echo ADMIN_PASSWORD=!ADMIN_PASS!
    echo POSTBACK_TOKEN=!POSTBACK_TOK!
    echo APP_URL=http://localhost:3000
    echo PUBLIC_BASE_URL=http://localhost:8001
    echo CORS_ORIGINS=*
    echo RESEND_API_KEY=
    echo RESEND_FROM=no-reply@krexion.local
    echo SENDER_EMAIL=onboarding@resend.dev
    echo GOOGLE_CLIENT_ID=
    echo GOOGLE_CLIENT_SECRET=
    echo GOOGLE_REDIRECT_URI=
)

> frontend\.env (
    echo REACT_APP_BACKEND_URL=http://localhost:8001
    echo WDS_SOCKET_PORT=0
    echo ENABLE_HEALTH_CHECK=false
)

> CREDENTIALS.txt (
    echo ============================================================
    echo  Krexion Admin Credentials - SAFE RAKHEIN
    echo ============================================================
    echo  Frontend:    http://localhost:3000
    echo  Backend:     http://localhost:8001
    echo  Admin URL:   http://localhost:3000/admin
    echo.
    echo  Admin Email:    admin@krexion.local
    echo  Admin Password: !ADMIN_PASS!
    echo ============================================================
)

echo.
echo [SETUP] Admin Password: !ADMIN_PASS!
echo         Saved in CREDENTIALS.txt

:: ====================================================================
:: Python venv + backend deps
:: LOCAL DEV ONLY — CI/deploy use backend/requirements.txt + Dockerfile
:: or build/build-backend.py (same EXCLUDE list via filter-requirements-local.py).
:: ====================================================================
echo.
echo [SETUP] Python venv + backend dependencies (5-7 min)...
if not exist ".venv\Scripts\python.exe" (
    "!PY_EXE!" -m venv .venv
    if errorlevel 1 (
        color 0C
        echo [ERROR] venv banane mein masla.
        pause
        exit /b 1
    )
) else (
    echo         [OK] Existing .venv reuse ho raha hai
)

call .venv\Scripts\activate.bat
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"!PY_EXE!" scripts\filter-requirements-local.py
if errorlevel 1 (
    color 0C
    echo [ERROR] requirements filter fail.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --prefer-binary -r backend\requirements-local.txt
if errorlevel 1 (
    del backend\requirements-local.txt >nul 2>&1
    color 0C
    echo [ERROR] Python deps install fail.
    pause
    exit /b 1
)
del backend\requirements-local.txt >nul 2>&1
echo         [SETUP] Optional AI package (fail ho to bhi OK)...
".venv\Scripts\python.exe" -m pip install emergentintegrations==0.1.0 --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ >nul 2>&1
if errorlevel 1 (
    color 0E
    echo [WARN] emergentintegrations skip — browser profile / referrer test ke liye zaroori nahi.
)

:: ====================================================================
:: Frontend deps + build
:: LOCAL DEV ONLY — GitHub Actions use Node 20 + yarn --frozen-lockfile (no --ignore-engines).
:: ====================================================================
echo.
echo [SETUP] Frontend yarn install + production build (3-5 min)...
cd frontend
set "YARN_IGNORE_ENGINES=true"
call "!YARN_CMD!" install --ignore-engines
if errorlevel 1 (
    color 0E
    echo [WARN] yarn install issue, retrying with --force...
    call "!YARN_CMD!" install --force --ignore-engines
)
set "NODE_OPTIONS=--max-old-space-size=4096"
set "CI=false"
set "GENERATE_SOURCEMAP=false"
if exist "node_modules\.bin\craco.cmd" (
    call "node_modules\.bin\craco.cmd" build
) else (
    call "node_modules\.bin\craco" build
)
if errorlevel 1 (
    color 0C
    echo [ERROR] Frontend build fail.
    cd ..
    pause
    exit /b 1
)
cd ..

:: Mark installed
> .installed echo done
echo.
color 0A
echo ============================================================
echo   SETUP COMPLETE! Services start ho rahi hain...
echo ============================================================
echo.

:: ============================================================
:: START SERVICES
:: ============================================================
:START_SERVICES
color 0B

:: Refresh PATH + paths
set "PY_EXE=%~dp0.venv\Scripts\python.exe"
set "YARN_CMD=%AppData%\npm\yarn.cmd"
set "SERVE_CMD=%AppData%\npm\serve.cmd"
set "PATH=%ProgramFiles%\nodejs;%AppData%\npm;%ProgramFiles%\MongoDB\Server\7.0\bin;%ProgramFiles%\MongoDB\Server\6.0\bin;%PATH%"

echo [START] MongoDB service check...
net start MongoDB >nul 2>&1
set "MONGO_OK="
sc query MongoDB | findstr /I "RUNNING" >nul
if not errorlevel 1 set "MONGO_OK=1"
if "!MONGO_OK!"=="" (
    netstat -an | findstr ":27017" | findstr "LISTENING" >nul
    if not errorlevel 1 set "MONGO_OK=1"
)
if "!MONGO_OK!"=="" (
    color 0C
    echo [ERROR] MongoDB service nahi chal rahi.
    echo         services.msc -^> MongoDB -^> Start
    pause
    exit /b 1
)
echo         [OK] MongoDB OK

:: Start backend
echo [START] Backend (FastAPI) launching on http://localhost:8001
start "Krexion Backend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --workers 1"

timeout /t 5 /nobreak >nul

:: Start frontend
echo [START] Frontend launching on http://localhost:3000
start "Krexion Frontend" cmd /k "cd /d %~dp0\frontend && %AppData%\npm\serve.cmd -s build -l 3000"

timeout /t 3 /nobreak >nul

:: Open browser
start "" http://localhost:3000

color 0A
echo.
echo ============================================================
echo   KREXION IS RUNNING
echo ============================================================
echo   Frontend:    http://localhost:3000
echo   Backend API: http://localhost:8001
echo   Admin Panel: http://localhost:3000/admin
echo.
echo   Credentials: CREDENTIALS.txt
echo   Stop:        LOCAL-STOP.bat
echo ============================================================
echo.
echo   Backend + Frontend windows alag se khulay hain.
echo   Yeh window band kar sakte ho.
echo.
pause
exit /b 0
