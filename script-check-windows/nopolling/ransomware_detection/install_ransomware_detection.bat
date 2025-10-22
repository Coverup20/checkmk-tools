@echo off
REM ============================================================================
REM Script di Installazione Ransomware Detection per CheckMK Agent Windows
REM ============================================================================
REM
REM Descrizione:
REM   Installa e configura il sistema di rilevamento ransomware per CheckMK
REM
REM Requisiti:
REM   - CheckMK Agent installato
REM   - Eseguire come Amministratore
REM
REM Autore: Marzio
REM Data: 2025-10-22
REM ============================================================================

setlocal enabledelayedexpansion

echo.
echo ========================================================================
echo   Installazione Ransomware Detection per CheckMK
echo ========================================================================
echo.

REM Verifica privilegi amministratore
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERRORE] Questo script richiede privilegi di amministratore!
    echo.
    echo Esegui nuovamente come amministratore:
    echo   1. Click destro su questo file
    echo   2. Seleziona "Esegui come amministratore"
    echo.
    pause
    exit /b 1
)

echo [OK] Privilegi amministratore verificati
echo.

REM Trova directory CheckMK Agent
set "AGENT_DIR="
set "LOCAL_DIR="

REM Cerca in diverse posizioni comuni
if exist "C:\Program Files (x86)\checkmk\service\" (
    set "AGENT_DIR=C:\Program Files (x86)\checkmk\service"
)
if exist "C:\Program Files\checkmk\service\" (
    set "AGENT_DIR=C:\Program Files\checkmk\service"
)
if exist "C:\ProgramData\checkmk\agent\" (
    set "AGENT_DIR=C:\ProgramData\checkmk\agent"
)

if not defined AGENT_DIR (
    echo [ERRORE] Directory CheckMK Agent non trovata!
    echo.
    echo Installare CheckMK Agent prima di continuare.
    echo Download: https://checkmk.com/download
    echo.
    pause
    exit /b 1
)

echo [OK] CheckMK Agent trovato: %AGENT_DIR%

REM Crea directory local se non esiste
set "LOCAL_DIR=%AGENT_DIR%\local"
if not exist "%LOCAL_DIR%" (
    echo [INFO] Creazione directory local...
    mkdir "%LOCAL_DIR%"
)

echo [OK] Directory local: %LOCAL_DIR%
echo.

REM Directory corrente (dove si trova questo batch)
set "SCRIPT_DIR=%~dp0"

echo Installazione file...
echo ----------------------------------------

REM Copia script principale
if exist "%SCRIPT_DIR%check_ransomware_activity.ps1" (
    copy /Y "%SCRIPT_DIR%check_ransomware_activity.ps1" "%LOCAL_DIR%\" >nul
    echo [OK] check_ransomware_activity.ps1
) else (
    echo [ERRORE] File check_ransomware_activity.ps1 non trovato!
    goto :error
)

REM Copia wrapper BAT
if exist "%SCRIPT_DIR%check_ransomware.bat" (
    copy /Y "%SCRIPT_DIR%check_ransomware.bat" "%LOCAL_DIR%\" >nul
    echo [OK] check_ransomware.bat
) else (
    echo [WARN] File check_ransomware.bat non trovato (opzionale)
)

REM Copia configurazione
if exist "%SCRIPT_DIR%ransomware_config.json" (
    if not exist "%LOCAL_DIR%\ransomware_config.json" (
        copy /Y "%SCRIPT_DIR%ransomware_config.json" "%LOCAL_DIR%\" >nul
        echo [OK] ransomware_config.json
    ) else (
        echo [INFO] ransomware_config.json già esistente (non sovrascritto)
    )
) else (
    echo [WARN] File ransomware_config.json non trovato (opzionale)
)

echo.
echo ========================================================================
echo   Configurazione
echo ========================================================================
echo.

REM Chiedi se modificare la configurazione
set /p CONFIG_NOW="Vuoi configurare le share da monitorare ora? (S/N): "
if /i "%CONFIG_NOW%"=="S" (
    echo.
    echo Aprendo editor di configurazione...
    if exist "%LOCAL_DIR%\ransomware_config.json" (
        notepad "%LOCAL_DIR%\ransomware_config.json"
    ) else (
        echo [ERRORE] File di configurazione non trovato!
    )
)

echo.
echo ========================================================================
echo   Test Funzionamento
echo ========================================================================
echo.

set /p TEST_NOW="Vuoi testare lo script ora? (S/N): "
if /i "%TEST_NOW%"=="S" (
    echo.
    echo Esecuzione test...
    echo ----------------------------------------
    powershell.exe -ExecutionPolicy Bypass -File "%LOCAL_DIR%\check_ransomware_activity.ps1" -Debug
    echo ----------------------------------------
    echo.
)

echo.
echo ========================================================================
echo   Riavvio Servizio CheckMK
echo ========================================================================
echo.

set /p RESTART_NOW="Vuoi riavviare il servizio CheckMK Agent ora? (S/N): "
if /i "%RESTART_NOW%"=="S" (
    echo.
    echo Riavvio servizio...
    
    REM Trova il nome del servizio CheckMK
    set "SERVICE_NAME="
    sc query CheckMkService >nul 2>&1
    if %errorLevel% EQU 0 (
        set "SERVICE_NAME=CheckMkService"
    )
    
    sc query checkmk >nul 2>&1
    if %errorLevel% EQU 0 (
        set "SERVICE_NAME=checkmk"
    )
    
    if defined SERVICE_NAME (
        net stop !SERVICE_NAME! >nul 2>&1
        timeout /t 2 /nobreak >nul
        net start !SERVICE_NAME! >nul 2>&1
        
        sc query !SERVICE_NAME! | find "RUNNING" >nul
        if %errorLevel% EQU 0 (
            echo [OK] Servizio !SERVICE_NAME! riavviato con successo
        ) else (
            echo [WARN] Problema nel riavvio del servizio !SERVICE_NAME!
        )
    ) else (
        echo [WARN] Servizio CheckMK non trovato
        echo        Riavviare manualmente: net stop CheckMkService ^&^& net start CheckMkService
    )
)

echo.
echo ========================================================================
echo   Installazione Completata!
echo ========================================================================
echo.
echo File installati in: %LOCAL_DIR%
echo.
echo PROSSIMI PASSI:
echo.
echo 1. Configura le share da monitorare:
echo    Modifica: %LOCAL_DIR%\ransomware_config.json
echo.
echo 2. In CheckMK Web UI:
echo    - Vai su Setup ^> Hosts ^> [tuo-host] ^> Services
echo    - Click "Run service discovery"
echo    - Cerca "Ransomware_Detection"
echo    - Click "Accept all"
echo.
echo 3. Configura le notifiche per alert CRITICAL
echo.
echo 4. Testa con: %SCRIPT_DIR%test_ransomware_detection.ps1
echo.
echo DOCUMENTAZIONE:
echo    %SCRIPT_DIR%README-Ransomware-Detection.md
echo    %SCRIPT_DIR%QUICK_START.md
echo.
echo ========================================================================
echo.

pause
exit /b 0

:error
echo.
echo [ERRORE] Installazione fallita!
echo.
pause
exit /b 1
