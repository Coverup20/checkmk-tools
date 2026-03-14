#!/bin/bash
################################################################################
# NS8 Audit Report - Unified Version (Collector + Viewer)
################################################################################
# Scopo: Report quindicinale completo ambiente NethServer 8
#
# Raccoglie:
#   1) Utenti Active Directory (Samba)
#   2) Scadenze password utenti AD
#   3) Permessi share di rete (Samba)
#   4) Condivisioni account posta WebTop (se disponibile)
#
# Visualizza:
#   - Tabella formattata permessi ACL share
#   - Report riepilogativo completo
#
# Output: Directory /var/tmp/ns8-audit-YYYYMMDD-HHMMSS/
#
# Uso:
#  ./ns8-audit-report-unified.sh
#   ./ns8-audit-report-unified.sh --output-dir /custom/path
#   ./ns8-audit-report-unified.sh --no-display  # Skip visualizzazione ACL
#
#
# Requisiti:
#   - NS8 con modulo samba installato
#   - runagent disponibile nel PATH
#   - Permessi di esecuzione su moduli NS8
################################################################################

set -euo pipefail

# Configurazione
REPORT_DATE=$(date +%Y%m%d-%H%M%S)
OUTPUT_BASE="${OUTPUT_DIR:-/tmp}"
OUTPUT_DIR="${OUTPUT_BASE}/ns8-audit-${REPORT_DATE}"
MAX_PWD_AGE_DAYS=42
SHOW_ACL_REPORT=1  # Default: mostra report ACL
VERSION="2.4.0"   # Versione script (aggiornare ad ogni modifica)

# Gruppi AD di sistema da escludere dal report
EXCLUDE_GROUPS=(
    "Denied RODC Password Replication Group"
    "DnsUpdateProxy"
    "Enterprise Read-Only Domain Controllers"
    "Network Configuration Operators"
    "Pre-Windows 2000 Compatible Access"
    "Incoming Forest Trust Builders"
    "Terminal Server License Servers"
    "Cryptographic Operators"
    "Remote Desktop Users"
    "RAS and IAS Servers"
    "Event Log Readers"
    "Guests"
    "Certificate Service DCOM Access"
    "Read-Only Domain Controllers"
    "Windows Authorization Access Group"
    "Performance Monitor Users"
)

# Cache globale per conversione SID → Username (usata da sid_to_name)
declare -gA SID_CACHE

# Colori output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzioni di logging
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Funzione helper: Conversione SID → Nome utente/gruppo (USA CACHE)
sid_to_name() {
    local sid="$1"
    
    # Skip SID di sistema
    case "$sid" in
        S-1-5-18|S-1-5-32-544|S-1-5-2|S-1-1-0) 
            return 1 
            ;;
    esac
    
    # USA CACHE se disponibile (instantaneo)
    if [[ -n "${SID_CACHE[$sid]+isset}" ]]; then
        local cached="${SID_CACHE[$sid]}"
        if [[ -n "$cached" ]]; then
            echo "$cached"
            return 0
        else
            return 1
        fi
    fi
    
    # Fallback: converti se cache non disponibile
    local module="$2"
    local result=$(runagent -m "$module" podman exec samba-dc wbinfo --sid-to-name "$sid" 2>/dev/null </dev/null | cut -d' ' -f1 || echo "")
    
    if [[ -n "$result" ]]; then
        echo "$result"
        return 0
    else
        return 1
    fi
}

# Funzione helper: Decodifica access_mask → RW/RO
decode_access_mask() {
    local mask="$1"
    
    # Converti hex to decimal se necessario
    if [[ "$mask" =~ ^0x ]]; then
        mask=$((mask))
    fi
    
    # Full Control / Modify (include write bit)
    # 0x001f01ff = Full Control
    # 0x001301bf = Modify
    # Check bit WRITE (0x0002) e DELETE (0x00010000)
    if (( (mask & 0x0002) || (mask & 0x00010000) )); then
        echo "RW"
    else
        echo "RO"
    fi
}

# Verifica prerequisiti
check_prerequisites() {
    log_info "Verifica prerequisiti..."
    
    if ! command -v runagent &>/dev/null; then
        log_error "runagent non trovato nel PATH"
        exit 1
    fi
    
    # Verifica moduli NS8 disponibili
    SAMBA_MODULES=$(runagent --list-modules 2>/dev/null | grep -E '^samba[0-9]+$' || true)
    WEBTOP_MODULES=$(runagent --list-modules 2>/dev/null | grep -E '^webtop[0-9]+$' || true)
    
    if [[ -z "$SAMBA_MODULES" ]]; then
        log_error "Nessun modulo Samba trovato"
        exit 1
    fi
    
    SAMBA_MODULE=$(echo "$SAMBA_MODULES" | head -1)
    log_success "Modulo Samba: $SAMBA_MODULE"
    
    # Cerca il primo modulo WebTop con container Postgres attivo
    if [[ -z "$WEBTOP_MODULES" ]]; then
        log_warn "Nessun modulo WebTop trovato (report limitato)"
        WEBTOP_MODULE=""
    else
        WEBTOP_MODULE=""
        while IFS= read -r webtop_mod; do
            if [[ -z "$webtop_mod" ]]; then
                continue
            fi
            local postgres_check=$(runagent -m "$webtop_mod" podman ps --format '{{.Names}}' 2>/dev/null | grep -i postgres || true)
            if [[ -n "$postgres_check" ]]; then
                WEBTOP_MODULE="$webtop_mod"
                log_success "Modulo WebTop: $WEBTOP_MODULE (con Postgres attivo)"
                break
            fi
        done <<< "$WEBTOP_MODULES"
        
        if [[ -z "$WEBTOP_MODULE" ]]; then
            log_warn "Nessun modulo WebTop con Postgres attivo trovato (report limitato)"
        fi
    fi
    
    # Crea directory output
    mkdir -p "$OUTPUT_DIR"
    log_success "Directory output: $OUTPUT_DIR"
}

