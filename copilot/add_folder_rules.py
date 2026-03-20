import shutil, os, datetime, uuid

BASE = "/omd/sites/monitoring/etc/check_mk/conf.d/wato"
ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

configs = [
    ("swtich",          "switch", "Switch managed"),
    ("ap_-_unifi",      "switch", "Access Point UniFi"),
    ("firewall",        "switch", "Firewall/NethSecurity"),
    ("self_monitoring", "server", "Self monitoring server"),
]

RULE_TEMPLATE = "\nglobals().setdefault('host_check_commands', [])\n\nhost_check_commands = [\n{{'id': '{uid}', 'value': ('custom', 'check_host_status -H $HOSTADDRESS$ --type {htype}'), 'condition': {{'host_folder': '/%s/' % FOLDER_PATH}}, 'options': {{'disabled': False, 'description': '{desc}'}}}},\n] + host_check_commands\n"

for folder, htype, desc in configs:
    fpath = f"{BASE}/{folder}/rules.mk"
    bak   = fpath + ".backup_" + ts
    shutil.copy2(fpath, bak)
    os.system(f"chown monitoring:monitoring {bak} && chmod 660 {bak}")
    with open(fpath) as fh:
        content = fh.read()
    if "host_check_commands" in content:
        print(f"SKIP {folder}: gia presente host_check_commands")
        continue
    block = RULE_TEMPLATE.format(uid=str(uuid.uuid4()), htype=htype, desc=desc)
    content += block
    with open(fpath, "w") as fh:
        fh.write(content)
    os.system(f"chown monitoring:monitoring {fpath} && chmod 660 {fpath}")
    print(f"OK {folder} -> --type {htype}")

print("DONE")
