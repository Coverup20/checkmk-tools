"""Tests for steps/remove_all.py's package-removal filter.

Regression test for the gap found 2026-08-03: after the CheckMK 2.5.x
package rename (check-mk-raw- -> check-mk-community- for the community
edition, see steps/checkmk.py), _filter_removal_packages() had never been
updated to match the new prefix, so 'installer.py remove-all' purged the
agent and dependencies but silently left the CheckMK server package itself
installed on any 2.5.x+ host.
"""


def test_filters_check_mk_community_versions(remove_all_module):
    installed = {
        "check-mk-community-2.5.0p10",
        "check-mk-community-2.5.0b2",
        "unrelated-package",
    }
    result = remove_all_module._filter_removal_packages(installed)
    assert "check-mk-community-2.5.0p10" in result
    assert "check-mk-community-2.5.0b2" in result
    assert "unrelated-package" not in result


def test_filters_check_mk_raw_versions(remove_all_module):
    installed = {"check-mk-raw-2.4.0p20", "unrelated-package"}
    result = remove_all_module._filter_removal_packages(installed)
    assert "check-mk-raw-2.4.0p20" in result
    assert "unrelated-package" not in result


def test_filters_exact_match_dependencies(remove_all_module):
    installed = {"check-mk-agent", "apache2", "fail2ban", "curl"}
    result = remove_all_module._filter_removal_packages(installed)
    assert "check-mk-agent" in result
    assert "apache2" in result
    assert "fail2ban" in result
    assert "curl" not in result


def test_empty_installed_set_yields_empty_result(remove_all_module):
    assert remove_all_module._filter_removal_packages(set()) == []


def test_result_is_sorted(remove_all_module):
    installed = {"fail2ban", "apache2", "check-mk-agent"}
    result = remove_all_module._filter_removal_packages(installed)
    assert result == sorted(result)


# --- _backup_cloud_push_units / _backup_cloud_push_files ---------------------
# Regression coverage for the gap found 2026-08-03 alongside the
# check-mk-community fix: remove-all stopped/purged CheckMK itself but left
# the backup-job and cloud-backup-push systemd units, scripts and per-site
# config files behind entirely untouched.

def test_backup_cloud_push_units_stops_site_scoped_instances(remove_all_module):
    to_stop, _ = remove_all_module._backup_cloud_push_units("monitoring")
    assert "checkmk-cloud-backup-push@monitoring.timer" in to_stop
    assert "checkmk-cloud-backup-push@monitoring.path" in to_stop
    assert "checkmk-cloud-backup-push@monitoring.service" in to_stop
    assert "checkmk-backup-job00.service" in to_stop
    assert "checkmk-backup-job01.timer" in to_stop


def test_backup_cloud_push_units_deletes_templates_not_instances(remove_all_module):
    _, to_delete = remove_all_module._backup_cloud_push_units("monitoring")
    assert "checkmk-cloud-backup-push@.service" in to_delete
    assert "checkmk-cloud-backup-push@.timer" in to_delete
    assert "checkmk-cloud-backup-push@.path" in to_delete
    # the site-instantiated unit names are stopped, not deleted as files -
    # only the template (with the bare @) is an actual file on disk
    assert "checkmk-cloud-backup-push@monitoring.service" not in to_delete


def test_backup_cloud_push_units_scoped_to_given_site(remove_all_module):
    to_stop, _ = remove_all_module._backup_cloud_push_units("otherSite")
    assert "checkmk-cloud-backup-push@otherSite.timer" in to_stop
    assert "checkmk-cloud-backup-push@monitoring.timer" not in to_stop


def test_backup_cloud_push_files_scoped_to_site(remove_all_module):
    from pathlib import Path

    files = remove_all_module._backup_cloud_push_files("monitoring")
    assert Path("/usr/local/sbin/checkmk_cloud_backup_push_run.sh") in files
    assert Path("/etc/default/checkmk-cloud-backup-push-monitoring") in files


def test_backup_cloud_push_files_site_name_is_not_hardcoded(remove_all_module):
    from pathlib import Path

    files = remove_all_module._backup_cloud_push_files("otherSite")
    assert Path("/etc/default/checkmk-cloud-backup-push-otherSite") in files
    assert Path("/etc/default/checkmk-cloud-backup-push-monitoring") not in files
