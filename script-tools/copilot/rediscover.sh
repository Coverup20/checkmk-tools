#!/bin/bash
echo "=== Rediscovery su tutti i host rete_192_168_32_0_23 ==="
su - monitoring -c "cmk -II @rete_192_168_32_0_23 2>&1 | tail -10"
echo "EXIT: $?"
