#!/bin/bash
# check_ns8_mail_services.sh
# Controllo servizi mail principali leggendo lo stato dei container
# + numero sessioni IMAP attive da doveadm
# + stato critico se rilevato vsz_limit nei log di Dovecot
# + warning se VszLimit non Ã¨ impostato
# + conteggio delle occorrenze recenti di vsz_limit nei log

echo "<<<local>>>"

# Numero di righe da controllare nei log (per non scansionare file enormi)
LOG_LINES=500

# Scopro tutte le istanze mail (mail1, mail2, ...)
MAIL_INSTANCES=$(runagent -l | grep '^mail')

# Servizi target = container interni
TARGET_SERVICES=("clamav" "rspamd" "dovecot" "postfix")

for INSTANCE in $MAIL_INSTANCES; do
    # Elenco container e stato dentro l'istanza
    STATS=$(runagent -m "$INSTANCE" podman ps --format "{{.Names}} {{.Status}}" 2>/dev/null)

    for SVC in "${TARGET_SERVICES[@]}"; do
        STATUS_LINE=$(echo "$STATS" | grep "^${SVC} ")
        if [[ -n "$STATUS_LINE" ]]; then
            STATE=$(echo "$STATUS_LINE" | awk '{print $2}')
            if [[ "$STATE" == "Up" ]]; then
                echo "0 ${SVC} - ${SVC} attivo"

                # Se Ã¨ dovecot, aggiungo controlli extra
                if [[ "$SVC" == "dovecot" ]]; then
                    # Numero sessioni IMAP
                    IMAP_COUNT=$(runagent -m "$INSTANCE" podman exec "$SVC" doveadm who 2>/dev/null | wc -l)
                    if [[ "$IMAP_COUNT" -gt 0 ]]; then
                        echo "0 imap_sessions - Sessioni IMAP attive: $IMAP_COUNT"
                    else
                        echo "1 imap_sessions - Nessuna sessione IMAP attiva"
                    fi

                    # Limite configurato tramite config show
                    VSZ=$(config show dovecot 2>/dev/null | grep -i VszLimit | awk '{print $2}')

                    # Conteggio errori vsz_limit nelle ultime LOG_LINES righe
                    OCCURRENCES=$(runagent -m "$INSTANCE" podman exec "$SVC" sh -c "tail -n ${LOG_LINES} /var/log/dovecot* 2>/dev/null | grep -c 'Cannot allocate memory due to vsz_limit'")

                    if [[ "$OCCURRENCES" -gt 0 ]]; then
                        if [[ -n "$VSZ" ]]; then
                            echo "2 dovecot_vszlimit - CRIT: rilevato vsz_limit (${OCCURRENCES} occorrenze nelle ultime ${LOG_LINES} righe, limite configurato=${VSZ})"
                        else
                            echo "2 dovecot_vszlimit - CRIT: rilevato vsz_limit (${OCCURRENCES} occorrenze nelle ultime ${LOG_LINES} righe, limite non impostato)"
                        fi
                    else
                        if [[ -n "$VSZ" ]]; then
                            echo "0 dovecot_vszlimit - Nessun allarme nei log (limite configurato=${VSZ})"
                        else
                            echo "1 dovecot_vszlimit - WARNING: Nessun allarme nei log (limite non impostato)"
                        fi
                    fi
                fi
            else
                echo "2 ${SVC} - ${SVC} non attivo"
            fi
        else
            echo "3 ${SVC} - ${SVC} non trovato"
        fi
    done
done
