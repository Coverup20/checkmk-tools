#!/usr/bin/env python3
"""Test check_host_status on real production hosts."""
import subprocess, concurrent.futures, time

PLUGIN = "/omd/sites/monitoring/local/lib/nagios/plugins/check_host_status"

TESTS = [
    # (label,              ip,              type,     extra_args)
    # --- Server with CMK agent ---
    ("fw.studiopaci.info", "192.168.32.1",   "server",  ""),
    ("ns8",                "192.168.33.223", "server",  ""),
    ("DC01",               "192.168.33.221", "server",  ""),
    ("HV01eth1",           "192.168.33.220", "server",  ""),
    # --- Switch ---
    ("SW-AreaGare",        "192.168.33.231", "switch",  ""),
    ("SW-AreaStrutture",   "192.168.33.232", "switch",  ""),
    # --- AP UniFi ---
    ("AP-AreaProgettazione","192.168.33.246","switch",  ""),
    ("AP-AreaGare",        "192.168.33.250", "switch",  ""),
    # --- Client (no agent) ---
    ("PC03",               "192.168.32.138", "client",  ""),
    ("WKS01",              "192.168.32.145", "client",  ""),
    # --- NAS ---
    ("NAS100_4100",        "192.168.100.241","server",  ""),
    ("PACI-sede4",         "192.168.200.242","server",  ""),
    # --- Stampanti ---
    ("KM4A7A3C-7001",      "192.168.33.216", "generic", ""),
    ("KM4A85F6-6610",      "192.168.33.215", "generic", ""),
    # --- Controllo negativo: IP inesistente ---
    ("IP_INESISTENTE",     "10.255.255.99",  "client",  "--timeout 1"),
]

def run_check(label, ip, htype, extra):
    cmd = f"{PLUGIN} -H {ip} --type {htype} {extra}".strip()
    t0 = time.time()
    r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30)
    elapsed = time.time() - t0
    out = (r.stdout or r.stderr or "").strip().split("|")[0].strip()
    return label, htype, r.returncode, out, elapsed

STATE = {0: "OK  ", 1: "WARN", 2: "CRIT", 3: "UNK "}

print(f"\n{'='*90}")
print(f"  TEST check_host_status v2.3.0 - {len(TESTS)} host")
print(f"{'='*90}")
print(f"{'Host':<25} {'Type':<8} {'St':<5} {'Tempo':>6}  Output")
print(f"{'-'*90}")

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(run_check, *t): t for t in TESTS}
    results = []
    for f in concurrent.futures.as_completed(futures):
        try:
            results.append(f.result())
        except Exception as e:
            t = futures[f]
            results.append((t[0], t[2], 3, str(e), 0))

results.sort(key=lambda x: TESTS.index(next(t for t in TESTS if t[0]==x[0])))

ok = warn = crit = unk = 0
for label, htype, rc, out, elapsed in results:
    s = STATE.get(rc, "UNK ")
    if rc == 0: ok += 1
    elif rc == 1: warn += 1
    elif rc == 2: crit += 1
    else: unk += 1
    # truncate output if too long
    out_short = out[:60] + "..." if len(out) > 63 else out
    print(f"{label:<25} {htype:<8} {s:<5} {elapsed:>5.1f}s  {out_short}")

print(f"{'-'*90}")
print(f"  OK={ok}  WARN={warn}  CRIT={crit}  UNK={unk}")
print(f"{'='*90}\n")
