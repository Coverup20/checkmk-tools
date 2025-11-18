#!/bin/bash
# check_ns8_containers.sh
# Monitoraggio stato e risorse dei container NS8 via runagent, con nomi friendly

echo "<<<local>>>"

friendly_name() {
    case $1 in
        ldapproxy*) echo "LdapProxy" ;;
        openldap*) echo "OpenLDAP" ;;
        webtop*) echo "WebTop" ;;
        nextcloud*) echo "Nextcloud" ;;
        nethvoice*) echo "NethVoice" ;;
        traefik*) echo "Traefik" ;;
        mail*) echo "Mail" ;;
        samba*) echo "Samba" ;;
        mattermost*) echo "Mattermost" ;;
        metrics*) echo "Metrics" ;;
        loki*) echo "Loki" ;;
        nethsecurity*) echo "NethSecurity" ;;
        *) echo "$1" ;;
    esac
}

INSTANCES=$(runagent -l | grep -vE '^(cluster|node)$')

for C in $INSTANCES; do
    NAME=$(friendly_name "$C")

    # Stato container
    if runagent -m "$C" true >/dev/null 2>&1; then
        echo "0 ${NAME} - ${NAME} attivo"
    else
        echo "2 ${NAME} - ${NAME} NON attivo"
        continue
    fi

    # Risorse dal podman interno
    STATS=$(runagent -m "$C" podman stats --no-stream --format "{{.CPUPerc}} {{.MemUsage}} {{.MemPerc}}" 2>/dev/null | head -1)
    if [[ -n "$STATS" ]]; then
        CPU=$(echo "$STATS" | awk '{print $1}' | tr -d '%')
        MEM_USED=$(echo "$STATS" | awk '{print $2}')
        MEM_PCT=$(echo "$STATS" | awk '{print $3}' | tr -d '%')

        echo "0 ${NAME}_CPU - CPU ${CPU}%"
        echo "0 ${NAME}_RAM - RAM ${MEM_USED} (${MEM_PCT}%)"
    fi

    # Sessioni IMAP (solo per Mail con doveadm)
    if [[ "$NAME" == "Mail" ]]; then
        IMAP_COUNT=$(runagent -m "$C" doveadm who 2>/dev/null | tail -n +2 | wc -l)
        if [[ "$IMAP_COUNT" -gt 0 ]]; then
            echo "0 Mail_IMAP - Sessioni IMAP attive: $IMAP_COUNT"
        else
            echo "1 Mail_IMAP - Nessuna sessione IMAP attiva"
        fi
    fi
done
