#!/usr/bin/env bash
set -euo pipefail

# scan-nmap-interattivo-verbose-multi-options.sh
# Interattivo multi-target: output unico -oN, CSV riepilogo + TXT leggibile, symlink "latest".
# Output default: ./scans

DEFAULT_OUTDIR="./scans"
DEFAULT_PORTS="1-1024"

timestamp() { date +%Y%m%dT%H%M%S; }

die() {
    echo "[ERR] $*" >&2
    exit 1
}

sanitize_label() {
    printf '%s' "$1" | tr -c '[:alnum:]._-' '_'
}

NMAP_BIN="$(command -v nmap || true)"
[[ -n "$NMAP_BIN" ]] || die "nmap non trovato nel PATH"

echo "SCAN NMAP INTERATTIVO (MULTI-TARGET)"

mode="1"
while true; do
    read -r -p "Target: (1) lista host/range/cidr oppure (2) file targets? [1/2] (default 1): " mode
    mode="${mode:-1}"
    [[ "$mode" == "1" || "$mode" == "2" ]] && break
    echo "Valore non valido"
done

targets=()
target_file=""
if [[ "$mode" == "1" ]]; then
    read -r -p "Inserisci targets separati da spazio o virgola (es. 192.168.1.0/24,10.0.0.1): " targets_in
    targets_in="${targets_in:-}"
    [[ -n "$targets_in" ]] || die "nessun target fornito"
    targets_in="$(printf '%s' "$targets_in" | tr ',' ' ' | xargs)"
    read -r -a targets <<< "$targets_in"
    ((${#targets[@]} > 0)) || die "nessun target valido"
else
    read -r -p "Percorso file targets (uno per riga): " target_file
    [[ -n "${target_file:-}" && -f "$target_file" ]] || die "file targets non valido: $target_file"
fi

scan_choice="1"
while true; do
    echo
    echo "Tipo scansione:"
    echo "  1) Scan porte (default)"
    echo "  2) Discovery only (-sn)"
    read -r -p "Scegli 1 o 2 [default 1]: " scan_choice
    scan_choice="${scan_choice:-1}"
    [[ "$scan_choice" == "1" || "$scan_choice" == "2" ]] && break
    echo "Valore non valido"
done

ports="$DEFAULT_PORTS"
if [[ "$scan_choice" == "1" ]]; then
    read -r -p "Porte (es. 22,80,443 o 1-65535) [default: $DEFAULT_PORTS]: " input_ports
    ports="${input_ports:-$DEFAULT_PORTS}"
fi

echo
echo "Verbose/debug:"
echo "  0) Nessuno (default)"
echo "  1) -v"
echo "  2) -vv"
echo "  3) -d --packet-trace"
read -r -p "Scegli 0|1|2|3 [default 0]: " vlevel
vlevel="${vlevel:-0}"
[[ "$vlevel" =~ ^[0-3]$ ]] || vlevel=0

read -r -p "Opzioni nmap extra (es. -sC -sV). Nota: -o* sara' ignorato: " nmap_extra
nmap_extra="${nmap_extra:-}"

read -r -p "Directory output [default: $DEFAULT_OUTDIR]: " outdir
outdir="${outdir:-$DEFAULT_OUTDIR}"
read -r -p "Timing template 0..5 [default 3]: " nt
nt="${nt:-3}"
[[ "$nt" =~ ^[0-5]$ ]] || nt=3

echo
echo "Riepilogo:"
if [[ "$mode" == "1" ]]; then
    echo "  Targets: ${targets[*]}"
else
    echo "  Targets file: $target_file"
fi
if [[ "$scan_choice" == "1" ]]; then
    echo "  Modalita: port scan"
    echo "  Porte: $ports"
else
    echo "  Modalita: discovery (-sn)"
fi
echo "  Verbose: $vlevel"
[[ -n "$nmap_extra" ]] && echo "  Extra: $nmap_extra"
echo "  Output dir: $outdir"
echo "  Timing: -T$nt"
read -r -p "Procedere? [y/N]: " confirm
confirm="${confirm:-N}"
[[ "$confirm" =~ ^[Yy]$ ]] || exit 0

mkdir -p "$outdir"
[[ -w "$outdir" ]] || die "directory non scrivibile: $outdir"

ts="$(timestamp)"
label=""
if [[ "$mode" == "1" ]]; then
    label="$(sanitize_label "${targets[0]}")_x${#targets[@]}"
else
    label="$(sanitize_label "$(basename "$target_file")")"
fi

outbase="${outdir%/}/nmap-${ts}_${label}"
outtxt="${outbase}.txt"
outcsv="${outbase}_summary.csv"
outcsv_txt="${outbase}_summary_readable.txt"
outsum="${outbase}_summary.txt"

nmap_opts=(--reason -T"$nt")
case "$vlevel" in
    1) nmap_opts+=(-v) ;;
    2) nmap_opts+=(-vv) ;;
    3) nmap_opts+=(-d --packet-trace) ;;
esac

if [[ "$scan_choice" == "2" ]]; then
    nmap_opts+=(-sn)
else
    if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
        nmap_opts+=(-sS -p "$ports")
    else
        nmap_opts+=(-sT -p "$ports")
    fi
fi

