# Tests for encoding a project's extra sync branches in its tags.
# Covers reading, replacing and parsing the extra-sync-branches tag.

import pytest

from txadmin.branches import extra_branches, parse_branch_list, with_extra_branches


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
