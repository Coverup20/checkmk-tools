#!/usr/bin/env python3
"""
update_dashboards.py - Dashboard personalizzate CheckMK v2
Fixes v2:
- HOST_PROB ctx: rimosso hst0 (UP) -> solo DOWN/UNREACHABLE
- SVC_PROB ctx: rimosso st0 (OK) -> solo WARN/CRIT/UNKNOWN
- Layout migliorato, colonne più utili, sizing corretto
- network_status: aggiunta sezione servizi in allarme
- self_monitoring: fix posizione dashlet UBNT22MARZIO
"""
import ast
import os
import time
import shutil

TS = int(time.time())
DASHBOARD_FILE = "/opt/omd/sites/monitoring/var/check_mk/web/cmkadmin/user_dashboards.mk"
BACKUP = f"{DASHBOARD_FILE}.backup_{time.strftime('%Y-%m-%d_%H-%M-%S')}"


# --- Backup ---
shutil.copy2(DASHBOARD_FILE, BACKUP)
st_orig = os.stat(DASHBOARD_FILE)
os.chown(BACKUP, st_orig.st_uid, st_orig.st_gid)
os.chmod(BACKUP, st_orig.st_mode)
print(f"Backup creato: {BACKUP}")

# --- Read current dashboards ---
with open(DASHBOARD_FILE) as f:
    dashboards = ast.literal_eval(f.read())
print(f"Dashboard esistenti: {list(dashboards.keys())}")


# --- Helper: painter entry ---
def P(name, link=None, parameters=None):
    """Create a standard painter entry"""
    return {
        'name': name,
        'parameters': parameters if parameters is not None else {},
        'link_spec': link,
        'tooltip': None,
        'join_value': None,
        'column_title': '',
        'column_type': 'column',
    }


def view_dashlet(name, title, title_url, position, size, datasource, painters,
                 context=None, sorters=None, reload=30, sort_index=1,
                 play_sounds=False, mobile=False, background=True):
    """Create a standard embedded-view dashlet"""
    return {
        'type': 'view',
        'size': size,
        'position': position,
        'single_infos': [],
        'background': background,
        'show_title': True,
        'title': title,
        'title_url': title_url,
        'context': context or {},
        'name': name,
        'sort_index': sort_index,
        'add_context_to_title': False,
        'is_show_more': False,
        'datasource': datasource,
        'browser_reload': reload,
        'layout': 'table',
        'num_columns': 1,
        'column_headers': 'pergroup',
        'mobile': mobile,
        'mustsearch': False,
        'force_checkboxes': False,
        'user_sortable': True,
        'play_sounds': play_sounds,
        'painters': painters,
        'group_painters': [],
        'sorters': sorters or [],
        'packaged': False,
        'megamenu_search_terms': [],
    }


# =============================================
# Contesti riutilizzabili (v2 - filtri corretti)
# =============================================
# Solo DOWN (hst1) e UNREACHABLE (hst2) - non UP (hst0)!
HOST_PROBLEM_CTX = {
    'hoststate': {'hst0': '', 'hst1': 'on', 'hst2': 'on', 'hstp': ''},
    'host_acknowledged': {'is_host_acknowledged': '0'},
    'host_scheduled_downtime_depth': {'is_host_scheduled_downtime_depth': '0'},
}
# Solo WARN (st1), CRIT (st2), UNKNOWN (st3) - non OK (st0)!
SVC_PROBLEM_CTX = {
    'hoststate': {'hst0': 'on', 'hst1': 'on', 'hst2': 'on', 'hstp': 'on'},
    'svcstate': {'st0': '', 'st1': 'on', 'st2': 'on', 'st3': 'on', 'stp': 'on'},
    'service_acknowledged': {'is_service_acknowledged': '0'},
    'in_downtime': {'is_in_downtime': '0'},
}


