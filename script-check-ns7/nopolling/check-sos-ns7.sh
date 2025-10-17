#!/bin/bash
# check-sos-ns7.sh
# Local check per Check_MK: stato sessione SOS (WindMill VPN + SSH) - senza ID
# NethServer 7.9

SERVICE_NAME="SOS_Session"

VPN_UNIT="don-openvpn"
SSH_UNIT="don-sshd"

is_active() {
    systemctl is-active --quiet "$1" && echo 1 || echo 0
}

vpn_status=$(is_active "$VPN_UNIT")
ssh_status=$(is_active "$SSH_UNIT")

if [[ "$vpn_status" -eq 1 && "$ssh_status" -eq 1 ]]; then
    state=1
    msg="SOS attivo"
elif [[ "$vpn_status" -eq 0 && "$ssh_status" -eq 0 ]]; then
    state=0
    msg="SOS disattivo"
else
    state=2
    msg="SOS PARZIALE: VPN=${vpn_status} SSH=${ssh_status}"
fi

echo "$state $SERVICE_NAME - $msg | vpn=$vpn_status ssh=$ssh_status"

