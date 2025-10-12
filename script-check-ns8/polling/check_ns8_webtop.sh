#!/bin/bash
# check_ns8_webtop.sh
# Monitoraggio WebTop in NS8 per Checkmk
# Controlla la presenza delle istanze e la raggiungibilità HTTP

echo "<<<local>>>"

# Recupera dominio dal FQDN host
FQDN=$(hostname -f)
DOMAIN=$(echo "$FQDN" | cut -d. -f2-)

if [[ -z "$DOMAIN" ]]; then
    echo "2 Webtop5 - Nessun dominio rilevato da hostname -f"
    exit 1
fi

# Verifica istanze WebTop
INSTANCES=$(runagent -l | grep -E '^webtop')

if [[ -z "$INSTANCES" ]]; then
    echo "2 Webtop5 - Nessuna istanza WebTop trovata"
    exit 0
fi

# Controllo raggiungibilità interfaccia
URL="https://webtop.${DOMAIN}/webtop/"
CODE=$(curl -sk -o /dev/null -w "%{http_code}" "$URL")

if [[ "$CODE" == "200" ]]; then
    echo "0 Webtop5 - WebTop risponde su $URL (HTTP 200)"
else
    echo "2 Webtop5 - WebTop NON risponde su $URL (HTTP $CODE)"
fi
