rules_file = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/rules.mk'

with open(rules_file, 'r') as f:
    content = f.read()

# Fix: aggiunge -H $HOSTADDRESS$ al valore del plugin
old = "('custom', 'check_windows_alive')"
new = "('custom', 'check_windows_alive -H $HOSTADDRESS$')"

if old in content:
    content = content.replace(old, new)
    with open(rules_file, 'w') as f:
        f.write(content)
    print('Fixed! Argomento -H aggiunto')
else:
    print('Pattern non trovato, contenuto attuale:')

with open(rules_file, 'r') as f:
    for line in f:
        if 'host_check' in line or 'custom' in line or 'check_windows' in line:
            print(line.rstrip())
