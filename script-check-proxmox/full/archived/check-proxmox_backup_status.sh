#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=5

INDEX="/var/log/pve/tasks/index"
INDEX1="/var/log/pve/tasks/index.1"

WARN_HOURS=30
CRIT_HOURS=54

lines="$(
  { [[ -r "$INDEX"  ]] && grep -F ":vzdump:" "$INDEX"  || true
    [[ -r "$INDEX1" ]] && grep -F ":vzdump:" "$INDEX1" || true; } || true
)"

if [[ -z "${lines:-}" ]]; then
  echo "1 PVE_Backup - WARN - no vzdump tasks found in task index"
  exit 0
fi

best_line=""
best_epoch=0

# Pick newest by converting UPID start hex -> epoch in bash
while IFS= read -r line; do
  upid_full="$(echo "$line" | awk '{print $1}')"
  start_hex="$(echo "$upid_full" | awk -F':' '{print $5}')"
  [[ -z "${start_hex:-}" ]] && continue
  # hex -> dec (bash)
  start_epoch=$((16#${start_hex}))
  if (( start_epoch > best_epoch )); then
    best_epoch="$start_epoch"
    best_line="$line"
  fi
done <<< "$lines"

if [[ -z "${best_line:-}" || "$best_epoch" -eq 0 ]]; then
  echo "2 PVE_Backup - CRIT - could not parse any vzdump UPID timestamps"
  exit 0
fi

upid_full="$(echo "$best_line" | awk '{print $1}')"

node="$(echo "$upid_full" | awk -F':' '{print $2}')"
start_hex="$(echo "$upid_full" | awk -F':' '{print $5}')"
task_type="$(echo "$upid_full" | awk -F':' '{print $6}')"
task_id="$(echo "$upid_full" | awk -F':' '{print $7}')"
task_user="$(echo "$upid_full" | awk -F':' '{print $8}')"

start_epoch=$((16#${start_hex}))
now_epoch="$(date +%s)"
age_sec=$(( now_epoch - start_epoch ))
age_hours=$(( age_sec / 3600 ))

task_file="$(find /var/log/pve/tasks -maxdepth 2 -type f -name "${upid_full}" 2>/dev/null | head -n 1 || true)"

res_state=0
res_label="OK"
detail=""

if [[ -n "${task_file:-}" && -r "$task_file" ]]; then
  if grep -qE 'ERROR:|TASK ERROR|task error|failed|cannot|unable|wrong content type' "$task_file"; then
    res_state=2
    res_label="CRIT"
    detail="$(grep -E 'ERROR:|TASK ERROR|task error|failed|cannot|unable|wrong content type' "$task_file" | tail -n 2 | tr '\n' '; ' | sed 's/; $//')"
  else
    detail="$(tail -n 2 "$task_file" 2>/dev/null | tr '\n' '; ' | sed 's/; $//' || true)"
  fi
else
  if echo "$best_line" | grep -qiE 'job errors|unexpected status|unable to read tail|error'; then
    res_state=2
    res_label="CRIT"
  fi
  detail="$(echo "$best_line" | sed -E 's/^[^ ]+ +//')"
fi

age_state=0
if (( age_hours >= CRIT_HOURS )); then
  age_state=2
elif (( age_hours >= WARN_HOURS )); then
  age_state=1
fi

msg="UPID=${upid_full} node=${node} vmid=${task_id} user=${task_user}"
[[ -n "${detail:-}" ]] && msg="${msg} detail=${detail}"

echo "${res_state} PVE_Backup_Last_Result - ${res_label} - ${msg}"
echo "${age_state} PVE_Backup_Last_Age age_hours=${age_hours};${WARN_HOURS};${CRIT_HOURS} - last vzdump ${age_hours}h ago"

exit 0
