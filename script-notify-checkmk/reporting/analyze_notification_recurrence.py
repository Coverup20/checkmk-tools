#!/usr/bin/env python3
"""analyze_notification_recurrence.py — Analisi ricorrenze notifiche per notify.log.
Modulo condiviso tra notification-limiter-report.py e MCP server."""

import os, gzip, re
from collections import defaultdict, Counter
from datetime import datetime

def parse_notifications(site='monitoring'):
    """Parsa notify.log e restituisce una lista di tuple (host, service, timestamp, state)."""
    log_dir = f'/omd/sites/{site}/var/log'
    base_log = log_dir + '/notify.log'
    
    log_files = [base_log]
    for i in range(1, 20):
        for ext in [f'.{i}.gz', f'.{i}']:
            fp = f'{log_dir}/notify.log{ext}'
            if os.path.isfile(fp):
                log_files.append(fp)
                break
        else:
            break

    pat_svc = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
        r'SERVICE NOTIFICATION: [^;]+;(?P<host>[^;]+);(?P<service>[^;]+);(?P<state>[^;]+);'
    )
    pat_host = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
        r'HOST NOTIFICATION: [^;]+;(?P<host>[^;]+);(?P<state>[^;]+);'
    )

    events = defaultdict(list)
    for fp in log_files:
        try:
            f = gzip.open(fp, 'rt', errors='replace') if fp.endswith('.gz') else open(fp, 'r', errors='replace')
            for line in f:
                m = pat_svc.search(line)
                if m:
                    ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                    events[m.group('host')].append((ts, m.group('service'), m.group('state')))
                    continue
                m = pat_host.search(line)
                if m:
                    ts = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                    events[m.group('host')].append((ts, 'HOST', m.group('state')))
            f.close()
        except:
            pass
    return events

def analyze_recurrences(events):
    """Analizza gli eventi di notifica e restituisce una lista di pattern."""
    rows = []
    def fmt_dur(s):
        if s < 60: return f"{s:.0f}s"
        if s < 3600: return f"{s/60:.0f}m"
        return f"{s/3600:.1f}h"
    
    for host in events:
        sorted_events = sorted(events[host], key=lambda x: x[0])
        svc_map = defaultdict(list)
        for ts, svc, st in sorted_events:
            svc_map[svc].append((ts, st))
        for svc in sorted(svc_map, key=lambda s: -len(svc_map[s])):
            se = sorted(svc_map[svc], key=lambda x: x[0])
            if len(se) < 4: continue
            sw = []; ip = False; ps = None
            for ts, st in se:
                if st in ('CRITICAL','WARNING','DOWN','UNKNOWN'):
                    if not ip: ip = True; ps = ts
                elif st in ('OK','UP'):
                    if ip: ip = False; sw.append((ps, ts, (ts-ps).total_seconds()))
            if len(sw) < 2: continue
            tot = len(sw)
            span = (se[-1][0] - se[0][0]).total_seconds()
            freq = tot / (span/86400) if span else 0
            avg = sum(d for _,_,d in sw) / tot
            ct = Counter(s.strftime('%H:%M') for s,_,_ in sw)
            ot = Counter(e.strftime('%H:%M') for _,e,_ in sw)
            tc = ct.most_common(1)[0][0]; to = ot.most_common(1)[0][0]
            cdt = datetime.strptime(tc,'%H:%M'); odt = datetime.strptime(to,'%H:%M')
            cn = sum(1 for t in ct if abs((datetime.strptime(t,'%H:%M')-cdt).total_seconds())<=1800)
            on = sum(1 for t in ot if abs((datetime.strptime(t,'%H:%M')-odt).total_seconds())<=1800)
            ir = (cn/tot>=0.6 and on/tot>=0.6 and freq<2) or (freq<1.5 and tot>=3 and cn/tot>=0.5 and on/tot>=0.5)
            rows.append((tot, freq, avg, host.replace('.urbinoservizi.it',''), svc, tc, to, ir))
    
    rows.sort(key=lambda r: -r[0])
    total = sum(len(v) for v in events.values())
    return rows, total

def format_dur(s):
    if s < 60: return f"{s:.0f}s"
    if s < 3600: return f"{s/60:.0f}m"
    return f"{s/3600:.1f}h"
