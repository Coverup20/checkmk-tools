#!/bin/bash
# Interactive Launcher - Esegui script remoti dal repository GitHub
# Scansiona tutte le cartelle remote/ e presenta menu interattivo

set -euo pipefail

REPO_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAVORITES_FILE="$HOME/.launcher-favorites"
STATS_FILE="$HOME/.launcher-stats"

# Colori per output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Array per memorizzare script trovati
declare -a SCRIPTS
declare -a SCRIPT_PATHS
declare -a SCRIPT_DESCRIPTIONS
declare -A FAVORITES
declare -A STATS

# Inizializza arrays vuoti per evitare unbound variable
FAVORITES=()
STATS=()

# Carica preferiti
load_favorites() {
    if [[ -f "$FAVORITES_FILE" ]]; then
        while IFS= read -r fav; do
            FAVORITES["$fav"]=1
        done < "$FAVORITES_FILE"
    fi
}

# Salva preferiti
save_favorites() {
    > "$FAVORITES_FILE"
    for fav in "${!FAVORITES[@]}"; do
        echo "$fav" >> "$FAVORITES_FILE"
    done
}

# Carica statistiche
load_stats() {
    if [[ -f "$STATS_FILE" ]]; then
        while IFS='=' read -r script count; do
            STATS["$script"]="$count"
        done < "$STATS_FILE"
    fi
}

# Salva statistiche
save_stats() {
    > "$STATS_FILE"
    for script in "${!STATS[@]}"; do
        echo "$script=${STATS[$script]}" >> "$STATS_FILE"
    done
}

# Incrementa contatore utilizzo
increment_usage() {
    local script="$1"
    local count="${STATS[$script]:-0}"
    STATS["$script"]=$((count + 1))
    save_stats
}

# Descrizioni degli script (estratte dai commenti)
get_script_description() {
    local script_path="$1"
    local full_path="$SCRIPT_DIR/$script_path"
    
    if [[ -f "$full_path" ]]; then
        # Cerca commento di descrizione nelle prime 10 righe
        local desc=$(head -n 10 "$full_path" | grep -E "^# (Desc|Description|Purpose):" | sed 's/^# [^:]*: //')
        if [[ -n "$desc" ]]; then
    echo "$desc"
else             # Fallback: seconda riga (solitamente descrizione)
            desc=$(sed -n '2p' "$full_path" | sed 's/^# //')
            echo "${desc:-Nessuna descrizione disponibile}"
        fi
else         echo "Script non trovato localmente"
    fi
}

print_header() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  🚀 ${GREEN}Interactive Launcher - CheckMK Tools Repository${NC}  ${BLUE}║${NC}"
    echo -e "${BLUE}╠═══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BLUE}║${NC}  ${CYAN}⭐ Preferiti: ${#FAVORITES[@]}${NC}  ${MAGENTA}📊 Script eseguiti: $(get_total_runs)${NC}         ${BLUE}║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

get_total_runs() {
    local total=0
    for count in "${STATS[@]}"; do
        total=$((total + count))
    done
echo "$total"
}

# Scansiona repository locale per trovare tutti gli script remoti
scan_remote_scripts() {
    echo -e "${YELLOW}📂 Scansione script remoti in corso...${NC}\n"
    
    local index=1
    
    # Trova tutti gli script nelle directory remote/
    while IFS= read -r -d '' script; do
        # Ottieni path relativo
        local rel_path="${script#$SCRIPT_DIR/}"
        local category=$(echo "$rel_path" | cut -d'/' -f1)
        local script_name=$(basename "$script" .sh)
        
        # Rimuovi prefisso 'r' se presente
        local display_name="${script_name#r}"
        
        SCRIPTS[$index]="[$category] $display_name"
        SCRIPT_PATHS[$index]="$rel_path"
        SCRIPT_DESCRIPTIONS[$index]=$(get_script_description "$rel_path")
        
        ((index++))
    done < <(find "$SCRIPT_DIR" -type f -path "*/remote/r*.sh" -print0 | sort -z)
    
    echo -e "${GREEN}✓ Trovati ${#SCRIPTS[@]} script remoti${NC}\n"
}

