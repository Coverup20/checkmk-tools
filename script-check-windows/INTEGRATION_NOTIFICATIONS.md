# Integrazione Ransomware Detection con Sistema Notifiche CheckMK

## Overview

Questo documento spiega come integrare il sistema di rilevamento ransomware con le notifiche CheckMK esistenti (email, Telegram, etc.).

## Architettura

```
CheckMK Detection
       ↓
  Local Check (check_ransomware_activity.ps1)
       ↓
  Service: Ransomware_Detection
       ↓
  CheckMK Notifications
       ↓
  ├── Email (mail_realip_hybrid)
  ├── Telegram (telegram_realip)
  └── Custom Handler
```

## 1. Configurazione Base in CheckMK

### Setup → Notifications → New Rule

```python
# Regola per Ransomware CRITICAL
{
    'description': 'Ransomware Detection - CRITICAL Alert',
    'disabled': False,
    
    # Condizioni
    'conditions': {
        'match_services': ['^Ransomware_'],
        'match_servicestates': [2],  # CRITICAL only
    },
    
    # Contatti
    'contact_selection': ['security_team', 'it_admins'],
    
    # Metodo notifica
    'notification_method': ('mail', {
        'subject': '🚨 RANSOMWARE: $HOSTNAME$/$SERVICEDESC$ is $SERVICESTATE$',
        'body': 'both',
    }),
}
```

## 2. Integrazione Email Esistente

Utilizza lo script esistente `mail_realip_hybrid` dalla directory `script-notify-checkmk`.

## 3. Integrazione Telegram

Utilizza lo script esistente `telegram_realip` dalla directory `script-notify-checkmk`.

## 4. Test Notifiche

### Test Manuale

```bash
# In CheckMK server
cmk --notify --test-mode \
    NOTIFY_SERVICEDESC='Ransomware_Detection' \
    NOTIFY_SERVICESTATE='CRITICAL' \
    NOTIFY_HOSTNAME='fileserver01'
```

## Checklist Deploy

- [ ] Regole notifica create in CheckMK UI
- [ ] Test manuale eseguito con successo
- [ ] Team informato sul tipo di alert
- [ ] Procedure IR documentate

---

**Vedi anche:**
- `../script-notify-checkmk/mail_realip_hybrid` - Script email esistente
- `../script-notify-checkmk/telegram_realip` - Script Telegram esistente
