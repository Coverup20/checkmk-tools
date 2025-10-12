# ub-cmk-interactive

Setup base Ubuntu + Checkmk (URL richiesto a runtime).

Contiene:
- SSH: porta, root login, timeout, cambio password root
- NTP: pool globale 0–3.pool.ntp.org
- Pacchetti base + unattended-upgrades
- UFW + Fail2Ban (sshd)
- Certbot (senza challenge) + plugin webserver
- Checkmk: installazione con URL richiesto a runtime, creazione e avvio site `monitoring`
- Script di verifica

## Uso
```bash
unzip ub-cmk-interactive.zip -d ~/
cd ~/ub-cmk-interactive
cp .env.example .env   # oppure usa .env già presente
sudo ./bootstrap.sh
./check-verifica.sh
```
