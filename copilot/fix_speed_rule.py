import shutil, os, datetime

f = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/swtich/rules.mk'
ts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
bak = f + '.backup_' + ts
shutil.copy2(f, bak)
os.system(f'chown monitoring:monitoring {bak} && chmod 660 {bak}')
print(f'Backup: {bak}')

content = open(f).read()
old = "'value': {'state': None, 'speed': 0}, 'condition'"
new = "'value': {'state': None}, 'condition'"
if old in content:
    content = content.replace(old, new)
    content = content.replace(
        'Regola per swtich - speed=0 ignora mismatch velocita porta',
        'Regola per swtich - usa discovered_speed come baseline'
    )
    open(f, 'w').write(content)
    os.system(f'chown monitoring:monitoring {f} && chmod 660 {f}')
    print('OK - speed rimosso dalla regola interfaces')
else:
    print('WARN: stringa non trovata, potrebbe essere gia cambiata')

# Verifica
idx = content.find("checkgroup_parameters['interfaces']")
print(content[idx:idx+300])
