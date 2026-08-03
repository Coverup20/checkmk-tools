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
