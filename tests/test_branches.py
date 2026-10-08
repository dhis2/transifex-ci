# Tests for working out a project's sync branches.
# Covers branches derived from resource slugs and reading, replacing and parsing the extra-sync-branches tag.

import pytest

import json
import subprocess

from txadmin.branches import extra_branches, parse_branch_list, resource_branches, with_extra_branches


def test_extra_branches_reads_branches_in_order():
    assert extra_branches(("jenkins-app-sync", "extra-sync-branches:main;2.43")) == ("main", "2.43")


def test_extra_branches_merges_multiple_tags_and_ignores_blanks():
    assert extra_branches(("extra-sync-branches:main;;2.43", "extra-sync-branches: 2.43;2.42")) == ("main", "2.43", "2.42")


def test_extra_branches_empty_without_tag():
    assert extra_branches(("jenkins-app-sync",)) == ()


def test_with_extra_branches_replaces_existing_tags_and_keeps_others():
    tags = ("extra-sync-branches:old", "jenkins-app-sync", "extra-sync-branches:older")

    assert with_extra_branches(tags, ("main", "2.43")) == ("jenkins-app-sync", "extra-sync-branches:main;2.43")


def test_with_extra_branches_removes_tag_when_no_branches():
    assert with_extra_branches(("jenkins-app-sync", "extra-sync-branches:main"), ()) == ("jenkins-app-sync",)


def test_parse_branch_list_splits_on_commas_and_strips():
    assert parse_branch_list(" main, 2.43 ,,feat/x-y_z, main") == ("main", "2.43", "feat/x-y_z")


def test_parse_branch_list_empty_text_means_no_branches():
    assert parse_branch_list("  ") == ()


def test_parse_branch_list_rejects_whitespace_in_names():
    with pytest.raises(ValueError, match="'my branch' contains whitespace"):
        parse_branch_list("main, my branch")


def test_parse_branch_list_rejects_separator_in_names():
    with pytest.raises(ValueError, match="'a;b' contains a semicolon"):
        parse_branch_list("a;b")


RESOURCE_SLUGS = ["master--app-json", "2-43--app-json", "master--other", "2-42--app-json", "demo-resource", "2-43--more"]


def test_resource_branches_takes_branch_before_double_hyphen_once_each():
    assert resource_branches(RESOURCE_SLUGS) == ("master", "2.43", "2.42")


def test_resource_branches_skips_slugs_without_a_branch():
    assert resource_branches(["demo-resource", "pagination-test-001"]) == ()


def test_resource_branches_match_the_sync_script():
    """For slugs that name a branch, the sync script's jq pipeline (from transyncosaurus_ALL.sh) gives the same
    branches; the script removes repeats with uniq afterwards."""
    script_filter = '.data[].attributes.slug | split("--")[0] | split("-") | join(".")'
    slugs = [slug for slug in RESOURCE_SLUGS if "--" in slug]
    payload = json.dumps({"data": [{"attributes": {"slug": slug}} for slug in slugs]})
    output = subprocess.run(["jq", "-r", script_filter], input=payload, capture_output=True, text=True, check=True).stdout
    assert tuple(dict.fromkeys(output.split())) == resource_branches(RESOURCE_SLUGS)