# Funzione 1: Raccolta utenti AD
collect_ad_users() {
    log_info "Raccolta utenti Active Directory..."
    
    local output_file="$OUTPUT_DIR/01_users.txt"
    
    if runagent -m "$SAMBA_MODULE" podman exec samba-dc samba-tool user list > "$output_file" 2>/dev/null; then
        local user_count=$(wc -l < "$output_file")
        log_success "Raccolti $user_count utenti AD (file temporaneo per processing)"
        return 0
    else
        log_error "Fallita raccolta utenti AD"
        echo "ERROR: Unable to collect AD users" > "$output_file"
        return 1
    fi
}

# Funzione 2: Raccolta scadenze password AD
collect_password_expiry() {
    log_info "Generazione report password expiry (Markdown)..."
    
    local output_md="$OUTPUT_DIR/01_password_expiry.md"
    local user_list="$OUTPUT_DIR/01_users.txt"
    
    # Leggi lista utenti
    if [[ ! -f "$user_list" ]]; then
        log_error "File utenti non trovato, esegui prima collect_ad_users"
        return 1
    fi
    
    # Inizia file MD
    {
        echo "# 🔐 Password Expiry Report"
        echo ""
        echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
        echo ""
        echo "---"
        echo ""
    } > "$output_md"
    
    local user_count=0
    local success_count=0
    local expired_count=0
    local expiring_count=0
    
    # Array temporaneo per dati
    declare -a pwd_data
    
    # DISABILITA set -e solo per questo loop
    set +e
    
    while IFS= read -r username; do
        [[ -z "$username" ]] && continue
        ((user_count++))
        
        # Progress ogni 10 utenti
        if (( user_count % 10 == 0 )); then
            log_info "  Progress: $user_count utenti elaborati..."
        fi
        
        # Ottieni pwdLastSet via samba-tool user show
        local pwd_last_set=$(runagent -m "$SAMBA_MODULE" podman exec samba-dc \
            samba-tool user show "$username" 2>/dev/null \
            | grep "^pwdLastSet:" | awk '{print $2}' || echo "0")
        
        if [[ -z "$pwd_last_set" ]] || [[ "$pwd_last_set" == "0" ]]; then
            pwd_data+=("$username|N/A|N/A|N/A")
            continue
        fi
        
        # Conversione FILETIME → Unix epoch
        local unix_time=$(python3 -c "print(int(($pwd_last_set - 116444736000000000) / 10000000))" 2>/dev/null || echo "0")
        
        if [[ "$unix_time" == "0" ]]; then
            pwd_data+=("$username|N/A|N/A|N/A")
            continue
        fi
        
        # Data ISO formattata
        local iso_date=$(date -d "@$unix_time" +"%Y-%m-%d" 2>/dev/null || echo "N/A")
        
        # Calcola scadenza
        local expires_unix=$((unix_time + MAX_PWD_AGE_DAYS * 86400))
        local expires_iso=$(date -d "@$expires_unix" +"%Y-%m-%d" 2>/dev/null || echo "N/A")
        
        # Giorni rimanenti
        local now=$(date +%s)
        local days_until_expiry=$(( (expires_unix - now) / 86400 ))
        
        # Contatori
        if [[ $days_until_expiry -lt 0 ]]; then
            ((expired_count++))
        elif [[ $days_until_expiry -le 7 ]]; then
            ((expiring_count++))
        fi
        
        pwd_data+=("$username|$iso_date|$expires_iso|$days_until_expiry")
        ((success_count++))
        
    done < "$user_list"
    
    # Riabilita set -e
    set -e
    
    # Scrivi riepilogo
    {
        echo "## 📊 Riepilogo"
        echo ""
        echo "- **Utenti totali:** $success_count"
        echo "- **Password scadute:** $expired_count"
        echo "- **Password in scadenza (≤7 giorni):** $expiring_count"
        echo ""
        echo "---"
        echo ""
    } >> "$output_md"
    
    # Scrivi ogni utente con formato heading uniforme
    for entry in "${pwd_data[@]}"; do
        IFS='|' read -r user lastset expires days <<< "$entry"
        
        # Determina stato e emoji
        local status_emoji=""
        local status_text=""
        
        if [[ "$days" == "N/A" ]]; then
            status_emoji="ℹ️"
            status_text="Informazioni non disponibili"
        elif [[ $days -lt 0 ]]; then
            status_emoji="⚠️"
            local abs_days=$((days * -1))
            status_text="Password scaduta da $abs_days giorni"
        elif [[ $days -le 7 ]]; then
            status_emoji="⏰"
            status_text="Password in scadenza tra $days giorni"
        else
            status_emoji="✅"
            status_text="Password valida (scade tra $days giorni)"
        fi
        
        # Scrivi heading per utente
        {
            echo "## 🔐 $user"
            echo ""
            echo "**Ultima Modifica:** $lastset  "
            echo "**Scade Il:** $expires  "
            echo "**Giorni rimanenti:** $days"
            echo ""
            echo "$status_emoji **$status_text**"
            echo ""
            echo "---"
            echo ""
        } >> "$output_md"
    done
    
    # Cleanup file utenti temporaneo
    rm -f "$user_list"
    
    log_success "Report password generato → 01_password_expiry.md ($success_count utenti)"
    return 0
}

