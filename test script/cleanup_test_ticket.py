#!/usr/bin/env python3
import json
cache = "/opt/ydea-toolkit/cache/ydea_checkmk_tickets.json"
with open(cache, "r") as f:
    data = json.load(f)
removed = data.pop("test-noticket-xyz", None)
with open(cache, "w") as f:
    json.dump(data, f)
if removed:
    print(f"Removed test entry (ticket #{removed.get('ticket_id')})")
else:
    print("Entry not found (already clean)")
