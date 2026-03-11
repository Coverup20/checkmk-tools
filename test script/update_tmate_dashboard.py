#!/usr/bin/env python3
"""
update_tmate_dashboard.py - Aggiorna la dashboard TMATE in CheckMK
Sostituisce i dashlet generici con una lista servizi filtrata ^Tmate.
"""
import ast
import time
import shutil
import os
import sys

DASHBOARD_FILE = '/omd/sites/monitoring/var/check_mk/web/cmkadmin/user_dashboards.mk'


def main():
    if not os.path.exists(DASHBOARD_FILE):
        print(f"ERROR: {DASHBOARD_FILE} not found")
        sys.exit(1)

    with open(DASHBOARD_FILE, 'r') as f:
        content = f.read()

    try:
        dashboards = ast.literal_eval(content)
    except Exception as e:
        print(f"ERROR parsing dashboard file: {e}")
        sys.exit(1)

    if 'tmate' not in dashboards:
        print("ERROR: 'tmate' dashboard not found in file")
        sys.exit(1)

    # Backup
    backup_path = DASHBOARD_FILE + f'.bak_{int(time.time())}'
    shutil.copy2(DASHBOARD_FILE, backup_path)
    print(f"Backup created: {backup_path}")

    dashboards['tmate'] = {
        'link_from': {},
        'megamenu_search_terms': [],
        'packaged': False,
        'single_infos': [],
        'name': 'tmate',
        'title': 'TMATE Sessions',
        'topic': 'overview',
        'sort_index': 12,
        'is_show_more': False,
        'description': 'Dashboard showing all active TMATE remote sessions.\n',
        'icon': 'dashboard_main',
        'add_context_to_title': False,
        'hidden': False,
        'hidebutton': False,
        'public': True,
        'show_title': True,
        'mandatory_context_filters': [],
        'dashlets': [
            {
                'type': 'view',
                'size': (0, 0),
                'position': (1, 1),
                'single_infos': [],
                'background': True,
                'show_title': True,
                'title': 'TMATE Sessions',
                'title_url': '',
                'context': {},
                'name': 'dashlet_1',
                'sort_index': 99,
                'add_context_to_title': False,
                'is_show_more': False,
                'datasource': 'services',
                'browser_reload': 30,
                'layout': 'table',
                'num_columns': 1,
                'column_headers': 'pergroup',
                'mobile': True,
                'mustsearch': False,
                'force_checkboxes': False,
                'user_sortable': True,
                'play_sounds': False,
                'painters': [
                    {
                        'name': 'service_state',
                        'parameters': {},
                        'link_spec': None,
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                    {
                        'name': 'host',
                        'parameters': {'color_choices': []},
                        'link_spec': ('views', 'host'),
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                    {
                        'name': 'service_description',
                        'parameters': {},
                        'link_spec': ('views', 'service'),
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                    {
                        'name': 'svc_plugin_output',
                        'parameters': {},
                        'link_spec': None,
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                    {
                        'name': 'svc_state_age',
                        'parameters': {},
                        'link_spec': None,
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                    {
                        'name': 'svc_check_age',
                        'parameters': {},
                        'link_spec': None,
                        'tooltip': None,
                        'join_value': None,
                        'column_title': '',
                        'column_type': 'column',
                    },
                ],
                'group_painters': [],
                'sorters': [('svcdescr', False, None)],
                'packaged': False,
                'megamenu_search_terms': [],
            }
        ],
        'mtime': int(time.time()),
        'context': {
            'serviceregex': {'service_regex': '^Tmate'},
        },
        'owner': 'cmkadmin',
    }

    with open(DASHBOARD_FILE, 'w') as f:
        f.write(repr(dashboards))

    print("TMATE dashboard updated successfully!")
    print("Dashboard now shows ONLY Tmate.* services.")


if __name__ == '__main__':
    main()
