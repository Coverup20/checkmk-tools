# CheckMK Agent + FRPC Interactive Installer for Windows

**Version**: 1.0  
**Date**: 2025-11-07  
**Platforms**: Windows 10, 11, Server 2019, 2022  
**Language**: PowerShell  

## Overview

`install-agent-interactive.ps1` è uno script PowerShell interattivo che automatizza l'installazione del CheckMK Agent e del client FRPC su sistemi Windows.

## Features

✅ **OS Detection**
- Rileva Windows 10, 11, Server 2019, 2022
- Mostra versione e architettura (x86/x64)
- Conferma iniziale prima di procedere

✅ **CheckMK Agent Installation**
- Download MSI da monitoring.nethlab.it
- Installazione silente
- Servizio Windows automatico
- Porta TCP 6556

✅ **FRPC Client Installation**
- Download da GitHub releases
- Configurazione TOML interattiva
- Servizio Windows Windows con autostart
- Log in C:\ProgramData\frp\logs

✅ **Complete Uninstallation**
- Flag: `--uninstall`, `--uninstall-frpc`, `--uninstall-agent`
- Rimozione completa di servizi, file, configurazioni
- Terminazione processi

✅ **User-Friendly Interface**
- Colorized output
- Detailed error messages
- Progress indicators
- File size reporting

## Requirements

- **PowerShell**: 5.0 o superiore (Windows 10+)
- **Administrator rights**: Richiesti per installazione/disinstallazione
- **Internet connection**: Per download dei pacchetti
- **Windows OS**: 10, 11, Server 2019, o 2022

## Installation Paths

| Component | Path |
|-----------|------|
| CheckMK Agent | `C:\Program Files (x86)\checkmk\service\` |
| FRPC Binary | `C:\Program Files\frp\frpc.exe` |
| FRPC Config | `C:\ProgramData\frp\frpc.toml` |
| FRPC Logs | `C:\ProgramData\frp\logs\` |

## Usage

### Basic Installation
```powershell
# Run as Administrator
.\install-agent-interactive.ps1
```

### Installation Steps
1. Script rileva SO Windows
2. Mostra informazioni sistema
3. Chiede conferma utente
4. Installa CheckMK Agent
5. Chiede se installare FRPC
6. Configura servizi Windows
7. Mostra riepilogo

### Uninstallation
```powershell
# Disinstalla solo FRPC
.\install-agent-interactive.ps1 --uninstall-frpc

# Disinstalla solo Agent
.\install-agent-interactive.ps1 --uninstall-agent

# Disinstalla tutto
.\install-agent-interactive.ps1 --uninstall
```

### Help
```powershell
.\install-agent-interactive.ps1 --help
.\install-agent-interactive.ps1 -h
```

## Configuration

### Environment Variables
```powershell
$CHECKMK_VERSION = "2.4.0p14"     # Version to download
$FRP_VERSION = "0.64.0"            # FRPC version
$DOWNLOAD_DIR = "$env:TEMP\CheckMK-Setup"  # Temporary download location
```

### FRPC Interactive Configuration
Lo script chiederà:
- **Nome host**: Default = Computer name
- **Server FRP**: Default = monitor.nethlab.it
- **Porta remota**: Es. 20001 (obbligatoria)
- **Token di sicurezza**: Default = conduit-reenact-talon-macarena-demotion-vaguely

## Output Example

```
╔════════════════════════════════════════════════════════════╗
│  Installazione Interattiva CheckMK Agent + FRPC per Windows│
│  Version: 1.0 - 2025-11-07                                │
╚════════════════════════════════════════════════════════════╝

📊 Rilevamento Sistema Operativo...

╔════════════════════════════════════════════════════════════╗
│             RILEVAMENTO SISTEMA OPERATIVO                 │
╚════════════════════════════════════════════════════════════╝

📌 Sistema Rilevato:
   OS: Windows 11
   Versione: 10.0.22631
   Architettura: x64

📌 Questa installazione utilizzerà:
   • CheckMK Agent (plain TCP on port 6556)
   • Servizio Windows: CheckMK Agent

============================================================
Procedi con l'installazione su questo sistema? [s/N]:
============================================================
```

## Useful PowerShell Commands

```powershell
# Visualizza servizi CheckMK/FRPC
Get-Service | Where-Object {$_.Name -like '*CheckMK*' -or $_.Name -like '*frpc*'}

# Riavvia servizio Agent
Restart-Service -Name "CheckMK Agent"

# Visualizza stato servizio
Get-Service -Name "CheckMK Agent" | Format-List

# Visualizza ultimi 50 righe del log FRPC
Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 50 -Follow

# Ferma FRPC
Stop-Service -Name "frpc"

# Avvia FRPC
Start-Service -Name "frpc"

# Verifica se porta 6556 è in ascolto
netstat -an | findstr :6556

