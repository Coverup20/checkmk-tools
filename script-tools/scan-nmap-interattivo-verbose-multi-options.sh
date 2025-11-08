#!/usr/bin/env bash
#
# scan-nmap-interattivo-verbose-multi-options.sh
# Interattivo Nmap: multi-target, forzato -oN unico, genera CSV riepilogo + TXT leggibile,
# e mantiene symlink "latest" per accesso rapido.
#
set -euo pipefail

DEFAULT_OUTDIR="./scans"
DEFAULT_PORTS="1-1024"
TIMESTAMP() { date +%Y%m%dT%H%M%S; }

NMAP_BIN="$(command -v nmap || true)"
if [[ -z "$NMAP_BIN" ]]; then
  echo "Errore: nmap non trovato nel PATH. Installa nmap e riprova." >&2
  exit 2
fi

echo "=== SCAN NMAP INTERATTIVO (output unico .txt + CSV riepilogo + TXT leggibile) ==="
echo

# TARGET MODE
while true; do
  read -rp "Vuoi scansionare (1) subnet/range/host (multipli separati da spazi o virgole) oppure (2) file targets? [1/2] (default 1): " MODE
  MODE="${MODE:-1}"
  if [[ "$MODE" == "1" || "$MODE" == "2" ]]; then break; fi
  echo "Risposta non valida. Inserisci 1 o 2."
done

TARGETS=()
TARGET_FILE=""
if [[ "$MODE" == "1" ]]; then
  read -rp "Inserisci subnet/host/range (es. 192.168.1.0/24 10.0.0.0/24). Puoi usare virgole o spazi: " RANGE_IN
  RANGE_IN="${RANGE_IN:-}"
  if [[ -z "$RANGE_IN" ]]; then
    echo "Errore: nessun target fornito. Uscita." >&2
    exit 3
  fi
  RANGE_IN="$(printf "%s" "$RANGE_IN" | tr ',' ' ' | xargs)"
  read -r -a TARGETS <<< "$RANGE_IN"
else
  read -rp "Inserisci percorso file targets (uno per riga, IP/host/CIDR): " TARGET_FILE
  TARGET_FILE="${TARGET_FILE:-}"
  if [[ -z "$TARGET_FILE" || ! -f "$TARGET_FILE" ]]; then
    echo "Errore: file targets non valido o non esistente: $TARGET_FILE" >&2
    exit 4
  fi
fi

# SCAN TYPE
while true; do
  echo
  echo "Tipo scansione:"
  echo "  1) Scan porte (default)     -- porta scan"
  echo "  2) Discovery only (no port scan) -- nmap -sn"
  read -rp "Scegli 1 o 2 [default 1]: " SCAN_CHOICE
  SCAN_CHOICE="${SCAN_CHOICE:-1}"
  if [[ "$SCAN_CHOICE" == "1" || "$SCAN_CHOICE" == "2" ]]; then break; fi
  echo "Risposta non valida."
done

PORTS="$DEFAULT_PORTS"
if [[ "$SCAN_CHOICE" == "1" ]]; then
  read -rp "Porte da scansionare (es. 22,2222,9090,980,443,80,3389,161,162 o 1-65535) [default: ${DEFAULT_PORTS}]: " INPUT_PORTS
  PORTS="${INPUT_PORTS:-$DEFAULT_PORTS}"
fi

# VERBOSITY
echo
echo "Livello verbositÃ  / debug:"
echo "  0) Nessuna verbositÃ  extra (default)"
echo "  1) Verbose (-v)"
echo "  2) Very verbose (-vv)"
echo "  3) Debug (-d) + --packet-trace"
read -rp "Scegli 0|1|2|3 [default 0]: " VLEVEL
VLEVEL="${VLEVEL:-0}"
if ! [[ "$VLEVEL" =~ ^[0-3]$ ]]; then VLEVEL=0; fi

# Extra nmap options (utente) - but strip -o* to force single OUTTXT file.
echo
read -rp "Opzioni nmap aggiuntive (es. -sC -sV -sU -p T:22,2222,U:161,162). NOTA: le opzioni -o* verranno ignorate (output forzato in un unico file): " NMAP_EXTRA
NMAP_EXTRA="${NMAP_EXTRA:-}"

# OUTDIR and timing
read -rp "Directory output [default: ${DEFAULT_OUTDIR}]: " OUTDIR
OUTDIR="${OUTDIR:-$DEFAULT_OUTDIR}"
read -rp "Timing template nmap 0..5 [default 3]: " NT
NT="${NT:-3}"
if ! [[ "$NT" =~ ^[0-5]$ ]]; then NT=3; fi

# Confirm
echo
echo "Riepilogo:"
if [[ "$MODE" == "1" ]]; then
  echo "  Targets: ${TARGETS[*]}"
else
  echo "  Targets file: $TARGET_FILE"
fi
if [[ "$SCAN_CHOICE" == "1" ]]; then
  echo "  ModalitÃ : Scan porte"
  echo "  Porte: $PORTS"
