rules_file = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/rules.mk'

new_rule_block = """
globals().setdefault('ignored_services', [])

ignored_services = [
{'id': 'b5c6d7e8-f9a0-1234-bcde-f01234567891', 'value': ['PING'], 'condition': {'host_folder': '/%s/' % FOLDER_PATH}, 'options': {'description': 'Rimuovi servizio PING dai workstation Windows (host check gia via ARP)', 'disabled': False}},
] + ignored_services

"""

with open(rules_file, 'r') as f:
    content = f.read()

if 'ignored_services' in content:
    print('Rule already present, skipping')
else:
    with open(rules_file, 'a') as f:
        f.write(new_rule_block)
    print('ignored_services rule added')

with open(rules_file, 'r') as f:
    print(f.read())