# Funzione 3: Raccolta gruppi AD e membri
collect_ad_groups() {
    log_info "Generazione report gruppi AD (Markdown)..."
    
    local output_md="$OUTPUT_DIR/02_gruppi_ad.md"
    local temp_groups=$(mktemp)
    local temp_computers=$(mktemp)
    
    # Lista gruppi AD
    if ! runagent -m "$SAMBA_MODULE" podman exec samba-dc samba-tool group list > "$temp_groups" 2>/dev/null; then
        log_error "Fallita raccolta gruppi AD"
        echo "# ❌ Errore Raccolta Gruppi AD" > "$output_md"
        echo "" >> "$output_md"
        echo "Impossibile raccogliere gruppi dal domain controller." >> "$output_md"
        rm -f "$temp_groups" "$temp_computers"
        return 1
    fi
    
    local group_count=$(grep -c ^ "$temp_groups" 2>/dev/null || echo "0")
    
    # Funzione helper: check se gruppo va escluso
    is_excluded_group() {
        local group="$1"
        for excluded in "${EXCLUDE_GROUPS[@]}"; do
            if [[ "$group" == "$excluded" ]]; then
                return 0
            fi
        done
        return 1
    }
    
    # Inizia file MD
    {
        echo "# 👥 Gruppi Active Directory"
        echo ""
        echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
        echo ""
        echo "**Totale gruppi:** $group_count"
        echo ""
        echo "---"
        echo ""
    } > "$output_md"
    
    local processed=0
    local excluded_count=0
    local computer_count=0
    
    # DISABILITA set -e solo per questo loop
    set +e
    
    while IFS= read -r groupname; do
        [[ -z "$groupname" ]] && continue
        
        # Salta gruppi di sistema esclusi
        if is_excluded_group "$groupname"; then
            ((excluded_count++))
            continue
        fi
        
        ((processed++))
        
        # Progress solo ogni 10 gruppi (riduce output da 87 a ~9 righe)
        if (( processed % 10 == 0 )); then
            log_info "  Progress: $processed/$group_count gruppi..."
        fi
        
        # Ottieni membri del gruppo
        local members=$(runagent -m "$SAMBA_MODULE" podman exec samba-dc \
            samba-tool group listmembers "$groupname" 2>/dev/null | sort || echo "")
        
        local members_count=0
        local regular_members=""
        local computers=""
        
        if [[ -n "$members" ]]; then
            # Separa computer (finiscono con $) da utenti normali
            while IFS= read -r member; do
                [[ -z "$member" ]] && continue
                if [[ "$member" == *$ ]]; then
                    computers+="$member
"
                    echo "$groupname|$member" >> "$temp_computers"
                    ((computer_count++))
                else
                    regular_members+="$member
"
                    ((members_count++))
                fi
            done <<< "$members"
        fi
        
        # Scrivi solo se ci sono membri normali (non solo computer)
        if [[ $members_count -gt 0 ]]; then
            # Scrivi sezione gruppo
            {
                echo "## 📁 $groupname"
                echo ""
                echo "**Membri:** $members_count"
                echo ""
            } >> "$output_md"
            
            # Usa <details> per collapsibile solo se membri > 5
            if [[ $members_count -gt 5 ]]; then
                echo "<details>" >> "$output_md"
                echo "<summary>Elenco membri ($members_count)</summary>" >> "$output_md"
                echo "" >> "$output_md"
            fi
            
            while IFS= read -r member; do
                [[ -z "$member" ]] && continue
                echo "- $member" >> "$output_md"
            done <<< "$regular_members"
            
            if [[ $members_count -gt 5 ]]; then
                echo "" >> "$output_md"
                echo "</details>" >> "$output_md"
            fi
            
            echo "" >> "$output_md"
        fi
        
    done < "$temp_groups"
    
    # Riabilita set -e
    set -e
    
    # Aggiungi sezione Domain Computer
    if [[ -s "$temp_computers" ]]; then
        {
            echo "---"
            echo ""
            echo "# 💻 Domain Computer"
            echo ""
            echo "**Totale computer:** $computer_count"
            echo ""
            echo "---"
            echo ""
        } >> "$output_md"
        
        # Raggruppa per gruppo
        local current_group=""
        while IFS='|' read -r group_name computer_name; do
            if [[ "$group_name" != "$current_group" ]]; then
                if [[ -n "$current_group" ]]; then
                    echo "" >> "$output_md"
                fi
                echo "## 📁 $group_name" >> "$output_md"
                echo "" >> "$output_md"
                current_group="$group_name"
            fi
            echo "- $computer_name" >> "$output_md"
        done < <(sort "$temp_computers")
        echo "" >> "$output_md"
    fi
    
    log_success "Report gruppi generato → 02_gruppi_ad.md ($processed gruppi, $excluded_count esclusi, $computer_count computer)"
    rm -f "$temp_groups" "$temp_computers"
    return 0
}

