#!/usr/bin/env bash
set -euo pipefail

# scan-nmap-interattivo-verbose.sh
# Interattivo: target (range/host o file), port-scan o discovery (-sn), livello verbose/debug.
# Output: ./scans/nmap-YYYYmmddTHHMMSS_<label>.txt e ./scans/nmap-..._summary.txt

DEFAULT_OUTDIR="./scans"
DEFAULT_PORTS="1-1024"

timestamp() { date +%Y%m%dT%H%M%S; }

die() {
    echo "[ERR] $*" >&2
    exit 1
}

sanitize_label() {
    # Keep only a-zA-Z0-9._- and replace others with _
    printf '%s' "$1" | tr -c '[:alnum:]._-' '_'
}

NMAP_BIN="$(command -v nmap || true)"
[[ -n "$NMAP_BIN" ]] || die "nmap non trovato nel PATH"

echo "SCAN NMAP INTERATTIVO"

mode="1"
while true; do
    read -r -p "Target: (1) host/range/cidr oppure (2) file targets? [1/2] (default 1): " mode
    mode="${mode:-1}"
    [[ "$mode" == "1" || "$mode" == "2" ]] && break
    echo "Valore non valido"
done

target_label=""
target_file=""
target_arg=()
if [[ "$mode" == "1" ]]; then
    read -r -p "Inserisci host/range/cidr (es. 192.168.1.0/24 o 10.0.0.1-254): " range
    [[ -n "${range:-}" ]] || die "nessun target fornito"
    target_arg=("$range")
    target_label="$(sanitize_label "$range")"
else
    read -r -p "Percorso file targets (uno per riga): " target_file
    [[ -n "${target_file:-}" && -f "$target_file" ]] || die "file targets non valido: $target_file"
    target_arg=(-iL "$target_file")
    target_label="$(sanitize_label "$(basename "$target_file")")"
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

read -r -p "Directory output [default: $DEFAULT_OUTDIR]: " outdir
outdir="${outdir:-$DEFAULT_OUTDIR}"
read -r -p "Timing template 0..5 [default 3]: " nt
nt="${nt:-3}"
[[ "$nt" =~ ^[0-5]$ ]] || nt=3

echo
echo "Riepilogo:"
if [[ "$mode" == "1" ]]; then
    echo "  Target: ${target_arg[*]}"
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
echo "  Output dir: $outdir"
echo "  Timing: -T$nt"
read -r -p "Procedere? [y/N]: " confirm
confirm="${confirm:-N}"
[[ "$confirm" =~ ^[Yy]$ ]] || exit 0

mkdir -p "$outdir"
[[ -w "$outdir" ]] || die "directory non scrivibile: $outdir"

ts="$(timestamp)"
outbase="${outdir%/}/nmap-${ts}_${target_label}"
outtxt="${outbase}.txt"
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

nmap_cmd=("$NMAP_BIN" "${nmap_opts[@]}" "${target_arg[@]}" -oN "$outtxt")

echo
printf 'Comando:'
for part in "${nmap_cmd[@]}"; do printf ' %q' "$part"; done
echo

set +e
"${nmap_cmd[@]}"
ec=$?
set -e

if [[ "$scan_choice" == "2" ]]; then
    grep -E "^Nmap scan report for|Host is up|^MAC Address:" "$outtxt" > "$outsum" 2>/dev/null || true
else
    awk '
        /^Nmap scan report for/ { host=$0 }
        /^PORT[[:space:]]+STATE/ { inports=1; next }
        /^$/ { inports=0 }
        inports && $2 ~ /^open/ { print host " | " $0 }
    ' "$outtxt" > "$outsum" 2>/dev/null || true
fi

echo
echo "Exit code: $ec"
echo "Output: $outtxt"
echo "Summary: $outsum"
exit "$ec"
