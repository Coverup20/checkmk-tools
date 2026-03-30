#!/bin/bash
source /opt/ydea-toolkit/.env.la

TOKEN=$(curl -s -X POST "${YDEA_BASE_URL}${YDEA_LOGIN_PATH}" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\": ${YDEA_ID}, \"api_key\": \"${YDEA_API_KEY}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token','ERROR'))")

echo "Token ottenuto: ${TOKEN:0:20}..."

curl -s -H "Authorization: Bearer $TOKEN" \
  "${YDEA_BASE_URL}/companies/1708355" | python3 -m json.tool
