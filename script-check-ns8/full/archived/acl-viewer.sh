#!/bin/bash
#
# acl-viewer.sh - Visualizzatore semplice ACL Samba Share NS8
# 
# Legge i file *_smbacl.txt generati da ns8-biweekly-audit-report.sh
# e mostra i permessi in formato leggibile italiano
#
# Usage: ./acl-viewer.sh [audit_directory]
#
# Se non specificato, usa l'audit più recente in /var/tmp/ns8-audit-*

set -euo pipefail

# Funzioni helper
log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
die() { echo "[ERR] $*" >&2; exit 1; }

# Traduzione permessi Windows → Italiano
translate_permissions() {
    local perms="$1"
    case "$perms" in
        *FULL*|*0x001f01ff*)
            echo "Controllo Totale"
            ;;
        *RWXD*|*0x001301bf*)
            echo "Lettura e Scrittura"
            ;;
        *READ*|*0x00120089*)
            echo "Solo Lettura"
            ;;
        *)
            echo "Permessi: $perms"
            ;;
    esac
}

# Main
main() {
    local audit_dir="${1:-}"
    
    # Se non specificato, trova l'audit più recente
    if [ -z "$audit_dir" ]; then
        audit_dir=$(find /var/tmp -maxdepth 1 -type d -name "ns8-audit-*" 2>/dev/null | sort -r | head -1)
        if [ -z "$audit_dir" ]; then
            die "Nessuna directory audit trovata in /var/tmp/ns8-audit-*"
        fi
        log "Uso audit directory: $audit_dir"
    fi
    
    local acl_dir="$audit_dir/03_shares/acls"
    
    if [ ! -d "$acl_dir" ]; then
        die "Directory ACL non trovata: $acl_dir"
    fi
    
    # Header tabella
    echo ""
    echo "==============================================================================="
    echo "  REPORT PERMESSI SHARE NS8"
    echo "==============================================================================="
    echo ""
    echo "Audit directory: $audit_dir"
    echo ""
    
    # Rileva modulo Samba (disabilita espansione gruppi - troppo lenta)
    local samba_module=""
    
    # Header tabella
    printf "%-20s %-35s %-30s %-25s\n" "SHARE" "PERCORSO" "ENTITA" "PERMESSI"
    printf "%-20s %-35s %-30s %-25s\n" \
        "--------------------" \
        "-----------------------------------" \
        "------------------------------" \
        "-------------------------"
    
    # Conta share
    local share_count=0
    local shares_report="$audit_dir/03_shares/shares_report.tsv"
    
    # Itera su tutti i file ACL - usa approccio semplice con find e for
    for acl_file in $(find "$acl_dir" -name "*_smbacl.txt" -type f | sort); do
        local share_name=$(basename "$acl_file" _smbacl.txt)
        share_count=$((share_count + 1))
        
        # Leggi path dalla shares_report.tsv
        local share_path=""
        if [ -f "$shares_report" ]; then
            share_path=$(grep "^$share_name	" "$shares_report" | cut -f2)
        fi
        
        # Estrai ACL - usa approccio semplice senza array
        local acl_lines=$(grep "^ACL:" "$acl_file" | grep -vE "^ACL:(NT AUTHORITY|BUILTIN)")
        
        if [ -z "$acl_lines" ]; then
            # Share senza permessi utente
            printf "%-20s %-35s %-30s %-25s\n" \
                "$share_name" \
                "${share_path:0:35}" \
                "[solo sistema]" \
                "-"
            continue
        fi
        
        # Prima riga con dati share
        local first_line=1
        
        # Processa ogni ACL - usa while read da variabile (no subshell issues)
        echo "$acl_lines" | while IFS= read -r acl_line; do
            [ -z "$acl_line" ] && continue
            
            # Parse ACL: ACL:DOMAIN\entity:ALLOWED/flags/perms
            local entity=$(echo "$acl_line" | cut -d: -f2)
            local perms=$(echo "$acl_line" | cut -d: -f3 | cut -d/ -f3)
            
            # Traduzione permessi
            local perms_italian=$(translate_permissions "$perms")
            
            # Prima riga mostra share e path, successive solo entità e permessi
            if [ $first_line -eq 1 ]; then
                printf "%-20s %-35s %-30s %-25s\n" \
                    "$share_name" \
                    "${share_path:0:35}" \
                    "${entity:0:30}" \
                    "$perms_italian"
                first_line=0
            else
                printf "%-20s %-35s %-30s %-25s\n" \
                    "" \
                    "" \
                    "${entity:0:30}" \
                    "$perms_italian"
            fi
        done
    done
    
    # Footer
    echo ""
    echo "==============================================================================="
    echo "Totale share analizzate: $share_count"
    echo ""
    echo "NOTE:"
    echo "  - Per vedere i membri di un gruppo AD:"
    echo "    runagent -m samba1 podman exec samba-dc samba-tool group listmembers NOME_GRUPPO"
    echo ""
}

# Esegui
main "$@"
