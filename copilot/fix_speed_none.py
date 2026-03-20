import shutil, os, datetime

f = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/swtich/rules.mk'
ts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
bak = f + '.backup_' + ts
shutil.copy2(f, bak)
os.system(f'chown monitoring:monitoring {bak} && chmod 660 {bak}')
print(f'Backup: {bak}')

content = open(f).read()
old = "'value': {'state': None}, 'condition'"
new = "'value': {'state': None, 'speed': None}, 'condition'"
if old in content:
    content = content.replace(old, new)
    content = content.replace(
        'Regola per swtich - usa discovered_speed come baseline',
        'Regola per swtich - ignora speed mismatch (None=disabilitato)'
    )
    open(f, 'w').write(content)
    os.system(f'chown monitoring:monitoring {f} && chmod 660 {f}')
    print('OK - speed: None aggiunto')
else:
    print('WARN: stringa non trovata nel file')
    print('Contenuto attuale regola interfaces:')
    idx = content.find("checkgroup_parameters['interfaces']")
    print(content[idx:idx+400])