# =============================================
# Dashboard 1: lab_full v2 - Panoramica Completa
# Layout:
#   Row  1-20: [HostStats 36w] [SvcStats 36w] [HostProbs fill-right]
#   Row 21-42: [SvcProbs full width]
#   Row 43-60: [Events full width]
#   Row 61+:   [Inventory full width con ping output]
# =============================================
lab_full_dashlets = [
    # --- Riga stats ---
    {
        'title': 'Statistiche Host',
        'type': 'hoststats',
        'position': (1, 1),
        'size': (36, 20),
        'show_title': True,
        'context': {},
        'single_infos': [],
    },
    {
        'title': 'Statistiche Servizi',
        'type': 'servicestats',
        'position': (37, 1),
        'size': (36, 20),
        'show_title': True,
        'context': {},
        'single_infos': [],
    },
    # Host problems - anchored right, stessa riga stats
    view_dashlet(
        name='lf_hostprob',
        title='Host con Problemi (non gestiti)',
        title_url='view.py?view_name=hostproblems&is_host_acknowledged=0',
        position=(-1, 1), size=(0, 20),
        datasource='hosts',
        painters=[
            P('host_state'),
            P('host', link=('views', 'host')),
            P('host_address'),
            P('host_icons'),
            P('host_state_age'),
            P('host_plugin_output'),
        ],
        context=HOST_PROBLEM_CTX,
        sorters=[('hoststate', True, None)],
        reload=30, play_sounds=True, sort_index=1,
    ),
    # Service problems - larghezza piena
    view_dashlet(
        name='lf_svcprob',
        title='Servizi con Problemi (non gestiti)',
        title_url='view.py?view_name=svcproblems&is_service_acknowledged=0',
        position=(1, 21), size=(0, 22),
        datasource='services',
        painters=[
            P('service_state'),
            P('host', link=('views', 'host')),
            P('service_description', link=('views', 'service')),
            P('service_icons'),
            P('svc_plugin_output'),
            P('svc_state_age'),
            P('svc_check_age'),
        ],
        context=SVC_PROBLEM_CTX,
        sorters=[('svcstate', True, None), ('stateage', False, None), ('svcdescr', False, None)],
        reload=30, play_sounds=True, sort_index=2,
    ),
    # Events - larghezza piena
    view_dashlet(
        name='lf_events',
        title='Ultimi eventi (ultime 4 ore)',
        title_url='view.py?view_name=events_dash',
        position=(1, 43), size=(0, 18),
        datasource='log_events',
        painters=[
            P('log_icon'),
            P('log_time'),
            P('host', link=('views', 'hostsvcevents')),
            P('service_description', link=('views', 'svcevents')),
            P('log_plugin_output'),
        ],
        context={'logtime': {'logtime_from_range': '3600', 'logtime_from': '4'}},
        sorters=[('log_time', True, None)],
        reload=60, sort_index=3,
    ),
    # Inventario completo con ping output e contatori OK/WARN/CRIT
    view_dashlet(
        name='lf_allhosts',
        title='Inventario Host - Stato Completo',
        title_url='view.py?view_name=allhosts',
        position=(1, 61), size=(0, 0),
        datasource='hosts',
        painters=[
            P('host_state'),
            P('host', link=('views', 'host')),
            P('host_address'),
            P('host_icons'),
            P('host_num_services_ok'),
            P('host_num_services_warn'),
            P('host_num_services_crit'),
            P('host_state_age'),
            P('host_plugin_output'),
            P('host_check_age'),
        ],
        context={},
        sorters=[('hoststate', True, None), ('host', False, None)],
        reload=60, sort_index=4,
    ),
]

dashboards['lab_full'] = {
    'link_from': {},
    'megamenu_search_terms': ['lab', 'overview', 'completa', 'panoramica'],
    'packaged': False,
    'single_infos': [],
    'name': 'lab_full',
    'title': 'Lab - Panoramica Completa',
    'topic': 'overview',
    'sort_index': 5,
    'is_show_more': False,
    'description': 'Panoramica completa del lab - tutti gli host e servizi, senza filtri di folder.\n',
    'icon': 'dashboard_main',
    'add_context_to_title': False,
    'hidden': False,
    'hidebutton': False,
    'public': True,
    'show_title': True,
    'mandatory_context_filters': [],
    'dashlets': lab_full_dashlets,
    'mtime': TS,
    'context': {},
    'owner': 'cmkadmin',
}
print("Dashboard 'lab_full' v2 OK")