# Ricerca script per nome o categoria
search_scripts() {
    local query="$1"
    local results=()
    
    for i in "${!SCRIPTS[@]}"; do
        if [[ "${SCRIPTS[$i],,}" == *"${query,,}"* ]] || [[ "${SCRIPT_DESCRIPTIONS[$i],,}" == *"${query,,}"* ]]; then
            results+=("$i")
        fi
    done
    
    if [ ${#results[@]} -eq 0 ]; then
    echo -e "${RED}✗ Nessun risultato trovato per: '$query'${NC}\n"
        return 1
    fi
echo -e "${GREEN}🔍 Risultati ricerca '$query':${NC}\n"
    for idx in "${results[@]}"; do
        local star=""
        [[ -n "${FAVORITES[$idx]:-}" ]] && star="${YELLOW}⭐${NC} "
        printf "  ${BLUE}%3d)${NC} ${star}%s\n" "$idx" "$(echo "${SCRIPTS[$idx]}" | sed 's/\[.*\] //')"
    done
echo ""
}

# Mostra dettagli script
show_script_details() {
    local idx="$1"
    
    if [ "$idx" -lt 1 ] || [ "$idx" -gt "${#SCRIPTS[@]}" ]; then
    echo -e "${RED}✗ Script non vali
do!${NC}\n"
        return 1
    fi
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  📋 ${GREEN}Dettagli Script${NC}                                    ${CYAN}║${NC}"
    echo -e "${CYAN}╠═══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  ${YELLOW}Nome:${NC} ${SCRIPTS[$idx]}"
    echo -e "${CYAN}║${NC}  ${YELLOW}Path:${NC} ${SCRIPT_PATHS[$idx]}"
    echo -e "${CYAN}║${NC}  ${YELLOW}Descrizione:${NC}"
    echo -e "${CYAN}║${NC}    ${SCRIPT_DESCRIPTIONS[$idx]}"
    echo -e "${CYAN}║${NC}  ${YELLOW}Utilizzi:${NC} ${STATS[$idx]:-0}"
    [[ -n "${FAVORITES[$idx]:-}" ]] && echo -e "${CYAN}║${NC}  ${YELLOW}Preferito:${NC} ⭐ Sì"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}\n"
}

# Mostra solo preferiti
show_favorites() {
    if [ ${#FAVORITES[@]} -eq 0 ]; then
    echo -e "${YELLOW}⭐ Nessun preferito salvato${NC}\n"
        return
    fi
echo -e "${YELLOW}⭐ Script preferiti:${NC}\n"
    for idx in "${!FAVORITES[@]}"; do
        printf "  ${BLUE}%3d)${NC} %s\n" "$idx" "$(echo "${SCRIPTS[$idx]}" | sed 's/\[.*\] //')"
    done
echo ""
}

# Toggle preferito
toggle_favorite() {
    local idx="$1"
    
    if [[ -n "${FAVORITES[$idx]:-}" ]]; then
        unset FAVORITES[$idx]
        echo -e "${GREEN}✓ Rimosso dai preferiti${NC}"
else         FAVORITES[$idx]=1
        echo -e "${GREEN}✓ Aggiunto ai preferiti ⭐${NC}"
    fi
    save_favorites
}

# Mostra statistiche
show_statistics() {
    echo -e "${MAGENTA}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║${NC}  📊 ${GREEN}Statistiche di Utilizzo${NC}                          ${MAGENTA}║${NC}"
    echo -e "${MAGENTA}╠═══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${MAGENTA}║${NC}  ${YELLOW}Totale esecuzioni:${NC} $(get_total_runs)"
    echo -e "${MAGENTA}║${NC}  ${YELLOW}Script più usati:${NC}"
    
    # Top 5 script più usati
    local -a top_scripts=()
    for idx in "${!STATS[@]}"; do
        top_scripts+=("${STATS[$idx]}:$idx")
    done
    
    if [ ${#top_scripts[@]} -gt 0 ]; then
    IFS=$'\n' sorted=($(sort -rn <<<"${top_scripts[*]}"))
        unset IFS
        
        local count=0
        for entry in "${sorted[@]}"; do
            [[ $count -ge 5 ]] && break
            local uses="${entry%%:*}"
            local idx="${entry##*:}"
            local name=$(echo "${SCRIPTS[$idx]}" | sed 's/\[.*\] //')
            echo -e "${MAGENTA}║${NC}    ${BLUE}$((count+1)).${NC} $name ${CYAN}($uses)${NC}"
            ((count++))
        done
else         echo -e "${MAGENTA}║${NC}    ${YELLOW}Nessuna statistica disponibile${NC}"
    fi
echo -e "${MAGENTA}╚═══════════════════════════════════════════════════════════╝${NC}\n"
}

# Mostra menu con tutti gli script disponibili
show_menu() {
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}Script disponibili:${NC}"
    echo -e "${CYAN}Comandi: ${YELLOW}s)${NC}Cerca ${YELLOW}f)${NC}Preferiti ${YELLOW}i)${NC}Info ${YELLOW}t)${NC}Stats ${YELLOW}*+)${NC}Aggiungi/Rimuovi ⭐${NC}\n"
    
    local current_category=""
    for i in "${!SCRIPTS[@]}"; do
        # Estrai categoria
        local category=$(echo "${SCRIPTS[$i]}" | grep -oP '\[\K[^\]]+')
        
        # Stampa intestazione categoria se cambia
        if [ "$category" != "$current_category" ]; then
    echo -e "\n${YELLOW}▶ $category${NC}"
            current_category="$category"
        fi
        
        # Stella se preferito
        local star=""
        [[ -n "${FAVORITES[$i]:-}" ]] && star="${YELLOW}⭐${NC} "
        
        # Numero di utilizzi
        local uses=""
        [[ -n "${STATS[$i]:-}" ]] && uses=" ${CYAN}(${STATS[$i]})${NC}"
        
        # Stampa script con numerazione
        printf "  ${BLUE}%3d)${NC} ${star}%s${uses}\n" "$i" "$(echo "${SCRIPTS[$i]}" | sed 's/\[.*\] //')"
    done
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "  ${RED}0)${NC} Esci  ${YELLOW}s)${NC}Cerca  ${YELLOW}f)${NC}Preferiti  ${YELLOW}i)${NC}Info  ${YELLOW}t)${NC}Stats"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}\n"
}

# Esegui script selezionato
execute_script() {
    local selection=$1
    
    if [ "$selection" -eq 0 ]; then
    echo -e "${GREEN}Arrivederci!${NC}"
    exit 0
    fi
    
    if [ "$selection" -lt 1 ] || [ "$selection" -gt "${#SCRIPTS[@]}" ]; then
    echo -e "${RED}✗ Selezione non valida!${NC}\n"
        return 1
    fi
    
    local script_path="${SCRIPT_PATHS[$selection]}"
    local script_name="${SCRIPTS[$selection]}"
    local remote_url="$REPO_URL/$script_path"
    
    # Incrementa statistiche
    increment_usage "$selection"
    
    echo -e "\n${GREEN}▶ Esecuzione:${NC} $script_name"
    echo -e "${BLUE}   URL:${NC} $remote_url\n"
    
    # Chiedi parametri aggiuntivi
    echo -e "${YELLOW}Parametri aggiuntivi (invio per nessuno):${NC}"
    read -r params
    
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    
    # Esegui script remoto usando un file temporaneo
    local TEMP_SCRIPT
    TEMP_SCRIPT=$(mktemp)
    curl -fsSL "$remote_url" -o "$TEMP_SCRIPT"
    
    if [ -n "$params" ]; then
        if [ "${EUID:-$(id -u)}" -eq 0 ]; then
            bash "$TEMP_SCRIPT" $params
        elif command -v sudo >/dev/null 2>&1; then
            sudo bash "$TEMP_SCRIPT" $params
        elif command -v su >/dev/null 2>&1; then
            su -c "bash '$TEMP_SCRIPT' $params"
        else
            bash "$TEMP_SCRIPT" $params
        fi
    else
        if [ "${EUID:-$(id -u)}" -eq 0 ]; then
            bash "$TEMP_SCRIPT"
        elif command -v sudo >/dev/null 2>&1; then
            sudo bash "$TEMP_SCRIPT"
        elif command -v su >/dev/null 2>&1; then
            su -c "bash '$TEMP_SCRIPT'"
        else
            bash "$TEMP_SCRIPT"
        fi
    fi
    
    rm -f "$TEMP_SCRIPT"
    
    local exit_code=$?
    
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if [ $exit_code -eq 0 ]; then
    echo -e "${GREEN}✓ Script completato con successo${NC}\n"
else         echo -e "${RED}✗ Script terminato con errore (exit code: $exit_code)${NC}\n"
    fi
    
    # Pausa prima di tornare al menu
    echo -e "${YELLOW}Premi INVIO per continuare...${NC}"
    read -r
}

# Main loop
main() {
    load_favorites
    load_stats
    print_header
    scan_remote_scripts
    
    while true; do
        clear
        print_header
        show_menu
        
        echo -e "${YELLOW}Seleziona uno script o coman
do:${NC} "
        read -r selection
        
        # Comandi speciali
        case "$selection" in
            0)
                echo -e "${GREEN}Arrivederci! 👋${NC}"
    exit 0
                ;;
            s|S)
                echo -e "${CYAN}🔍 Cerca script:${NC} "
                read -r query
                search_scripts "$query"
                echo -e "${YELLOW}Premi INVIO per continuare...${NC}"
                read -r
                ;;
            f|F)
                show_favorites
                echo -e "${YELLOW}Premi INVIO per continuare...${NC}"
                read -r
                ;;
            i|I)
                echo -e "${CYAN}📋 Numero script per info:${NC} "
                read -r idx
                if [[ "$idx" =~ ^[0-9]+$ ]]; then
                    show_script_details "$idx"
else                     echo -e "${RED}✗ Numero non vali
do${NC}"
                fi
echo -e "${YELLOW}Premi INVIO per continuare...${NC}"
                read -r
                ;;
            t|T)
                show_statistics
                echo -e "${YELLOW}Premi INVIO per continuare...${NC}"
                read -r
                ;;
            *+)
                local idx="${selection%+}"
                if [[ "$idx" =~ ^[0-9]+$ ]]; then
                    toggle_favorite "$idx"
                    sleep 1
                else
                    echo -e "${RED}✗ Formato: numero+ (es: 57+)${NC}"
                    sleep 2
                fi
                ;;
            *)
                # Verifica input numerico
                if [[ "$selection" =~ ^[0-9]+$ ]]; then
                    execute_script "$selection"
else                     echo -e "${RED}✗ Coman
do non riconosciuto!${NC}\n"
                    sleep 2
                fi
                ;;
        esac
    done
}

# Verifica prerequisiti
if ! command -v curl &> /dev/null; then
    echo -e "${RED}✗ Errore: curl non trovato. Installalo con: apt install curl${NC}"
    exit 1
fi

# Avvia launcher
main
