#!/bin/bash
# CheckMK plugin - Monitoraggio pacchetti opkg
# Controlla pacchetti installati, aggiornamenti disponibili, modifiche recenti

# Verifica opkg disponibile
if ! command -v opkg >/dev/null 2>&1; then
    echo "2 OPKG_Packages - opkg non disponibile"
    exit 0
fi

# Conta pacchetti installati
installed_count=$(opkg list-installed 2>/dev/null | wc -l)

# Verifica aggiornamenti disponibili (solo se non causa timeout)
updates_available=0
if timeout 10 opkg list-upgradable >/dev/null 2>&1; then
    updates_available=$(opkg list-upgradable 2>/dev/null | wc -l)
fi

# Leggi info repository
last_update_file="/var/opkg-lists"
last_update_age=0
if [[ -d "$last_update_file" ]]; then
    last_update_time=$(find "$last_update_file" -type f -printf '%T@\n' 2>/dev/null | sort -n | tail -1 | cut -d. -f1)
    if [[ -n "$last_update_time" ]]; then
        current_time=$(date +%s)
        last_update_age=$(( (current_time - last_update_time) / 86400 ))  # giorni
    fi
fi

# Leggi log opkg recenti (ultimi 7 giorni)
LOG_FILE="/var/log/messages"
recent_installs=0
recent_removes=0

if [[ -f "$LOG_FILE" ]]; then
    # Cerca installazioni/rimozioni recenti (usa head per evitare output multipli)
    recent_installs=$(grep "opkg.*install" "$LOG_FILE" 2>/dev/null | wc -l)
    recent_removes=$(grep "opkg.*remove" "$LOG_FILE" 2>/dev/null | wc -l)
fi

# Verifica spazio disponibile in /overlay (dove vanno i pacchetti)
overlay_free=0
overlay_used_pct=0
if df /overlay >/dev/null 2>&1; then
    overlay_info=$(df /overlay | tail -1)
    overlay_free=$(echo "$overlay_info" | awk '{print $4}')
    overlay_used_pct=$(echo "$overlay_info" | awk '{print $5}' | tr -d '%')
fi

# Determina stato
status=0
status_text="OK"

if [[ $overlay_used_pct -ge 95 ]]; then
    status=2
    status_text="CRITICAL - Spazio /overlay: ${overlay_used_pct}%"
elif [[ $overlay_used_pct -ge 85 ]]; then
    status=1
    status_text="WARNING - Spazio /overlay: ${overlay_used_pct}%"
elif [[ $updates_available -ge 10 ]]; then
    status=1
    status_text="WARNING - $updates_available aggiornamenti disponibili"
elif [[ $last_update_age -ge 30 ]]; then
    status=1
    status_text="WARNING - Lista pacchetti obsoleta ($last_update_age giorni)"
elif [[ $updates_available -gt 0 ]]; then
    status=0
    status_text="OK - $updates_available aggiornamenti disponibili"
else
    status=0
    status_text="OK - $installed_count pacchetti installati"
fi

# Output CheckMK
echo "$status OPKG_Packages installed=$installed_count updates=$updates_available;10;20;0 overlay_used_pct=$overlay_used_pct;85;95;0;100 - $status_text | installed=$installed_count updates_available=$updates_available overlay_free_kb=$overlay_free overlay_used_pct=$overlay_used_pct last_update_age_days=$last_update_age recent_installs=$recent_installs recent_removes=$recent_removes"

# Dettaglio ultimi pacchetti installati/rimossi (se presenti)
if [[ $recent_installs -gt 0 ]] || [[ $recent_removes -gt 0 ]]; then
    echo "0 OPKG_Recent_Changes - Installs: $recent_installs, Removes: $recent_removes (last 7 days)"
fi

# Lista aggiornamenti disponibili (solo se pochi, per non appesantire)
if [[ $updates_available -gt 0 ]] && [[ $updates_available -le 5 ]]; then
    upgradable_list=$(opkg list-upgradable 2>/dev/null | head -5 | awk '{print $1}' | tr '\n' ' ')
    if [[ -n "$upgradable_list" ]]; then
        echo "0 OPKG_Updates_Available - Packages: $upgradable_list"
    fi
fi
