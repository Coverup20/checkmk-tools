#!/usr/bin/env python3
"""
ydea_check_company.py - Verifica nome azienda su Ydea tramite ID
Usa la libreria YdeaAPI già installata in /opt/ydea-toolkit/full/
"""
import sys
import json
import importlib.util
from pathlib import Path

COMPANY_ID = 1708355

# Carica YdeaAPI dalla libreria toolkit installata
toolkit_path = Path("/opt/ydea-toolkit/full/ydea-toolkit.py")
spec = importlib.util.spec_from_file_location("ydea_toolkit", toolkit_path)
if not spec or not spec.loader:
    print("ERROR: impossibile caricare ydea-toolkit.py")
    sys.exit(1)

ydea_toolkit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ydea_toolkit)  # type: ignore
YdeaAPI = ydea_toolkit.YdeaAPI

api = YdeaAPI()
if not api.ensure_token():
    print("ERROR: login Ydea fallito")
    sys.exit(1)

print("Login OK")

# Query azienda
data, status = api.api_call("GET", f"/companies/{COMPANY_ID}")
print(f"Status: {status}")
if status == 200:
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print(f"Risposta: {data}")