else
  echo "  ModalitÃ : Discovery only (no port scan) - -sn"
fi
case "$VLEVEL" in
  0) echo "  VerbositÃ : nessuna extra" ;;
  1) echo "  VerbositÃ : -v" ;;
  2) echo "  VerbositÃ : -vv" ;;
  3) echo "  VerbositÃ : -d + --packet-trace" ;;
esac
if [[ -n "$NMAP_EXTRA" ]]; then
  echo "  Opzioni extra (senza -o*): $NMAP_EXTRA"
fi
echo "  Output dir: $OUTDIR"
echo "  Timing template: -T$NT"
echo

read -rp "Procedere con la scansione? [y/N]: " CONF
CONF="${CONF:-N}"
if [[ ! "$CONF" =~ ^[Yy]$ ]]; then
  echo "Annullato dall'utente."
  exit 0
fi

mkdir -p "$OUTDIR"
if [[ ! -w "$OUTDIR" ]]; then
  echo "Errore: directory $OUTDIR non scrivibile." >&2
  exit 5
fi

TS="$(TIMESTAMP)"
SAFE_LABEL=""
if [[ "$MODE" == "1" ]]; then
  SAFE_LABEL="$(echo "${TARGETS[0]}" | tr -c '[:alnum:]_.' '_' )_x${#TARGETS[@]}"
else
  SAFE_LABEL="$(basename "$TARGET_FILE" | tr -c '[:alnum:]_.' '_' )"
fi

OUTBASE="${OUTDIR%/}/nmap-${TS}_${SAFE_LABEL}"
OUTTXT="${OUTBASE}.txt"
OUTCSV="${OUTBASE}_summary.csv"
OUTCSV_TXT="${OUTBASE}_summary_readable.txt"
OUTSUM="${OUTBASE}_summary.txt"

# Build nmap flags depending on choices
NMAP_OPTS=()

# verbositÃ 
if [[ "$VLEVEL" -eq 1 ]]; then
  NMAP_OPTS+=( -v )
elif [[ "$VLEVEL" -eq 2 ]]; then
  NMAP_OPTS+=( -vv )
elif [[ "$VLEVEL" -eq 3 ]]; then
  NMAP_OPTS+=( -d --packet-trace )
fi

NMAP_OPTS+=( --reason -T"${NT}" )

if [[ "$SCAN_CHOICE" == "2" ]]; then
  NMAP_OPTS+=( -sn )
else
  # prefer SYN if root, else connect
  if [[ "$(id -u)" -eq 0 ]]; then
    NMAP_OPTS+=( -sS -p "$PORTS" )
  else
    NMAP_OPTS+=( -sT -p "$PORTS" )
  fi
fi

# Process NMAP_EXTRA: split but strip any -o* output flags to force single OUTTXT file.
EXTRA_ARR=()
if [[ -n "$NMAP_EXTRA" ]]; then
  read -r -a TMP <<< "$NMAP_EXTRA"
  for tok in "${TMP[@]}"; do
    if [[ "$tok" =~ ^-o ]]; then
      # ignore -o* options
      continue
    fi
    EXTRA_ARR+=( "$tok" )
  done
fi

# Detect if user specified their own scan type (-sS -sT etc.) or -p so we can avoid duplicates
USER_SPEC_SCAN=0
USER_SPEC_P=0
for tok in "${EXTRA_ARR[@]}"; do
  if [[ "$tok" =~ ^-s ]]; then USER_SPEC_SCAN=1; fi
  if [[ "$tok" == "-p" || "$tok" =~ ^-p.+ ]]; then USER_SPEC_P=1; fi
done

# If user specified a scan type, remove our -sS/-sT to avoid duplicate types
if (( USER_SPEC_SCAN )); then
  tmp=()
  for x in "${NMAP_OPTS[@]}"; do
    if [[ "$x" == "-sS" || "$x" == "-sT" ]]; then
      continue
    fi
    tmp+=( "$x" )
  done
  NMAP_OPTS=( "${tmp[@]}" )
fi

# If user specified -p explicitly, remove our -p and its argument
if (( USER_SPEC_P )); then
  tmp=()
  skip=0
  for x in "${NMAP_OPTS[@]}"; do
    if (( skip )); then skip=0; continue; fi
    if [[ "$x" == "-p" ]]; then
      skip=1
      continue
    fi
    tmp+=( "$x" )
  done
  NMAP_OPTS=( "${tmp[@]}" )
fi

# Assemble final command array
NMAP_CMD=( "$NMAP_BIN" "${NMAP_OPTS[@]}" )
if [[ "$MODE" == "2" ]]; then
  NMAP_CMD+=( -iL "$TARGET_FILE" )
else
  for t in "${TARGETS[@]}"; do
    NMAP_CMD+=( "$t" )
  done
fi

