# ----------------------------
# 5. Fix agent Checkmk (solo per Debian/Proxmox con Raw Edition)
# ----------------------------
if [ "$OS_TYPE" = "debian" ] || [ "$OS_TYPE" = "proxmox" ]; then
    echo ">>> Verifica stato agent Checkmk su $OS_TYPE"

    if systemctl is-active --quiet cmk-agent-ctl-daemon.service; then
        echo ">>> Disattivo agent TLS (non supportato su Raw Edition)..."
        systemctl stop cmk-agent-ctl-daemon.service
        systemctl disable cmk-agent-ctl-daemon.service
        pkill -9 -f cmk-agent-ctl || true
    fi

    echo ">>> Configuro agent in modalitÃ  Plaintext"
    cat > /etc/systemd/system/check-mk-agent-plain.socket <<EOF
[Unit]
Description=Checkmk Agent (Plaintext Socket)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF

    cat > /etc/systemd/system/check-mk-agent-plain@.service <<EOF
[Unit]
Description=Checkmk Agent (Plaintext)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=/usr/bin/check_mk_agent
StandardInput=socket
EOF

    systemctl daemon-reexec
    systemctl enable --now check-mk-agent-plain.socket

    echo ">>> Test agent locale:"
    nc 127.0.0.1 6556 | head || true
fi
