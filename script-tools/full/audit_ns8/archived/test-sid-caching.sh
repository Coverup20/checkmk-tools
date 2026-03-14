#!/bin/bash
#
# Test minimale pre-caching SID per identificare punto di blocco
#

set -e

# Dichiarazione globale cache SID
declare -A SID_CACHE

echo "=========================================="
echo "TEST PRE-CACHING SID - DEBUG"
echo "=========================================="
echo ""

# Trova modulo Samba
SAMBA_MODULE=$(runagent --list-modules 2>/dev/null | grep -E '^samba[0-9]+$' | head -1)

if [[ -z "$SAMBA_MODULE" ]]; then
    echo "[ERROR] Nessun modulo Samba trovato"
    exit 1
fi

echo "[OK] Modulo Samba: $SAMBA_MODULE"
echo ""

# Directory ACL (usa l'ultima esecuzione)
ACL_DIR=$(ls -td /tmp/ns8-audit-* 2>/dev/null | head -1)

if [[ -z "$ACL_DIR" ]] || [[ ! -d "$ACL_DIR/03_shares/acls" ]]; then
    echo "[ERROR] Directory ACL non trovata"
    echo "Esegui prima ns8-audit-report-unified.sh per raccogliere ACL"
    exit 1
fi

ACL_DIR="$ACL_DIR/03_shares/acls"
echo "[OK] ACL directory: $ACL_DIR"
echo ""

# Estrai SID unici
echo "[INFO] Estrazione SID unici dai file ACL..."
ALL_SIDS=$(grep -h "trustee.*: S-1" "$ACL_DIR"/*_acl.txt 2>/dev/null | sed 's/.*trustee.*: \(S-1-[0-9-]*\).*/\1/' | sort -u)
SID_COUNT=$(echo "$ALL_SIDS" | grep -c "^S-1" || echo 0)

echo "[OK] Trovati $SID_COUNT SID unici"
echo ""

if [[ $SID_COUNT -eq 0 ]]; then
    echo "[ERROR] Nessun SID trovato nei file ACL"
    exit 1
fi

# DEBUG: Mostra primi 3 SID
echo "[DEBUG] Primi 3 SID estratti:"
echo "$ALL_SIDS" | head -3
echo ""

# Test conversione SID uno alla volta
echo "=========================================="
echo "TEST CONVERSIONE SID (uno alla volta)"
echo "=========================================="
echo ""

CURRENT=0

echo "[DEBUG] Starting loop with ALL_SIDS length: ${#ALL_SIDS}"
echo ""

while IFS= read -r sid; do
    echo "[DEBUG] Loop iteration - raw sid: '$sid'"
    if [[ -z "$sid" ]]; then
        continue
    fi
    CURRENT=$((CURRENT + 1))
    echo "[DEBUG] After increment, CURRENT=$CURRENT"
    
    echo "[$CURRENT/$SID_COUNT] Testing SID: $sid"
    
    # Skip SID di sistema
    case "$sid" in
        S-1-5-18|S-1-5-32-544|S-1-5-2|S-1-1-0) 
            echo "  → SKIP (system SID)"
            SID_CACHE["$sid"]=""
            continue
            ;;
    esac
    
    # Test wbinfo con timeout progressivo
    echo "  → Calling wbinfo (timeout 5s)..."
    START=$(date +%s)
    
    # Prova con timeout 5s
    if NAME=$(timeout 5 runagent -m "$SAMBA_MODULE" podman exec samba-dc wbinfo --sid-to-name "$sid" 2>&1 </dev/null); then
        ELAPSED=$(($(date +%s) - START))
        echo "  → SUCCESS: $NAME (${ELAPSED}s)"
        SID_CACHE["$sid"]="$NAME"
    else
        EXIT_CODE=$?
        ELAPSED=$(($(date +%s) - START))
        echo "  → FAILED: Exit code $EXIT_CODE after ${ELAPSED}s"
        echo "  → Output: $NAME"
        
        # Se timeout (exit 124), prova con 10s
        if [[ $EXIT_CODE -eq 124 ]]; then
            echo "  → Retry with 10s timeout..."
            START=$(date +%s)
            if NAME=$(timeout 10 runagent -m "$SAMBA_MODULE" podman exec samba-dc wbinfo --sid-to-name "$sid" 2>&1 </dev/null); then
                ELAPSED=$(($(date +%s) - START))
                echo "  → SUCCESS (retry): $NAME (${ELAPSED}s)"
                SID_CACHE["$sid"]="$NAME"
            else
                ELAPSED=$(($(date +%s) - START))
                echo "  → FAILED (retry): Exit code $? after ${ELAPSED}s"
                SID_CACHE["$sid"]="UNKNOWN"
            fi
        else
            SID_CACHE["$sid"]="UNKNOWN"
        fi
    fi
    
    echo ""
    
    # Mostra statistiche ogni 5 SID
    if (( CURRENT % 5 == 0 )); then
        echo "--- Progress: $CURRENT/$SID_COUNT SID processati ---"
        echo ""
    fi
    
done <<< "$ALL_SIDS"

# Riepilogo finale
echo "=========================================="
echo "RIEPILOGO TEST"
echo "=========================================="
echo ""
echo "SID totali:        $SID_COUNT"
set +u
cache_size=${#SID_CACHE[@]}
set -u
echo "Cache popolata:    ${cache_size} entries"
echo ""
echo "Contenuto cache:"
for sid in "${!SID_CACHE[@]}"; do
    echo "  $sid → ${SID_CACHE[$sid]}"
done
echo ""
echo "[OK] Test completato!"