# Append user extras (non -o*)
if (( ${#EXTRA_ARR[@]} )); then
  NMAP_CMD+=( "${EXTRA_ARR[@]}" )
fi

# Force single output file -oN OUTTXT (user cannot override)
NMAP_CMD+=( -oN "$OUTTXT" )

# Show command (escaped)
echo
printf 'Comando:'
for part in "${NMAP_CMD[@]}"; do
  printf ' %q' "$part"
done
echo
echo

# Run nmap
if "${NMAP_CMD[@]}"; then
  EC=0
else
  EC=$?
fi

# Produce CSV summary
printf '%s\n' "Hostname,IP,MAC,Vendor,Status,OpenPorts" > "$OUTCSV"

awk -v OUTCSV="$OUTCSV" '
  BEGIN {
    host=""; ip=""; mac=""; vendor=""; status=""; inports=0; openports="";
  }
  /^Nmap scan report for/ {
    if (host != "") {
      gsub(/"/, "\"\"", vendor); gsub(/"/, "\"\"", host)
      if (openports == "") op=""; else op=openports
      printf "\"%s\",%s,\"%s\",\"%s\",%s,\"%s\"\n", host, ip, mac, vendor, status, op >> OUTCSV
    }
    host=$0
    sub(/^Nmap scan report for /,"",host)
    ip="N/A"; mac=""; vendor=""; status=""; openports=""
    if (match(host, /\(([0-9.]+)\)/, a)) {
      ip=a[1]
      split(host, hparts, " \\(")
      host=hparts[1]
    } else {
      if (host ~ /^[0-9.]+$/) ip=host
    }
    next
  }
  /^[Hh]ost is up/ { status="up"; next }
  /received no-response|[Hh]ost down/ { status="down"; next }
  /^MAC Address:/ {
    mac=$3
    vendor=substr($0, index($0,$4))
    gsub(/^\(|\)$/, "", vendor)
    next
  }
  /^PORT[[:space:]]+STATE/ { inports=1; next }
  /^$/ { inports=0; next }
  inports==1 && /^[0-9]+\/(tcp|udp)/ {
    portproto=$1
    state=$2
    service=$3
    vers=""
    for (i=4;i<=NF;i++) vers = vers (i==4 ? $i : " " $i)
    if (state ~ /^open/) {
      if (vers != "") frag = portproto "(" service " " vers ")"
      else frag = portproto "(" service ")"
      if (openports == "") openports = frag
      else openports = openports ";" frag
    }
    next
  }
  END {
    if (host != "") {
      gsub(/"/, "\"\"", vendor); gsub(/"/, "\"\"", host)
      if (openports == "") op=""; else op=openports
      printf "\"%s\",%s,\"%s\",\"%s\",%s,\"%s\"\n", host, ip, mac, vendor, status, op >> OUTCSV
    }
  }
' "$OUTTXT" || true

# Produce human-readable TXT from CSV (columns aligned)
# We'll create OUTCSV_TXT with columns: Hostname | IP | Status | OpenPorts (Vendor and MAC optional)
{
  # header
  printf "%-40s %-15s %-8s %s\n" "Hostname" "IP" "Status" "OpenPorts"
  printf "%-40s %-15s %-8s %s\n" "--------" "----" "------" "---------"
  # read CSV and print aligned
  awk -F',' 'NR>1 {
    # remove surrounding quotes from $1 and $4 and $6
    gsub(/^"|"$/, "", $1); gsub(/^"|"$/, "", $4); gsub(/^"|"$/, "", $6)
    host=$1; ip=$2; status=$5; ports=$6
    # shorten ports if too long
    if (length(ports) > 120) {
      ports = substr(ports,1,117) "..."
    }
    printf "%-40s %-15s %-8s %s\n", host, ip, status, ports
  }' "$OUTCSV"
} > "$OUTCSV_TXT" || true

# Produce short human summary (OUTSUM)
if [[ "$SCAN_CHOICE" == "2" ]]; then
  grep -E "Nmap scan report for|Host is up|MAC Address" "$OUTTXT" > "$OUTSUM" || true
else
  awk -F',' 'NR>1 { gsub(/^"|"$/,"",$1); print $1 " | " $2 " | " $5 " | " $6 }' "$OUTCSV" > "$OUTSUM" || true
fi

# Create symlinks to latest
ln -sf "$(basename "$OUTTXT")" "${OUTDIR%/}/nmap_latest.txt"
ln -sf "$(basename "$OUTCSV")" "${OUTDIR%/}/nmap_summary_latest.csv"
ln -sf "$(basename "$OUTCSV_TXT")" "${OUTDIR%/}/nmap_summary_latest.txt"

echo
echo "Fine scansione (exit code: $EC)"
echo "Output completo nmap: $OUTTXT"
echo "CSV riepilogo unico: $OUTCSV"
echo "TXT leggibile dal CSV: $OUTCSV_TXT"
echo "Summary breve: $OUTSUM"
echo "Link veloci in $OUTDIR: nmap_latest.txt, nmap_summary_latest.csv, nmap_summary_latest.txt"
exit $EC

