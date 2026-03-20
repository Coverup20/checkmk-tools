#!/usr/bin/env python3
"""
Creates rules.mk for nas and stampanti folders with check_host_status host check commands.
- nas       -> --type server  (NAS with CheckMK agent on port 6556)
- stampanti -> --type generic (printers: ping-only, no agent)
"""

import os
import datetime
import uuid

WATO_BASE = '/omd/sites/monitoring/etc/check_mk/conf.d/wato'

FOLDERS = {
    'nas':       '--type server',
    'stampanti': '--type generic',
}

TEMPLATE = """\
# Written by Administer
# encoding: utf-8

host_check_commands += [
  (('custom', 'check_host_status -H $HOSTADDRESS$ {args}'), [], ALL_HOSTS, {{'comment': u'', 'description': u'', 'docu_url': u'', 'disabled': False}}, {{'id': u'{uid}', 'comment': u'', 'docu_url': u''}}),
]
"""

for folder, args in FOLDERS.items():
    folder_path = os.path.join(WATO_BASE, folder)
    rules_mk    = os.path.join(folder_path, 'rules.mk')

    # Make sure the WATO folder exists (it should, but just in case)
    if not os.path.isdir(folder_path):
        print(f"[SKIP] Folder not found: {folder_path}")
        continue

    # Backup if rules.mk already exists
    if os.path.isfile(rules_mk):
        ts     = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup = rules_mk + '.backup_' + ts
        import shutil
        shutil.copy2(rules_mk, backup)
        os.chown(backup, 1000, 1000)   # monitoring uid/gid (typical)
        os.chmod(backup, 0o660)
        print(f"[BACKUP] {backup}")

    # Write new rules.mk
    content = TEMPLATE.format(args=args, uid=str(uuid.uuid4()))
    with open(rules_mk, 'w') as fh:
        fh.write(content)

    # Fix ownership/permissions
    os.chown(rules_mk, 1000, 1000)
    os.chmod(rules_mk, 0o660)
    print(f"[OK] {rules_mk}  ({args})")

print("Done.")
