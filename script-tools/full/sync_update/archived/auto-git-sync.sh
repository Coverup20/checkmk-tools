#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

REPO_URL="https://github.com/Coverup20/checkmk-tools.git"
SYNC_INTERVAL="${1:-60}"

LOG_FILE="/var/log/auto-git-sync.log"

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    local level="$1"; shift
    local msg="$*"
    printf '[%s] %s: %s\n' "$(timestamp)" "$level" "$msg"
    {
        printf '[%s] %s: %s\n' "$(timestamp)" "$level" "$msg" >>"$LOG_FILE"
    } 2>/dev/null || true
}

ensure_log_file() {
    if [[ -w "$(dirname "$LOG_FILE")" ]] || mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null; then
        touch "$LOG_FILE" 2>/dev/null || true
        return 0
    fi
    LOG_FILE="$HOME/auto-git-sync.log"
    touch "$LOG_FILE" 2>/dev/null || true
}

detect_target_dir() {
    local candidates=("/opt/checkmk-tools" "/root/checkmk-tools" "$HOME/checkmk-tools")
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -d "$candidate/.git" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    # Default preferred location
    printf '%s\n' "/opt/checkmk-tools"
}

clone_repo_if_needed() {
    local target_dir="$1"
    if [[ -d "$target_dir/.git" ]]; then
        return 0
    fi

    log INFO "Repository not found at $target_dir; cloning"
    mkdir -p "$(dirname "$target_dir")" 2>/dev/null || true
    rm -rf "$target_dir" 2>/dev/null || true
    if ! timeout 180 git clone "$REPO_URL" "$target_dir"; then
        log ERROR "git clone failed"
        return 1
    fi
}

repo_is_valid() {
    (
        cd "$1" 2>/dev/null || exit 1
        git rev-parse --is-inside-work-tree >/dev/null 2>&1
    )
}

reset_to_remote_default() {
    local target_dir="$1"

    if ! repo_is_valid "$target_dir"; then
        log WARNING "Repository invalid/corrupted; recloning"
        rm -rf "$target_dir" 2>/dev/null || true
        clone_repo_if_needed "$target_dir" || return 1
    fi

    log INFO "Fetching updates"
    if ! (
        cd "$target_dir" 2>/dev/null || exit 1
        timeout 120 git fetch origin
    ); then
        log ERROR "git fetch failed"
        return 1
    fi

    local remote_head local_branch
    remote_head="$(
        cd "$target_dir" 2>/dev/null || exit 1
        git symbolic-ref -q refs/remotes/origin/HEAD || true
    )"
    if [[ -z "$remote_head" ]]; then
        remote_head="origin/main"
    else
        # Convert refs/remotes/origin/main -> origin/main
        remote_head="${remote_head#refs/remotes/}"
    fi
    local_branch="${remote_head#origin/}"

    log INFO "Reset to $remote_head"
    # Force local branch to track the remote default.
    (
        cd "$target_dir" 2>/dev/null || exit 1
        git checkout -B "$local_branch" "$remote_head" >/dev/null 2>&1 || true
    )
    if ! (
        cd "$target_dir" 2>/dev/null || exit 1
        timeout 60 git reset --hard "$remote_head"
    ); then
        log ERROR "git reset --hard failed"
        return 1
    fi
    # Aggressive cleanup (handles renames and deleted paths)
    (
        cd "$target_dir" 2>/dev/null || exit 1
        # Preserve local configuration/state files that must survive sync.
        # NOTE: `git clean -x` would delete even ignored files, so we explicitly exclude them.
        git clean -fdx \
            -e .env -e .env.* \
            -e install/checkmk-installer/.env -e install/checkmk-installer/.env.* \
            >/dev/null 2>&1 || true
    )

    # Keep scripts executable
    find "$target_dir" -type f -name "*.sh" -exec chmod +x {} + 2>/dev/null || true
    return 0
}

main() {
    ensure_log_file

    if ! command -v git >/dev/null 2>&1; then
        log ERROR "git not found"
        exit 1
    fi

    local target_dir
    target_dir="$(detect_target_dir)"
    log INFO "Using repo dir: $target_dir"
    log INFO "Sync interval: ${SYNC_INTERVAL}s"

    clone_repo_if_needed "$target_dir" || exit 1

    # First sync immediately
    if reset_to_remote_default "$target_dir"; then
        log INFO "Initial sync ok"
    else
        log ERROR "Initial sync failed"
    fi

    while true; do
        sleep "$SYNC_INTERVAL"
        if reset_to_remote_default "$target_dir"; then
            log INFO "Sync ok"
        else
            log ERROR "Sync failed"
        fi
    done
}

main "$@"