# Test agent locale
(New-Object Net.Sockets.TcpClient).Connect("127.0.0.1", 6556)
```

## Services

### CheckMK Agent Service
- **Name**: CheckMK Agent
- **Type**: Windows Service
- **Port**: 6556 (TCP listener)
- **Startup**: Automatic

### FRPC Service
- **Name**: frpc
- **Type**: Windows Service
- **Startup**: Automatic
- **Config**: `C:\ProgramData\frp\frpc.toml`
- **Log**: `C:\ProgramData\frp\logs\frpc.log`

## Troubleshooting

### Problema: "Script non trovato"
```powershell
# Esegui da PowerShell come Administrator
cd C:\Users\Marzio\Desktop\CheckMK\Script\script-tools
.\install-agent-interactive.ps1
```

### Problema: "Accesso negato - non sei Administrator"
```powershell
# Apri PowerShell come Administrator
# Tasto destro → "Run as Administrator"
```

### Problema: FRPC non si avvia
```powershell
# Visualizza errore servizio
Get-Service -Name "frpc" -ErrorAction SilentlyContinue
Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 100

# Riprova manualmente
C:\Program Files\frp\frpc.exe -c C:\ProgramData\frp\frpc.toml
```

### Problema: Agent non risponde
```powershell
# Verifica servizio
Get-Service -Name "CheckMK Agent"

# Verifica porta
netstat -an | findstr :6556

# Riavvia
Restart-Service -Name "CheckMK Agent"
```

## Logs & Diagnostics

### Download Log
- Location: `C:\Users\{User}\AppData\Local\Temp\CheckMK-Setup\checkmk-install.log`

### FRPC Log
- Location: `C:\ProgramData\frp\logs\frpc.log`
- Level: debug (verboso per troubleshooting)

### Event Viewer
```powershell
# Visualizza errori servizi
Get-EventLog -LogName System -Source "Service Control Manager" -Newest 50
```

## Compatibility Matrix

| OS | Version | x86 | x64 | Status |
|----|---------|-----|-----|--------|
| Windows 10 | 21H2+ | ✅ | ✅ | Supported |
| Windows 11 | All | ❌ | ✅ | Supported (x64 only) |
| Windows Server 2019 | LTSC | ✅ | ✅ | Supported |
| Windows Server 2022 | LTSC | ✅ | ✅ | Supported |

## Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| (none) | Installazione normale con prompts | `.\install-agent-interactive.ps1` |
| `--help` | Mostra help | `.\install-agent-interactive.ps1 --help` |
| `-h` | Mostra help | `.\install-agent-interactive.ps1 -h` |
| `--uninstall` | Disinstalla tutto | `.\install-agent-interactive.ps1 --uninstall` |
| `--uninstall-agent` | Disinstalla solo Agent | `.\install-agent-interactive.ps1 --uninstall-agent` |
| `--uninstall-frpc` | Disinstalla solo FRPC | `.\install-agent-interactive.ps1 --uninstall-frpc` |

## Architecture Differences from Linux Version

| Feature | Linux (bash) | Windows (PowerShell) |
|---------|--------------|---------------------|
| **Service Manager** | systemd / init.d | Windows Services (sc.exe) |
| **Package Format** | DEB / RPM / opkg | MSI / ZIP |
| **Config Paths** | /etc/, /usr/bin | C:\Program Files, C:\ProgramData |
| **Listener** | socat / systemd socket | Windows TCP Listener |
| **Download Tool** | wget | Net.WebClient / Invoke-WebRequest |
| **Log Paths** | /var/log | C:\ProgramData |

## Uninstallation Cleanup

When uninstalling, the script removes:

**CheckMK Agent:**
- ✅ MSI Package (msiexec.exe)
- ✅ Service "CheckMK Agent"
- ✅ Directory: `C:\Program Files (x86)\checkmk`
- ✅ Config: `C:\ProgramData\checkmk`
- ✅ Processes: check_mk_agent.exe

**FRPC:**
- ✅ Service "frpc"
- ✅ Directory: `C:\Program Files\frp`
- ✅ Config: `C:\ProgramData\frp`
- ✅ Logs: `C:\ProgramData\frp\logs`
- ✅ Processes: frpc.exe

## Advanced Configuration

### Custom FRPC Tunnel
Edit `C:\ProgramData\frp\frpc.toml` manually:
```toml
[custom-tunnel]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 3389  # RDP example
remote_port = 20002
```

Then restart service:
```powershell
Restart-Service -Name "frpc"
```

## Support

For issues or questions:
1. Check logs: `C:\ProgramData\frp\logs\frpc.log`
2. Verify services: `Get-Service -Name "*frpc*","CheckMK Agent"`
3. Review EventLog for Windows errors
4. Ensure Administrator rights are used

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-07 | Initial release |

---

**Author**: CheckMK Tools Project  
**Repository**: https://github.com/Coverup20/checkmk-tools  
**License**: Check main repository
