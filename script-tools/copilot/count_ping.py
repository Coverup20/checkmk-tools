#!/usr/bin/env python3
import subprocess
result = subprocess.run(
    ["su", "-", "monitoring", "-c",
     'lq "GET services\nFilter: description = PING\nColumns: host_name host_filename\nOutputFormat: python\n"'],
    capture_output=True, text=True
)
data = eval(result.stdout.strip()) if result.stdout.strip() else []
from collections import Counter
folders = Counter(r[1] for r in data)
print(f"PING services totali: {len(data)}")
for k, v in sorted(folders.items()):
    print(f"  {k}: {v}")
