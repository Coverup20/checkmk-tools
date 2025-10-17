#!/bin/bash
# check-sosid-ns7.sh
# Local check per Check_MK: mostra l'ID della sessione SOS se attivo
# NethServer 7.9

SERVICE_NAME="SOS_Session_ID"

VPN_UNIT="don-openvpn"
SSH_UNIT="don-sshd"

is_active() {
    systemctl is-active --quiet "$1" && echo 1 || echo 0
}

vpn_status=$(is_active "$VPN_UNIT")
ssh_status=$(is_active "$SSH_UNIT")

if [[ "$vpn_status" -eq 1 && "$ssh_status" -eq 1 ]]; then
    session_id=$(don status 2>/dev/null | awk '/Session ID/ {print $3}')
    if [[ -n "$session_id" ]]; then
        state=1
        msg="SOS attivo - ID $session_id"
    else
        state=2
        msg="SOS attivo ma ID non trovato"
    fi
else
    state=0
    msg="SOS non attivo"
fi

echo "$state $SERVICE_NAME - $msg"

