#!/bin/bash
echo "=== Lista host nella folder ==="
su - monitoring -c "cmk --list-hosts 2>&1 | grep 'ad.studiopaci' | head -5"

echo ""
echo "=== Rediscovery su un host di test ==="
su - monitoring -c "cmk -II WKS-11settembre.ad.studiopaci.info 2>&1"
echo "EXIT: $?"
