@echo off
REM ============================================================================
REM Wrapper BAT per check_ransomware_activity.ps1
REM ============================================================================
REM
REM Questo wrapper permette a CheckMK Agent di eseguire correttamente lo
REM script PowerShell bypassando le ExecutionPolicy e problemi di associazione
REM
REM Uso: Copiare questo file insieme a check_ransomware_activity.ps1
REM      nella directory C:\ProgramData\checkmk\agent\local\
REM
REM ============================================================================

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0check_ransomware_activity.ps1"