# Parse extra options (split on whitespace) and strip -o* output flags
extra_arr=()
user_spec_scan=0
user_spec_p=0
if [[ -n "$nmap_extra" ]]; then
    read -r -a tmp <<< "$nmap_extra"
    skip_next=0
    for tok in "${tmp[@]}"; do
        if ((skip_next)); then
            skip_next=0
            continue
        fi
        if [[ "$tok" == "-o" ]]; then
            skip_next=1
            continue
        fi
        if [[ "$tok" =~ ^-o ]]; then
            continue
        fi
        [[ "$tok" =~ ^-s ]] && user_spec_scan=1
        [[ "$tok" == "-p" || "$tok" =~ ^-p.+ ]] && user_spec_p=1
        extra_arr+=("$tok")
    done
fi

if ((user_spec_scan)); then
    filtered=()
    for x in "${nmap_opts[@]}"; do
        [[ "$x" == "-sS" || "$x" == "-sT" ]] && continue
        filtered+=("$x")
    done
    nmap_opts=("${filtered[@]}")
fi

if ((user_spec_p)); then
    filtered=()
    skip_next=0
    for x in "${nmap_opts[@]}"; do
        if ((skip_next)); then
            skip_next=0
            continue
        fi
        if [[ "$x" == "-p" ]]; then
            skip_next=1
            continue
        fi
        filtered+=("$x")
    done
    nmap_opts=("${filtered[@]}")
fi

nmap_cmd=("$NMAP_BIN" "${nmap_opts[@]}")
if [[ "$mode" == "2" ]]; then
    nmap_cmd+=(-iL "$target_file")
else
    nmap_cmd+=("${targets[@]}")
fi
if ((${#extra_arr[@]} > 0)); then
    nmap_cmd+=("${extra_arr[@]}")
fi
nmap_cmd+=(-oN "$outtxt")

echo
printf 'Comando:'
for part in "${nmap_cmd[@]}"; do printf ' %q' "$part"; done
echo

set +e
"${nmap_cmd[@]}"
ec=$?
set -e

# CSV summary
printf '%s\n' "Hostname,IP,MAC,Vendor,Status,OpenPorts" > "$outcsv"
awk -v OUTCSV="$outcsv" '
    BEGIN { host=""; ip=""; mac=""; vendor=""; status=""; inports=0; openports="" }
    function flush() {
        if (host == "") return
        gsub(/"/, "\"\"", host)
        gsub(/"/, "\"\"", vendor)
        printf "\"%s\",%s,\"%s\",\"%s\",%s,\"%s\"\n", host, ip, mac, vendor, status, openports >> OUTCSV
    }
    /^Nmap scan report for/ {
        flush()
        line=$0
        sub(/^Nmap scan report for /, "", line)
        host=line
        ip="N/A"; mac=""; vendor=""; status=""; openports=""
        if (match(line, /\(([0-9.]+)\)/, a)) {
            ip=a[1]
            sub(/ \([0-9.]+\)$/, "", host)
        } else if (line ~ /^[0-9.]+$/) {
            ip=line
        }
        next
    }
    /^[Hh]ost is up/ { status="up"; next }
    /Host seems down|host down|received no-response/ { if (status=="") status="down"; next }
    /^MAC Address:/ {
        mac=$3
        vendor=""
        if (index($0, "(") > 0) vendor=substr($0, index($0, "(")+1)
        gsub(/\)$/, "", vendor)
        next
    }
    /^PORT[[:space:]]+STATE/ { inports=1; next }
    /^$/ { inports=0; next }
    inports && $2 ~ /^open/ {
        frag=$1 "(" $3 ")"
        if (openports == "") openports=frag; else openports=openports ";" frag
        next
    }
    END { flush() }
' "$outtxt" 2>/dev/null || true

# Readable summary from CSV
{
    printf "%-40s %-15s %-8s %s\n" "Hostname" "IP" "Status" "OpenPorts"
    printf "%-40s %-15s %-8s %s\n" "--------" "--" "------" "--------"
    awk -F',' 'NR>1 {
        gsub(/^"|"$/, "", $1); gsub(/^"|"$/, "", $6)
        host=$1; ip=$2; status=$5; ports=$6
        if (length(ports) > 140) ports=substr(ports,1,137) "..."
        printf "%-40s %-15s %-8s %s\n", host, ip, status, ports
    }' "$outcsv"
} > "$outcsv_txt" 2>/dev/null || true

# Short summary
if [[ "$scan_choice" == "2" ]]; then
    grep -E "^Nmap scan report for|Host is up|^MAC Address:" "$outtxt" > "$outsum" 2>/dev/null || true
else
    awk -F',' 'NR>1 { gsub(/^"|"$/, "", $1); gsub(/^"|"$/, "", $6); print $1 " | " $2 " | " $5 " | " $6 }' "$outcsv" > "$outsum" 2>/dev/null || true
fi

# Latest links (best-effort)
ln -sf "$(basename "$outtxt")" "${outdir%/}/nmap_latest.txt" 2>/dev/null || true
ln -sf "$(basename "$outcsv")" "${outdir%/}/nmap_summary_latest.csv" 2>/dev/null || true
ln -sf "$(basename "$outcsv_txt")" "${outdir%/}/nmap_summary_latest.txt" 2>/dev/null || true

echo
echo "Exit code: $ec"
echo "Output: $outtxt"
echo "CSV: $outcsv"
echo "Readable: $outcsv_txt"
echo "Summary: $outsum"
exit "$ec"