# Funzione 4: Raccolta share e permessi
collect_samba_shares() {
    log_info "Generazione report share Samba (Markdown)..."
    
    local output_md="$OUTPUT_DIR/04_share_permissions.md"
    local temp_shares=$(mktemp)
    
    # Lista share (escludi share di sistema)
    runagent -m "$SAMBA_MODULE" podman exec samba-dc \
        smbclient -L localhost -N 2>/dev/null \
        | grep "Disk" \
        | awk '{print $1}' \
        | grep -vE '^(IPC\$|ADMIN\$|print\$|netlogon|sysvol)$' \
        > "$temp_shares" || true
    
    local share_count=$(wc -l < "$temp_shares" 2>/dev/null || echo 0)
    
    if [[ $share_count -eq 0 ]]; then
        log_warn "Nessuno share trovato"
        {
            echo "# 📂 Share Samba - Permessi"
            echo ""
            echo "⚠️ **Nessuno share trovato**"
        } > "$output_md"
        rm -f "$temp_shares"
        return 0
    fi
    
    log_info "Trovati $share_count share"
    
    # Inizia file MD
    {
        echo "# 📂 Share Samba - Permessi"
        echo ""
        echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
        echo ""
        echo "**Totale share:** $share_count"
        echo ""
        echo "---"
        echo ""
    } > "$output_md"
    
    # Contatori
    local processed=0
    local acl_success=0
    local acl_failed=0
    
    # DISABILITA set -e per il loop (sid_to_name può ritornare 1)
    set +e
    
    # Per ogni share: ottieni path, ACL, parsa e scrivi MD
    while IFS= read -r share_name; do
        [[ -z "$share_name" ]] && continue
        ((processed++))
        
        # Progress ogni 5 share
        if (( processed % 5 == 0 )); then
            log_info "  Progress: $processed/$share_count share..."
        fi
        
        # Ottieni path share
        local share_path=$(runagent -m "$SAMBA_MODULE" podman exec samba-dc \
            net conf getparm "$share_name" path 2>/dev/null </dev/null || echo "N/A")
        
        # Scrivi header share
        {
            echo "## 📁 $share_name"
            echo ""
            echo "**Path:** $share_path"
            echo ""
        } >> "$output_md"
        
        if [[ "$share_path" == "N/A" ]]; then
            echo "**Permessi:** ND" >> "$output_md"
            echo "" >> "$output_md"
            ((acl_failed++))
            continue
        fi
        
        # Ottieni ACL Windows
        local temp_acl=$(mktemp)
        if ! runagent -m "$SAMBA_MODULE" podman exec samba-dc \
            samba-tool ntacl get "$share_path" > "$temp_acl" 2>&1 </dev/null; then
            echo "**Permessi:** ND" >> "$output_md"
            echo "" >> "$output_md"
            rm -f "$temp_acl"
            ((acl_failed++))
            continue
        fi
        
        # Verifica ACL valido
        if ! grep -q "trustee" "$temp_acl" 2>/dev/null; then
            echo "**Permessi:** ND" >> "$output_md"
            echo "" >> "$output_md"
            rm -f "$temp_acl"
            ((acl_failed++))
            continue
        fi
        
        ((acl_success++))
        
        # Parsa ACL e raggruppa per tipo permesso
        local users_rw=()
        local users_ro=()
        
        local current_mask=""
        local current_sid=""
        
        while IFS= read -r line; do
            # Rileva access_mask
            if [[ "$line" =~ access_mask.*:[[:space:]]*(0x[0-9a-f]+) ]]; then
                current_mask="${BASH_REMATCH[1]}"
            fi
            
            # Rileva trustee SID
            if [[ "$line" =~ trustee.*:[[:space:]]*(S-1-[0-9-]+) ]]; then
                current_sid="${BASH_REMATCH[1]}"
                
                # Quando abbiamo entrambi, processa
                if [[ -n "$current_mask" && -n "$current_sid" ]]; then
                    # Converti SID → nome (skip SID di sistema)
                    local entity_name=$(sid_to_name "$current_sid" "$SAMBA_MODULE")
                    
                    if [[ -n "$entity_name" ]]; then
                        # Decodifica permessi
                        local perm_type=$(decode_access_mask "$current_mask")
                        
                        if [[ "$perm_type" == "RW" ]]; then
                            users_rw+=("$entity_name")
                        else
                            users_ro+=("$entity_name")
                        fi
                    fi
                    
                    # Reset
                    current_mask=""
                    current_sid=""
                fi
            fi
        done < "$temp_acl"
        
        rm -f "$temp_acl"
        
        # Scrivi tabella permessi
        echo "### Permessi" >> "$output_md"
        echo "" >> "$output_md"
        
        local has_perms=0
        
        if [[ ${#users_rw[@]} -gt 0 ]]; then
            echo "**Lettura/Scrittura:**" >> "$output_md"
            echo "" >> "$output_md"
            for user in "${users_rw[@]}"; do
                echo "- $user" >> "$output_md"
            done
            echo "" >> "$output_md"
            has_perms=1
        fi
        
        if [[ ${#users_ro[@]} -gt 0 ]]; then
            echo "**Solo Lettura:**" >> "$output_md"
            echo "" >> "$output_md"
            for user in "${users_ro[@]}"; do
                echo "- $user" >> "$output_md"
            done
            echo "" >> "$output_md"
            has_perms=1
        fi
        
        if [[ $has_perms -eq 0 ]]; then
            echo "*Nessun permesso esplicito configurato*" >> "$output_md"
            echo "" >> "$output_md"
        fi
        
        echo "---" >> "$output_md"
        echo "" >> "$output_md"
        
    done < "$temp_shares"
    
    # Riabilita set -e
    set -e
    
    rm -f "$temp_shares"
    
    log_success "Report share generato → 04_share_permissions.md ($processed share, $acl_success ACL, $acl_failed errori)"
    return 0
}

# Funzione 4: Raccolta condivisioni email WebTop
collect_webtop_sharing() {
    if [[ -z "$WEBTOP_MODULE" ]]; then
        log_warn "Modulo WebTop non disponibile - skip raccolta email sharing"
        local output_md="$OUTPUT_DIR/03_webtop_shares.md"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "⚠️ **Modulo WebTop non disponibile**"
        } > "$output_md"
        return 0
    fi
    
    log_info "Generazione report condivisioni email WebTop (Markdown)..."
    
    local output_md="$OUTPUT_DIR/03_webtop_shares.md"
    
    # Container Postgres
    local postgres_container=$(runagent -m "$WEBTOP_MODULE" podman ps --format '{{.Names}}' 2>/dev/null | grep -i postgres | head -1)
    
    if [[ -z "$postgres_container" ]]; then
        log_warn "Container Postgres non trovato"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "❌ **Errore:** Container Postgres non trovato"
        } > "$output_md"
        return 1
    fi
    
    # Rileva database WebTop
    local db_list=$(mktemp)
    if ! runagent -m "$WEBTOP_MODULE" podman exec "$postgres_container" \
        psql -U postgres -t -c '\l' > "$db_list" 2>/dev/null; then
        log_warn "Impossibile listare database"
        rm -f "$db_list"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "❌ **Errore:** Impossibile listare database"
        } > "$output_md"
        return 1
    fi
    
    local webtop_db=$(grep -iE 'webtop' "$db_list" | awk '{print $1}' | head -1 || true)
    rm -f "$db_list"
    
    if [[ -z "$webtop_db" ]]; then
        log_warn "Database WebTop non trovato"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "❌ **Errore:** Database WebTop non trovato"
        } > "$output_md"
        return 1
    fi
    
    # Query per ottenere mapping UUID → username
    local mapping_query="SELECT user_uid, user_id FROM core.users;"
    local temp_mapping="/tmp/webtop_mapping_$$.txt"
    local mapping_file="/tmp/webtop_uuid_map_$$.txt"
    
    # Funzione helper per risolvere UUID → username
    resolve_uuid() {
        local uuid="$1"
        # Normalizza UUID (rimuovi spazi)
        uuid=$(echo "$uuid" | xargs)
        local username=$(grep -i "^$uuid|" "$mapping_file" 2>/dev/null | cut -d'|' -f2 | xargs)
        if [[ -n "$username" && "$username" != "$uuid" ]]; then
            echo "$username"
        else
            # Fallback: cerca in modo case-insensitive con awk
            username=$(awk -F'|' -v uuid="$uuid" 'tolower($1) == tolower(uuid) {print $2; exit}' "$mapping_file" 2>/dev/null | xargs)
            if [[ -n "$username" ]]; then
                echo "$username"
            else
                echo "$uuid"
            fi
        fi
    }
    
    # Esegui query mapping e processa risultati
    if echo "$mapping_query" | runagent -m "$WEBTOP_MODULE" podman exec -i "$postgres_container" \
        psql -U postgres -d "$webtop_db" -t > "$temp_mapping" 2>/dev/null; then
        
        # Crea file mapping pulito: UUID|username
        grep -E "^\s*[a-f0-9]{8}-" "$temp_mapping" 2>/dev/null | \
            sed 's/|/\t/g' | \
            awk -F'\t' '{
                uuid = $1
                username = $2
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", uuid)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", username)
                if (uuid != "" && username != "") {
                    print uuid "|" username
                }
            }' > "$mapping_file"
        
        local map_count=$(wc -l < "$mapping_file" 2>/dev/null || echo 0)
        log_info "Caricati $map_count mapping UUID → username"
    else
        log_warn "Impossibile caricare mapping UUID, saranno mostrati UUID raw"
        touch "$mapping_file"  # Crea file vuoto per evitare errori
    fi
    
    rm -f "$temp_mapping"
    
    # Query SQL shares
    local query="SELECT s.share_id, s.user_uid AS owner, s.service_id, s.key AS mailbox_path, s.instance, sd.user_uid AS shared_with, sd.value AS permissions FROM core.shares s LEFT JOIN core.shares_data sd ON s.share_id = sd.share_id WHERE s.service_id LIKE '%mail%' ORDER BY s.user_uid, s.share_id, sd.user_uid;"
    
    local temp_output="/tmp/webtop_raw_$$.txt"
    
    # Esegui query
    if ! echo "$query" | runagent -m "$WEBTOP_MODULE" podman exec -i "$postgres_container" \
        psql -U postgres -d "$webtop_db" > "$temp_output" 2>/dev/null; then
        log_error "Query Postgres fallita"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "❌ **Errore:** Query Postgres fallita"
        } > "$output_md"
        rm -f "$temp_output"
        return 1
    fi
    
    # Controlla se ci sono dati
    if ! grep -qE "^\s*[0-9]+" "$temp_output" 2>/dev/null; then
        log_warn "Nessuna condivisione email configurata"
        {
            echo "# 📧 Condivisioni Email WebTop"
            echo ""
            echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
            echo ""
            echo "*Nessuna condivisione email configurata*"
        } > "$output_md"
        rm -f "$temp_output"
        return 0
    fi
    
    # Inizia file MD
    {
        echo "# 📧 Condivisioni Email WebTop"
        echo ""
        echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
        echo ""
        echo "---"
        echo ""
    } > "$output_md"
    
    # Processa righe output PostgreSQL e scrivi MD con formato heading
    local record_count=0
    
    set +e  # Disabilita set -e per processing loop (grep/awk possono tornare 1 se no match)
    
    grep -E "^\s*[0-9]+" "$temp_output" | \
        sed 's/|/\t/g' | \
        sed 's/^\s\+//;s/\s\+$//' | \
        awk -F'\t' '{
            # Trim ogni campo
            for(i=1; i<=NF; i++) {
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
            }
            # Stampa solo se ha abbastanza campi (share_id, owner, service_id, mailbox, instance, shared_with, perms)
            if (NF >= 6) {
                share_id = $1
                owner = $2
                mailbox = $4
                shared_with = $6
                perms = ($7 != "") ? $7 : "N/A"
                print share_id "\t" owner "\t" mailbox "\t" shared_with "\t" perms
            }
        }' | while IFS=$'\t' read -r share_id owner mailbox shared_with perms; do
        
        [[ -z "$share_id" ]] && continue
        record_count=$((record_count + 1))  # Safe increment
        
        # Risolvi UUID → username
        owner_user=$(resolve_uuid "$owner")
        shared_user=$(resolve_uuid "$shared_with")
        
        # Parse permessi JSON per formato leggibile
        local perm_readable=""
        if echo "$perms" | grep -q '"shareIdentity"\s*:\s*true'; then
            perm_readable="Lettura/Scrittura"
        else
            perm_readable="Sola lettura"
        fi
        
        # Scrivi heading per condivisione (formato uniforme con Samba)
        {
            echo "## 📧 Condivisione #$share_id - $owner_user → $shared_user"
            echo ""
            echo "**Proprietario:** $owner_user  "
            echo "**Mailbox:** $mailbox  "
            echo "**Condiviso Con:** $shared_user  "
            echo "**Permessi:** $perm_readable"
            echo ""
            echo "---"
            echo ""
        } >> "$output_md"
    done
    
    set -e  # Ri-abilita set -e
    
    rm -f "$temp_output" "$mapping_file"
    
    log_success "Report condivisioni WebTop generato → 03_webtop_shares.md ($record_count condivisioni)"
    return 0
}

