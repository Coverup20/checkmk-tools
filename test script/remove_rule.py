rules_file = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/rules.mk'

with open(rules_file, 'r') as f:
    content = f.read()

# Rimuovi il blocco host_check_commands che abbiamo aggiunto
marker = "\nglobals().setdefault('host_check_commands', [])"
idx = content.find(marker)
if idx >= 0:
    content = content[:idx]
    print('Removed host_check_commands block')
else:
    print('Block not found, nothing to remove')

with open(rules_file, 'w') as f:
    f.write(content)

print('Done. Content:')
with open(rules_file, 'r') as f:
    print(f.read())
