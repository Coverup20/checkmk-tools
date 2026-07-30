from __future__ import annotations

from pathlib import Path

from lib.common import backup_file, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig

# install-checkmk-log-optimizer.sh (and its .py wrapper) were archived and removed from the repo
# without ever being reimplemented - this step now does the job directly in Python instead of
# shelling out to a script that no longer exists.

_LOGROTATE_FILE = Path("/etc/logrotate.d/checkmk-installer")
_PRUNE_CRON_NAME = "prune-old-logs"
_PRUNE_MAX_AGE_DAYS = 30


def _logrotate_stanza(paths: str) -> str:
    return "\n".join(
        [
            paths + " {",
            "    daily",
            "    missingok",
            "    rotate 14",
            "    compress",
            "    delaycompress",
            "    notifempty",
            "    copytruncate",
            "}",
        ]
    )


def run_step(cfg: InstallerConfig) -> None:
    log_header("95-LOG-OPTIMIZER")

    site_dir = Path(f"/omd/sites/{cfg.site_name}")
    if not site_dir.is_dir():
        log_warn(f"Sito OMD non trovato: {site_dir}. CheckMK non installato? Skip.")
        return

    log_info("Configuring logrotate for Nagios/Apache/OMD/Event Console/Notify logs...")

    run_cmd(["apt-get", "install", "-y", "logrotate"])

    # Rotated via copytruncate: OMD daemons keep their log file handles open, and there is no
    # single reload signal that covers all of them, so copy-then-truncate is the safe generic
    # choice instead of per-daemon postrotate scripts.
    stanzas = [
        _logrotate_stanza(f"{site_dir}/var/log/nagios.log"),
        _logrotate_stanza(f"{site_dir}/var/log/web.log"),
        _logrotate_stanza(f"{site_dir}/var/log/mkeventd.log"),
        _logrotate_stanza(f"{site_dir}/var/log/notify.log"),
        _logrotate_stanza(f"{site_dir}/var/log/rrdcached.log"),
        _logrotate_stanza(f"{site_dir}/var/log/liveproxyd.log"),
        _logrotate_stanza(f"{site_dir}/var/log/apache/access_log {site_dir}/var/log/apache/error_log"),
    ]

    if _LOGROTATE_FILE.exists():
        backup_file(_LOGROTATE_FILE)
    _LOGROTATE_FILE.write_text("\n\n".join(stanzas) + "\n", encoding="utf-8")
    log_info(f"Wrote logrotate config: {_LOGROTATE_FILE}")

    # Validate the config so a syntax error here doesn't silently break rotation for every
    # other package sharing /etc/logrotate.d.
    run_cmd(["logrotate", "-d", str(_LOGROTATE_FILE)], check=False)

    # Crash reports (var/check_mk/crashes/<type>/<id>/) and Event Console history
    # (var/mkeventd/history/*.log) are directories of discrete files, not one growing log -
    # logrotate can't prune those by age, so that goes in the site's own cron instead.
    cron_dir = site_dir / "etc" / "cron.d"
    if not cron_dir.exists():
        log_warn(f"OMD cron directory not found: {cron_dir}. Skip crash/Event Console cleanup cron.")
        log_success("Log optimization pack installed (logrotate only)")
        return

    cron_file = cron_dir / _PRUNE_CRON_NAME
    if cron_file.exists():
        backup_file(cron_file)

    cron_file.write_text(
        "\n".join(
            [
                f"# Prune CheckMK crash reports and Event Console history older than {_PRUNE_MAX_AGE_DAYS} days",
                f"15 3 * * * find {site_dir}/var/check_mk/crashes -mindepth 2 -maxdepth 2 -type d "
                f"-mtime +{_PRUNE_MAX_AGE_DAYS} -exec rm -rf {{}} + > /dev/null 2>&1",
                f"20 3 * * * find {site_dir}/var/mkeventd/history -type f -name '*.log' "
                f"-mtime +{_PRUNE_MAX_AGE_DAYS} -delete > /dev/null 2>&1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log_info(f"Wrote crash/Event Console cleanup cron: {cron_file}")

    run_cmd(["su", "-", cfg.site_name, "-c", "omd reload crontab"], check=False)

    log_success("Log optimization pack installed")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
