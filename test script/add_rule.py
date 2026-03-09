rules_file = '/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/rules.mk'

new_rule_block = """
globals().setdefault('host_check_commands', [])

host_check_commands = [
{'id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'value': ('custom', 'check_windows_alive'), 'condition': {'host_folder': '/%s/' % FOLDER_PATH}, 'options': {'description': 'Windows workstations ARP check via nmap (bypassa Windows Firewall)', 'disabled': False}},
] + host_check_commands

"""

with open(rules_file, 'r') as f:
    content = f.read()

if 'host_check_commands' in content:
    print('Rule already present, skipping')
else:
    with open(rules_file, 'a') as f:
        f.write(new_rule_block)
    print('Rule added successfully')

with open(rules_file, 'r') as f:
    print(f.read())