# Funzione 5: Genera report riepilogativo
generate_summary_report() {
    log_info "Generazione report riepilogativo (Markdown)..."
    
    local output_md="$OUTPUT_DIR/00_REPORT_SUMMARY.md"
    
    # DISABILITA set -e (grep -c può ritornare 1 se no match)
    set +e
    
    # Conta dati dai file MD (usa arithmetic expansion per garantire numero valido)
    # User count: conta heading "## 🔐"
    user_count=$(( $(grep -c "^## 🔐" "$OUTPUT_DIR/01_password_expiry.md" 2>/dev/null) + 0 ))
    
    # Group count: conta heading "## 📁"
    group_count=$(( $(grep -c "^## 📁" "$OUTPUT_DIR/02_gruppi_ad.md" 2>/dev/null) + 0 ))
    
    # Share count: conta heading "## 📁"
    share_count=$(( $(grep -c "^## 📁" "$OUTPUT_DIR/04_share_permissions.md" 2>/dev/null) + 0 ))
    
    # WebTop count: conta heading "## 📧"
    webtop_count=$(( $(grep -c "^## 📧" "$OUTPUT_DIR/03_webtop_shares.md" 2>/dev/null) + 0 ))
    
    # Conta password critiche: cerca emoji ⚠️ per password scadute
    expired_count=$(( $(grep -c "⚠️ \*\*Password scaduta" "$OUTPUT_DIR/01_password_expiry.md" 2>/dev/null) + 0 ))
    
    # Conta password in scadenza: cerca emoji ⏰
    expiring_count=$(( $(grep -c "⏰ \*\*Password in scadenza" "$OUTPUT_DIR/01_password_expiry.md" 2>/dev/null) + 0 ))
    
    # Inizia file MD
    {
        echo "# 📊 Report Riepilogativo Audit NS8"
        echo ""
        echo "Report generato: $(date '+%d/%m/%Y %H:%M:%S')"
        echo ""
        echo "---"
        echo ""
        echo "## 📋 Statistiche Generali"
        echo ""
        echo "| Categoria | Totale |"
        echo "|-----------|--------|"
        echo "| **Utenti AD** | $user_count |"
        echo "| **Gruppi AD** | $group_count |"
        echo "| **Share Samba** | $share_count |"
        echo "| **Condivisioni Email WebTop** | $webtop_count |"
        echo ""
        echo "---"
        echo ""
        echo "## ⚠️ Criticità"
        echo ""
    } > "$output_md"
    
    # Sezione password critiche
    if [[ $expired_count -gt 0 ]] || [[ $expiring_count -gt 0 ]]; then
        {
            echo "### 🔐 Password"
            echo ""
            [[ $expired_count -gt 0 ]] && echo "- ⚠️ **Password scadute:** $expired_count"
            [[ $expiring_count -gt 0 ]] && echo "- ⏰ **Password in scadenza (≤7 giorni):** $expiring_count"
            echo ""
        } >> "$output_md"
    else
        {
            echo "### ✅ Password"
            echo ""
            echo "*Nessuna criticità rilevata*"
            echo ""
        } >> "$output_md"
    fi
    
    # Sezione file generati
    {
        echo "---"
        echo ""
        echo "## 📁 File Generati"
        echo ""
    } >> "$output_md"
    
    # Lista file MD con dimensioni
    for md_file in "$OUTPUT_DIR"/*.md; do
        [[ -f "$md_file" ]] || continue
        local basename=$(basename "$md_file")
        local size=$(du -h "$md_file" | cut -f1)
        echo "- [$basename]($basename) ($size)" >> "$output_md"
    done
    
    echo "" >> "$output_md"
    
    # Riabilita set -e
    set -e
    
    log_success "Report riepilogativo generato → 00_REPORT_SUMMARY.md"
    return 0
}

# Funzione 6: Genera report consolidato TSV
generate_consolidated_tsv() {
    log_info "Generazione report consolidato TSV..."
    
    local consolidated_file="$OUTPUT_DIR/REPORT_CONSOLIDATED.txt"
    
    # Header TSV
    echo -e "username\tpassword_last_set\tpassword_expires\tdays_until_expiry\tmember_of_groups\tshare_access\temail_shares" > "$consolidated_file"
    
    # Leggi lista utenti
    if [[ ! -f "$OUTPUT_DIR/01_users.txt" ]]; then
        log_warn "Lista utenti non disponibile"
        return 1
    fi
    
    # Per ogni utente
    while IFS= read -r username; do
        [[ -z "$username" ]] && continue
        [[ "$username" == "Guest" ]] && continue  # Skip Guest
        
        # 1. Password expiry info
        local pwd_last_set="N/A"
        local pwd_expires="N/A"
        local days_expiry="N/A"
        
        if [[ -f "$OUTPUT_DIR/02_password_expiry.txt" ]]; then
            local pwd_line=$(grep -i "^${username}\t" "$OUTPUT_DIR/02_password_expiry.txt" 2>/dev/null || true)
            if [[ -n "$pwd_line" ]]; then
                pwd_last_set=$(echo "$pwd_line" | cut -f3)
                pwd_expires=$(echo "$pwd_line" | cut -f5)
                days_expiry=$(echo "$pwd_line" | cut -f7)
            fi
        fi
        
        # 2. Gruppi di appartenenza
        local user_groups=""
        if [[ -f "$OUTPUT_DIR/05_ad_groups.txt" ]]; then
            # Cerca utente nei membri di ogni gruppo
            while IFS=$'\t' read -r group_name members; do
                if echo "$members" | grep -qiE "(^|,)${username}(,|$)" 2>/dev/null; then
                    user_groups="${user_groups}${group_name}; "
                fi
            done < <(tail -n +2 "$OUTPUT_DIR/05_ad_groups.txt" 2>/dev/null || true)
            user_groups=$(echo "$user_groups" | sed 's/; $//')
            [[ -z "$user_groups" ]] && user_groups="N/A"
        else
            user_groups="N/A"
        fi
        
        # 3. Accesso share
        local share_access=""
        if [[ -d "$OUTPUT_DIR/03_shares/acls" ]]; then
            # Parse tutti i file ACL per trovare l'utente (samba-tool ntacl format)
            for acl_file in "$OUTPUT_DIR/03_shares/acls"/*.txt; do
                [[ ! -f "$acl_file" ]] && continue
                local share_name=$(basename "$acl_file" _acl.txt)
                
                # Cerca SID, poi converti e verifica se corrisponde all'utente
                local current_trustee=""
                while IFS= read -r line; do
                    if [[ "$line" =~ trustee.*:\ (S-1-[0-9-]+) ]]; then
                        current_trustee="${BASH_REMATCH[1]}"
                        
                        # Converti SID → nome
                        local entity_name=$(sid_to_name "$current_trustee" "$SAMBA_MODULE")
                        
                        # Verifica se corrisponde con username (formato: DOMAIN\username)
                        if [[ "$entity_name" =~ \\${username}$ ]] || [[ "$entity_name" == "$username" ]]; then
                            share_access="${share_access}${share_name}; "
                            break  # Trovato, vai alla prossima share
                        fi
                    fi
                done < "$acl_file"
            done
            share_access=$(echo "$share_access" | sed 's/; $//')
            [[ -z "$share_access" ]] && share_access="N/A"
        else
            share_access="N/A"
        fi
        
        # 4. Email shares
        local email_shares=""
        if [[ -f "$OUTPUT_DIR/04_webtop_email_shares.txt" ]]; then
            # Cerca utente come owner o shared_with
            while IFS=$'\t' read -r owner_id shared_id mailbox owner shared perms; do
                if [[ "$owner" == "$username" ]] || [[ "$shared" == "$username" ]]; then
                    email_shares="${email_shares}${mailbox} (${perms}); "
                fi
            done < <(tail -n +2 "$OUTPUT_DIR/04_webtop_email_shares.txt" 2>/dev/null || true)
            email_shares=$(echo "$email_shares" | sed 's/; $//')
            [[ -z "$email_shares" ]] && email_shares="N/A"
        else
            email_shares="N/A"
        fi
        
        # Scrivi riga consolidata
        echo -e "$username\t$pwd_last_set\t$pwd_expires\t$days_expiry\t$user_groups\t$share_access\t$email_shares" >> "$consolidated_file"
        
    done < "$OUTPUT_DIR/01_users.txt"
    
    log_success "Report consolidato generato → REPORT_CONSOLIDATED.txt"
}

# ============================================================================
# VISUALIZZAZIONE TABELLE DETTAGLIATE
# ============================================================================

display_detailed_tables() {
    echo ""
    echo "================================================================================"
    echo "  REPORT COMPLETO AUDIT NS8"
    echo "================================================================================"
    echo ""
    
    log_info "Visualizzazione report Markdown..."
    
    # Display file MD in ordine (summary primo, poi dettagli)
    local md_files=(
        "00_REPORT_SUMMARY.md"
        "01_password_expiry.md"
        "02_gruppi_ad.md"
        "03_webtop_shares.md"
        "04_share_permissions.md"
    )
    
    for md_file in "${md_files[@]}"; do
        local full_path="$OUTPUT_DIR/$md_file"
        
        if [[ -f "$full_path" ]]; then
            echo ""
            cat "$full_path"
            echo ""
            echo "================================================================================"
        else
            log_warn "File non trovato: $md_file"
        fi
    done
    
    echo ""
    log_success "Visualizzazione completata"
}

# ============================================================================
# VISUALIZZAZIONE ACL - Integrato da acl-viewer.sh
# ============================================================================

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

# Visualizzazione report ACL
display_acl_report() {
    if [[ "$SHOW_ACL_REPORT" -eq 0 ]]; then
        log_info "Visualizzazione ACL disabilitata (--no-display)"
        return 0
    fi
    
    log_info "Visualizzazione report ACL permessi share..."
    
    local acl_dir="$OUTPUT_DIR/03_shares/acls"
    
    if [[ ! -d "$acl_dir" ]]; then
        log_warn "Directory ACL non trovata: $acl_dir"
        return 1
    fi
    
    local share_files=$(find "$acl_dir" -name "*_acl.txt" -type f 2>/dev/null | wc -l || echo 0)
    
    if [[ $share_files -eq 0 ]]; then
        log_warn "Nessun file ACL trovato"
        return 1
    fi
    
    # Header tabella
    echo ""
    echo "==============================================================================="
    echo "  REPORT PERMESSI SHARE NS8"
    echo "==============================================================================="
    echo ""
    echo "Audit directory: $OUTPUT_DIR"
    echo ""
    
    # Header tabella
    printf "%-20s %-35s %-30s %-25s\n" "SHARE" "PERCORSO" "ENTITA" "PERMESSI"
    printf "%-20s %-35s %-30s %-25s\n" \
        "--------------------" \
        "-----------------------------------" \
        "------------------------------" \
        "-------------------------"
    
    # Conta share
    local share_count=0
    local shares_report="$OUTPUT_DIR/03_shares/shares_report.txt"
    
    # Itera su tutti i file ACL
    for acl_file in $(find "$acl_dir" -name "*_acl.txt" -type f | sort); do
        local share_name=$(basename "$acl_file" _acl.txt)
        share_count=$((share_count + 1))
        
        # Leggi path dalla shares_report.txt
        local share_path=""
        if [[ -f "$shares_report" ]]; then
            share_path=$(grep "^$share_name	" "$shares_report" | cut -f2 || echo "N/A")
        fi
        
        local has_acl=0
        local first_line=1
        
        # Parse ACL Windows (samba-tool ntacl output)
        # Estrai coppie trustee + access_mask
        if grep -q "trustee" "$acl_file" 2>/dev/null; then
            has_acl=1
            
            # Estrai tutti i blocchi ACE
            local ace_count=0
            local current_trustee=""
            local current_mask=""
            
            while IFS= read -r line; do
                # Rileva access_mask (VIENE PRIMA nel output)
                if [[ "$line" =~ access_mask.*:\ (0x[0-9a-f]+) ]]; then
                    current_mask="${BASH_REMATCH[1]}"
                fi
                
                # Rileva trustee SID (VIENE DOPO nel output)
                if [[ "$line" =~ trustee.*:\ (S-1-[0-9-]+) ]]; then
                    current_trustee="${BASH_REMATCH[1]}"
                    
                    # Quando abbiamo entrambi, processa questa ACE IMMEDIATAMENTE
                    if [[ -n "$current_mask" && -n "$current_trustee" ]]; then
                        # Converti SID → nome
                        local entity_name=$(sid_to_name "$current_trustee" "$SAMBA_MODULE")
                        
                        # Skip SID di sistema (S-1-5-18, S-1-5-32-544, etc.)
                        if [[ -z "$entity_name" ]]; then
                            current_trustee=""
                            current_mask=""
                            continue
                        fi
                        
                        # Decodifica permessi
                        local perm_type=$(decode_access_mask "$current_mask")
                        
                        # Mostra nella tabella
                        if [[ $first_line -eq 1 ]]; then
                            printf "%-20s %-35s %-30s %-25s\n" \
                                "$share_name" \
                                "${share_path:0:35}" \
                                "${entity_name:0:30}" \
                                "$perm_type"
                            first_line=0
                        else
                            printf "%-20s %-35s %-30s %-25s\n" \
                                "" \
                                "" \
                                "${entity_name:0:30}" \
                                "$perm_type"
                        fi
                        
                        ace_count=$((ace_count + 1))
                        
                        # Reset per prossima ACE
                        current_trustee=""
                        current_mask=""
                    fi
                fi
            done < "$acl_file"
        fi
        
        # Se nessun ACL trovato, mostra "[solo sistema]"
        if [[ $has_acl -eq 0 ]]; then
            printf "%-20s %-35s %-30s %-25s\n" \
                "$share_name" \
                "${share_path:0:35}" \
                "[solo sistema]" \
                "-"
        fi
    done
    
    # Footer
    echo ""
    echo "==============================================================================="
    echo "Totale share analizzate: $share_count"
    echo ""
    echo "NOTE:"
    echo "  - Per vedere i membri di un gruppo AD:"
    echo "    runagent -m $SAMBA_MODULE podman exec samba-dc samba-tool group listmembers NOME_GRUPPO"
    echo ""
    
    log_success "Report ACL visualizzato"
    return 0
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
    echo "================================================================================"
    echo "NS8 Audit Report - Unified Version v${VERSION}"
    echo "================================================================================"
    echo ""
    
    check_prerequisites
    echo ""
    
    # Fase 1: Raccolta dati
    collect_ad_users
    collect_password_expiry
    collect_ad_groups
    collect_samba_shares
    collect_webtop_sharing
    
    echo ""
    
    # Fase 2: Genera report riepilogativo
    generate_summary_report
    # generate_consolidated_tsv  # Rimosso: troppo carico, non necessario
    
    echo ""
    
    # Fase 3: Visualizza tabelle dettagliate
    display_detailed_tables
    
    # Fase 4: Visualizza report ACL (disabilitato - ora usiamo solo MD display)
    # display_acl_report
    
    echo ""
    log_success "Report completato!"
    log_info "Output salvato in: $OUTPUT_DIR"
    
    return 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --output-dir)
            OUTPUT_BASE="$2"
            shift 2
            ;;
        --no-display)
            SHOW_ACL_REPORT=0
            shift
            ;;
        --help)
            echo "Uso: $0 [opzioni]"
            echo ""
            echo "Opzioni:"
            echo "  --output-dir /path        Directory base output (default: /tmp)"
            echo "  --no-display              Disabilita visualizzazione report ACL"
            echo "  --help                    Mostra questo help"
            echo ""
            echo "Nota: Lo script raccoglie ACL direttamente dal filesystem usando getfacl"
            echo "      (accesso root, nessuna autenticazione richiesta)."
            exit 0
            ;;
        *)
            log_error "Opzione sconosciuta: $1"
            echo "Usa --help per vedere le opzioni disponibili"
            exit 1
            ;;
    esac
done

# Run
main "$@"

