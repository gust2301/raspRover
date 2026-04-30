@echo off
REM ========================================================================
REM Configuration de l'environnement Python pour le RaspRover (Windows)
REM ========================================================================

cd /d "%~dp0"
set PYEXE=

REM --- 1) Essayer le lanceur py -3 (installe par python.org/winget) ------
py -3 --version >nul 2>&1
if not errorlevel 1 goto USE_PY

REM --- 2) Essayer python mais verifier que ce n'est pas le stub MS Store -
for /f "delims=" %%V in ('python --version 2^>^&1') do set "PYVER=%%V"
echo %PYVER% | findstr /i "Python 3" >nul 2>&1
if not errorlevel 1 goto USE_PYTHON

goto NO_PYTHON

:USE_PY
set "PYEXE=py -3"
goto HAVE_PYTHON

:USE_PYTHON
set "PYEXE=python"
goto HAVE_PYTHON

:NO_PYTHON
echo.
echo [ERREUR] Aucun Python utilisable n'a ete detecte.
echo.
echo Verifier dans l'ordre :
echo   1. Python installe ?  Sinon :  winget install Python.Python.3.12
echo   2. Alias Microsoft Store desactives ?
echo      Parametres ^> Applications ^> Parametres avances des applications
echo      ^> Alias d'execution d'application
echo      Decocher : python.exe  ET  python3.exe
echo      Garder actives : py.exe, pymanager.exe, pyw.exe, pywmanager.exe
echo   3. FERMER et rouvrir PowerShell apres install/modif (PATH en cache)
echo.
pause
exit /b 1

:HAVE_PYTHON
echo Python detecte : %PYEXE%
%PYEXE% --version
echo.

REM --- Creation du virtualenv --------------------------------------------
if not exist .venv (
    echo [1/3] Creation du virtualenv .venv ...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] echec creation du venv.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtualenv .venv deja present.
)

REM --- Mise a jour pip + installation des dependances --------------------
echo [2/3] Mise a jour de pip dans le venv ...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERREUR] echec pip upgrade.
    pause
    exit /b 1
)

echo [3/3] Installation des dependances runtime...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] echec pip install.
    pause
    exit /b 1
)

if exist requirements-dev.txt (
    echo [3bis] Installation des dependances de developpement...
    .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    if errorlevel 1 (
        echo [ERREUR] echec pip install dev.
        pause
        exit /b 1
    )
)

echo.
echo ========================================================================
echo   Installation reussie.
echo.
echo   Activer le venv dans une future session :
echo     PowerShell :  .\.venv\Scripts\Activate.ps1
echo     cmd.exe    :  .venv\Scripts\activate.bat
echo.
echo   Dans IntelliJ IDEA :
echo     File ^> Project Structure ^> Project ^> SDK ^> Add Python SDK ^>
echo     Virtualenv Environment ^> Existing environment ^>
echo     %cd%\.venv\Scripts\python.exe
echo ========================================================================
pause