# =============================================
# Dashboard 2: network_status v2
# Layout:
#   Row  1-20: [HostStats 40w] [SvcStats 40w]
#   Row 21-38: [Host DOWN/UNREACHABLE - full width]
#   Row 39-56: [Servizi WARN/CRIT - full width]
#   Row 57+:   [Inventario rete con ping rta]
# =============================================
network_dashlets = [
    # Stats
    {
        'title': 'Host UP / DOWN',
        'type': 'hoststats',
        'position': (1, 1),
        'size': (40, 20),
        'show_title': True,
        'context': {},
        'single_infos': [],
    },
    {
        'title': 'Stato Servizi',
        'type': 'servicestats',
        'position': (41, 1),
        'size': (40, 20),
        'show_title': True,
        'context': {},
        'single_infos': [],
    },
    # Host non raggiungibili (solo DOWN + UNREACHABLE)
    view_dashlet(
        name='ns_hostdown',
        title='Host NON Raggiungibili (DOWN / UNREACHABLE)',
        title_url='view.py?view_name=hostproblems',
        position=(1, 21), size=(0, 18),
        datasource='hosts',
        painters=[
            P('host_state'),
            P('host', link=('views', 'host')),
            P('host_address'),
            P('host_icons'),
            P('host_state_age'),
            P('host_plugin_output'),
        ],
        context={'hoststate': {'hst0': '', 'hst1': 'on', 'hst2': 'on', 'hstp': ''}},
        sorters=[('hoststate', True, None)],
        reload=30, play_sounds=True, sort_index=1,
    ),
    # Servizi in allarme (WARN/CRIT/UNKNOWN - non OK)
    view_dashlet(
        name='ns_svcwarn',
        title='Servizi con Allarmi (WARN / CRIT / UNKNOWN)',
        title_url='view.py?view_name=svcproblems',
        position=(1, 39), size=(0, 18),
        datasource='services',
        painters=[
            P('service_state'),
            P('host', link=('views', 'host')),
            P('service_description', link=('views', 'service')),
            P('svc_plugin_output'),
            P('svc_state_age'),
        ],
        context=SVC_PROBLEM_CTX,
        sorters=[('svcstate', True, None), ('stateage', False, None)],
        reload=30, play_sounds=True, sort_index=2,
    ),
    # Inventario rete con ping RTA
    view_dashlet(
        name='ns_inventory',
        title='Inventario Rete - Ping / RTA',
        title_url='view.py?view_name=allhosts',
        position=(1, 57), size=(0, 0),
        datasource='hosts',
        painters=[
            P('host_state'),
            P('host', link=('views', 'host')),
            P('host_address'),
            P('host_icons'),
            P('host_state_age'),
            P('host_plugin_output'),
            P('host_check_age'),
        ],
        context={},
        sorters=[('hoststate', True, None), ('host', False, None)],
        reload=60, sort_index=3,
    ),
]

dashboards['network_status'] = {
    'link_from': {},
    'megamenu_search_terms': ['network', 'ping', 'rete', 'disponibilita'],
    'packaged': False,
    'single_infos': [],
    'name': 'network_status',
    'title': 'Stato Rete - Disponibilita Host',
    'topic': 'overview',
    'sort_index': 8,
    'is_show_more': False,
    'description': 'Monitoraggio disponibilita rete - stato ping e raggiungibilita dei dispositivi del lab.\n',
    'icon': 'dashboard_main',
    'add_context_to_title': False,
    'hidden': False,
    'hidebutton': False,
    'public': True,
    'show_title': True,
    'mandatory_context_filters': [],
    'dashlets': network_dashlets,
    'mtime': TS,
    'context': {},
    'owner': 'cmkadmin',
}
print("Dashboard 'network_status' v2 OK")


# =============================================
# Dashboard 3: self_monitoring v2
# Fix: rimuovi vecchio sm_ubnt_svc (posizione errata)
#      riaggiungi con position (1,-1) = bottom-left anchor
# =============================================
if 'self_monitoring' in dashboards:
    sm = dashboards['self_monitoring']
    # Rimuovi eventuale versione precedente
    sm['dashlets'] = [d for d in sm['dashlets'] if d.get('name') != 'sm_ubnt_svc']
    # Aggiungi la vista servizi UBNT22MARZIO ancorata al fondo
    sm['dashlets'].append(view_dashlet(
        name='sm_ubnt_svc',
        title='Tutti i Servizi - UBNT22MARZIO',
        title_url='view.py?view_name=host&host=UBNT22MARZIO',
        position=(1, -1), size=(0, 0),
        datasource='services',
        painters=[
            P('service_state'),
            P('service_description', link=('views', 'service')),
            P('service_icons'),
            P('svc_plugin_output'),
            P('svc_state_age'),
            P('svc_check_age'),
        ],
        context={'host': {'host': 'UBNT22MARZIO'}},
        sorters=[('svcstate', True, None), ('svcdescr', False, None)],
        reload=30, sort_index=5,
    ))
    sm['mtime'] = TS
    dashboards['self_monitoring'] = sm
    print("Dashboard 'self_monitoring' v2 OK")


# --- Scrivi il file aggiornato ---
with open(DASHBOARD_FILE, 'w') as f:
    f.write(repr(dashboards))

# Ripristina permessi owner monitoring:monitoring
os.chown(DASHBOARD_FILE, st_orig.st_uid, st_orig.st_gid)
os.chmod(DASHBOARD_FILE, st_orig.st_mode)

print(f"\n=== COMPLETATO v2 ===")
print(f"Dashboard nel file: {list(dashboards.keys())}")
print(f"Backup in: {BACKUP}")
print(f"Owner: uid={st_orig.st_uid} gid={st_orig.st_gid}")
print("OK")
