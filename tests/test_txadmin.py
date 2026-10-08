# Tests for the Transifex maintenance TUI: project parsing, the API client and the app.
# Tests marked `live` call the real Transifex API and need TX_TOKEN or ~/.transifexrc.

import asyncio
from datetime import datetime, timezone

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, Label

from txadmin.app import (
    ADVANCED_COLUMN_KEYS,
    COLUMN_KEYS,
    TOGGLE_TAGS,
    ConfirmScreen,
    EditScreen,
    ProjectsApp,
    project_row,
    uses_branches,
)
from txadmin.client import (
    API_BASE,
    REQUEST_TIMEOUT_SECONDS,
    Project,
    TransifexClient,
    TransifexError,
    ValueTooLongError,
    clean_tags,
)
from txadmin.branches import resource_branches
from txadmin.credentials import find_token
from txadmin.validation import parse_homepage_url

ORGANISATION = "hisp-uio"
TEST_PROJECT_SLUG = "test-phil-temp"
TOKEN = find_token()
live = pytest.mark.skipif(not TOKEN, reason="no Transifex token found")

PROJECT_PAYLOAD = {
    "id": "o:hisp-uio:p:app-dashboard",
    "type": "projects",
    "attributes": {
        "name": "APP: Dashboard",
        "slug": "app-dashboard",
        "private": False,
        "archived": False,
        "homepage_url": "https://github.com/dhis2/dashboard-app",
        "tags": ["jenkins-app-sync", "jenkins-pr-automerge"],
        "translation_memory_fillup": True,
        "datetime_modified": "2026-09-30T12:34:56Z",
    },
    "relationships": {
        "source_language": {"data": {"type": "languages", "id": "l:en"}},
    },
}


def test_project_from_api_parses_attributes():
    project = Project.from_api(PROJECT_PAYLOAD)

    assert project.id == "o:hisp-uio:p:app-dashboard"
    assert project.name == "APP: Dashboard"
    assert project.slug == "app-dashboard"
    assert project.private is False
    assert project.archived is False
    assert project.homepage_url == "https://github.com/dhis2/dashboard-app"
    assert project.source_language == "en"
    assert project.tags == ("jenkins-app-sync", "jenkins-pr-automerge")
    assert project.translation_memory_fillup is True
    assert project.modified == datetime(2026, 9, 30, 12, 34, 56, tzinfo=timezone.utc)


def test_clean_tags_strips_whitespace_and_drops_empty_and_duplicate_tags():
    assert clean_tags(["jenkins-weekly-app-sync", " jenkins-app-sync", "  ", "jenkins-app-sync "]) == (
        "jenkins-weekly-app-sync",
        "jenkins-app-sync",
    )


def _row_cells(tags: list[str]) -> dict[str, str]:
    payload = {**PROJECT_PAYLOAD, "attributes": {**PROJECT_PAYLOAD["attributes"], "tags": tags}}
    return dict(zip(COLUMN_KEYS, map(str, project_row(Project.from_api(payload), "master, 2.43")), strict=True))


def test_project_row_renders_every_column():
    assert _row_cells(PROJECT_PAYLOAD["attributes"]["tags"]) == {
        "name": "APP: Dashboard",
        "slug": "app-dashboard",
        "homepage": "https://github.com/dhis2/dashboard-app",
        "source": "en",
        "private": "",
        "archived": "",
        "jenkins-app-sync": "◉",
        "jenkins-weekly-app-sync": "○",
        "jenkins-single-app-sync": "○",
        "jenkins-pr-automerge": "◉",
        "tm_fill": "◉",
        "branches": "master, 2.43",
        "extra_branches": "",
        "modified": "2026-09-30 12:34",
        "other_tags": "",
    }


def test_project_row_toggles_need_exact_tags_and_others_are_listed():
    cells = _row_cells([" jenkins-weekly-app-sync", "jenkins-app-sync-extra", "docs"])

    assert [cells[tag] for tag in TOGGLE_TAGS] == ["○", "◉", "○", "○"]
    assert cells["other_tags"] == "jenkins-app-sync-extra, docs"


def test_project_row_styles_toggles_as_radio_buttons():
    row = project_row(Project.from_api(PROJECT_PAYLOAD), "")
    cells = dict(zip(COLUMN_KEYS, row, strict=True))

    assert (cells["jenkins-app-sync"].style, cells["jenkins-app-sync"].justify) == ("bold green", "center")
    assert (cells["jenkins-weekly-app-sync"].style, cells["jenkins-weekly-app-sync"].justify) == ("dim", "center")


def test_project_row_lists_extra_branches_separately_from_other_tags():
    cells = _row_cells(["docs", "extra-sync-branches:main;2.43"])

    assert cells["extra_branches"] == "main, 2.43"
    assert cells["other_tags"] == "docs"


def test_invalid_token_raises_transifex_error():
    client = TransifexClient("not-a-real-token", ORGANISATION)

    with pytest.raises(TransifexError) as error:
        client.projects()

    assert error.value.status == 401


def test_invalid_token_cannot_set_tags():
    client = TransifexClient("not-a-real-token", ORGANISATION)

    with pytest.raises(TransifexError) as error:
        client.set_project_tags(f"o:{ORGANISATION}:p:{TEST_PROJECT_SLUG}", ("jenkins-app-sync",))

    assert error.value.status == 401


def test_tags_longer_than_transifex_allows_are_rejected_before_sending():
    client = TransifexClient("not-a-real-token", ORGANISATION)

    with pytest.raises(ValueTooLongError, match="Tags would take 256 characters; Transifex allows 255."):
        client.set_project_tags(f"o:{ORGANISATION}:p:{TEST_PROJECT_SLUG}", ("a" * 100, "b" * 100, "c" * 54))


def test_homepage_longer_than_transifex_allows_is_rejected_before_sending():
    client = TransifexClient("not-a-real-token", ORGANISATION)
    url = "https://" + "a" * 189 + ".com"

    with pytest.raises(ValueTooLongError, match="Homepage URL would take 201 characters; Transifex allows 200."):
        client.set_homepage_url(f"o:{ORGANISATION}:p:{TEST_PROJECT_SLUG}", url)


@pytest.mark.parametrize(
    "text, url",
    [
        ("https://github.com/dhis2/dashboard-app", "https://github.com/dhis2/dashboard-app"),
        ("  http://example.org/x  ", "http://example.org/x"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_parse_homepage_url_accepts_http_urls_and_empty(text, url):
    assert parse_homepage_url(text) == url


@pytest.mark.parametrize("text", ["github.com/dhis2/x", "not a url", "ftp://example.com", "https://"])
def test_parse_homepage_url_rejects_other_values(text):
    with pytest.raises(ValueError, match="Homepage must be an http:// or https:// URL, or empty."):
        parse_homepage_url(text)


def _run_app_until_loaded(client: TransifexClient) -> tuple[int, str, list[str]]:
    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            notifications = [n.message for n in app._notifications]
            return app.query_one(DataTable).row_count, app.sub_title, notifications

    return asyncio.run(run())


def test_app_reports_load_failure():
    row_count, sub_title, notifications = _run_app_until_loaded(TransifexClient("not-a-real-token", ORGANISATION))

    assert row_count == 0
    assert sub_title == f"o:{ORGANISATION} · load failed"
    assert len(notifications) == 1
    assert notifications[0].startswith("Transifex API error 401")


def _column_keys(app: ProjectsApp) -> list[str]:
    return [key.value for key in app.query_one(DataTable).columns]


def test_app_starts_in_basic_mode_and_toggles_advanced_columns():
    async def run():
        app = ProjectsApp(TransifexClient("not-a-real-token", ORGANISATION))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            modes = [_column_keys(app)]
            for _ in range(2):
                await pilot.press("a")
                modes.append(_column_keys(app))
            return modes

    basic, advanced, basic_again = asyncio.run(run())

    assert basic == [key for key in COLUMN_KEYS if key not in ADVANCED_COLUMN_KEYS]
    assert advanced == list(COLUMN_KEYS)
    assert basic_again == basic


@live
def test_projects_lists_organisation_projects():
    projects = TransifexClient(TOKEN, ORGANISATION).projects()

    assert projects
    assert all(p.id.startswith(f"o:{ORGANISATION}:p:") for p in projects)
    assert len({p.id for p in projects}) == len(projects)


@live
def test_app_shows_one_row_per_project():
    client = TransifexClient(TOKEN, ORGANISATION)
    expected = len(client.projects())

    row_count, sub_title, notifications = _run_app_until_loaded(client)

    assert row_count == expected
    assert sub_title == f"o:{ORGANISATION} · {expected} {'project' if expected == 1 else 'projects'}"
    assert notifications == []


@pytest.fixture
def test_project():
    """The live test project, with its exact original tags, TM fillup and homepage restored after the test."""
    client = TransifexClient(TOKEN, ORGANISATION)
    project = next((p for p in client.projects() if p.slug == TEST_PROJECT_SLUG), None)
    if project is None:
        pytest.skip(f"{TEST_PROJECT_SLUG} is not visible to this token")
    attributes = client._request("GET", f"{API_BASE}/projects/{project.id}")["data"]["attributes"]
    original = {key: attributes[key] for key in ("tags", "translation_memory_fillup", "homepage_url")}
    yield project
    restore = {"data": {"type": "projects", "id": project.id, "attributes": original}}
    client._request("PATCH", f"{API_BASE}/projects/{project.id}", json=restore)


@live
def test_set_project_tags_replaces_tags(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    tags = test_project.tags + ("txadmin-test",)

    updated = client.set_project_tags(test_project.id, tags)

    assert updated.tags == tags
    assert client.project(test_project.id).tags == tags


@live
def test_app_toggles_tag_after_confirmation(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    tag = next(t for t in TOGGLE_TAGS if t not in test_project.tags)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table = app.query_one(DataTable)
            results = []
            for _ in range(2):
                await _select_cell(app, pilot, test_project.id, tag)
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await app.workers.wait_for_complete()
                await pilot.pause()
                results.append((str(table.get_cell(test_project.id, tag)), tag in client.project(test_project.id).tags))
            return results

    assert asyncio.run(run()) == [("◉", True), ("○", False)]


@live
def test_app_leaves_tag_when_declined(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    tag = next(t for t in TOGGLE_TAGS if t not in test_project.tags)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await _select_cell(app, pilot, test_project.id, tag)
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            return isinstance(app.screen, ConfirmScreen), str(app.query_one(DataTable).get_cell(test_project.id, tag))

    assert asyncio.run(run()) == (False, "○")
    assert client.project(test_project.id).tags == test_project.tags


async def _select_cell(app: ProjectsApp, pilot, project_id: str, column: str) -> None:
    table = app.query_one(DataTable)
    table.cursor_coordinate = Coordinate(table.get_row_index(project_id), table.get_column_index(column))
    await pilot.press("enter")
    await pilot.pause()


async def _save_text(app: ProjectsApp, pilot, text: str) -> None:
    assert isinstance(app.screen, EditScreen)
    app.screen.query_one(Input).value = text
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


@live
def test_app_edits_extra_branches(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    other_tags = tuple(t for t in test_project.tags if not t.startswith("extra-sync-branches:"))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table = app.query_one(DataTable)
            results = []
            for text in ("main, 2.43", ""):
                await _select_cell(app, pilot, test_project.id, "extra_branches")
                await _save_text(app, pilot, text)
                results.append((table.get_cell(test_project.id, "extra_branches"), client.project(test_project.id).tags))
            return results

    assert asyncio.run(run()) == [
        ("main, 2.43", other_tags + ("extra-sync-branches:main;2.43",)),
        ("", other_tags),
    ]


@live
def test_app_keeps_branch_dialog_open_on_invalid_input(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await _select_cell(app, pilot, test_project.id, "extra_branches")
            await _save_text(app, pilot, "main, feature;x")
            error = str(app.screen.query_one("#error", Label).render())
            await pilot.press("escape")
            await pilot.pause()
            return error, isinstance(app.screen, EditScreen)

    assert asyncio.run(run()) == ("Branch name 'feature;x' contains a semicolon.", False)
    assert client.project(test_project.id).tags == test_project.tags


@live
def test_app_reports_tags_too_long_without_saving(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    branches = ", ".join(f"release-{n:03}" for n in range(30))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await _select_cell(app, pilot, test_project.id, "extra_branches")
            await _save_text(app, pilot, branches)
            return [n.message for n in app._notifications]

    notifications = asyncio.run(run())

    assert len(notifications) == 1
    assert "Transifex allows 255." in notifications[0]
    assert client.project(test_project.id).tags == test_project.tags


@live
def test_app_shows_current_transifex_state_after_failed_save(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    other_tags = tuple(t for t in test_project.tags if not t.startswith("extra-sync-branches:"))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            client.set_project_tags(test_project.id, other_tags + ("extra-sync-branches:changed-elsewhere",))
            await _select_cell(app, pilot, test_project.id, "extra_branches")
            await _save_text(app, pilot, ", ".join(f"release-{n:03}" for n in range(30)))
            return str(app.query_one(DataTable).get_cell(test_project.id, "extra_branches"))

    assert asyncio.run(run()) == "changed-elsewhere"


@live
def test_set_translation_memory_fillup_round_trip(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    enable = not test_project.translation_memory_fillup

    updated = client.set_translation_memory_fillup(test_project.id, enable)

    assert updated.translation_memory_fillup is enable
    assert client.project(test_project.id).translation_memory_fillup is enable


@live
def test_app_toggles_translation_memory_fillup_after_confirmation(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    original = test_project.translation_memory_fillup

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table = app.query_one(DataTable)
            results = []
            for _ in range(2):
                await _select_cell(app, pilot, test_project.id, "tm_fill")
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await app.workers.wait_for_complete()
                await pilot.pause()
                results.append((str(table.get_cell(test_project.id, "tm_fill")), client.project(test_project.id).translation_memory_fillup))
            return results

    radio = {True: "◉", False: "○"}
    assert asyncio.run(run()) == [(radio[not original], not original), (radio[original], original)]


@live
def test_set_homepage_url_round_trip(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    url = "https://example.org/txadmin-test"

    updated = client.set_homepage_url(test_project.id, url)

    assert updated.homepage_url == url
    assert client.project(test_project.id).homepage_url == url


@live
def test_app_edits_homepage(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("a")
            table = app.query_one(DataTable)
            results = []
            for text in ("https://example.org/txadmin-test", ""):
                await _select_cell(app, pilot, test_project.id, "homepage")
                await _save_text(app, pilot, text)
                results.append((table.get_cell(test_project.id, "homepage"), client.project(test_project.id).homepage_url))
            return results

    assert asyncio.run(run()) == [
        ("https://example.org/txadmin-test", "https://example.org/txadmin-test"),
        ("", ""),
    ]


@live
def test_app_keeps_homepage_dialog_open_on_invalid_url(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("a")
            await _select_cell(app, pilot, test_project.id, "homepage")
            await _save_text(app, pilot, "github.com/dhis2/x")
            error = str(app.screen.query_one("#error", Label).render())
            still_open = isinstance(app.screen, EditScreen)
            await pilot.press("escape")
            await pilot.pause()
            return error, still_open

    assert asyncio.run(run()) == ("Homepage must be an http:// or https:// URL, or empty.", True)
    assert client.project(test_project.id).homepage_url == test_project.homepage_url


@live
def test_app_keeps_rows_and_sort_when_switching_mode():
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one(DataTable)
            rows_before = table.row_count
            await pilot.press("a")
            app.on_data_table_header_selected(DataTable.HeaderSelected(table, table.columns["slug"].key, 1, table.columns["slug"].label))
            sorted_by_slug = app._sort_column
            await pilot.press("a")
            sort_after_basic = app._sort_column
            app.on_data_table_header_selected(DataTable.HeaderSelected(table, table.columns["name"].key, 0, table.columns["name"].label))
            await pilot.press("a")
            app.on_data_table_header_selected(DataTable.HeaderSelected(table, table.columns["modified"].key, 0, table.columns["modified"].label))
            await pilot.press("a")
            return rows_before, table.row_count, sorted_by_slug, sort_after_basic, app._sort_column

    rows_before, rows_after, sorted_by_slug, sort_after_basic, sort_after_hidden = asyncio.run(run())

    assert rows_after == rows_before
    assert (sorted_by_slug, sort_after_basic) == ("slug", "slug")
    assert sort_after_hidden == "name"


@live
def test_typing_a_in_a_dialog_does_not_switch_mode(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await _select_cell(app, pilot, test_project.id, "extra_branches")
            assert isinstance(app.screen, EditScreen)
            app.screen.query_one(Input).value = ""
            await pilot.press("a", "r", "q")
            typed = app.screen.query_one(Input).value
            await pilot.press("escape")
            await pilot.pause()
            return typed, _column_keys(app)

    typed, columns = asyncio.run(run())

    assert typed == "arq"
    assert columns == [key for key in COLUMN_KEYS if key not in ADVANCED_COLUMN_KEYS]


def test_requests_time_out():
    client = TransifexClient("not-a-real-token", ORGANISATION, timeout=0.000001)

    with pytest.raises(OSError, match="timed out"):
        client.projects()


@live
def test_app_shows_saving_until_save_finishes(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    tag = next(t for t in TOGGLE_TAGS if t not in test_project.tags)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table = app.query_one(DataTable)
            # Read the state before yielding, so the save cannot have finished yet.
            app.update_tags(test_project.id, tag, lambda tags: tags + (tag,))
            during = (str(table.get_cell(test_project.id, tag)), app.sub_title)
            await app.workers.wait_for_complete()
            await pilot.pause()
            after = (str(table.get_cell(test_project.id, tag)), app.sub_title)
            return during, after

    during, after = asyncio.run(run())

    assert during[0] == "…"
    assert during[1].endswith(" · saving…")
    assert after == ("◉", during[1].removesuffix(" · saving…"))


@live
def test_app_restores_cell_and_reports_error_when_save_times_out(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    tag = next(t for t in TOGGLE_TAGS if t not in test_project.tags)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            client.timeout = 0.000001
            await _select_cell(app, pilot, test_project.id, tag)
            await pilot.press("y")
            await app.workers.wait_for_complete()
            await pilot.pause()
            cell = str(app.query_one(DataTable).get_cell(test_project.id, tag))
            return cell, app.sub_title, [n.message for n in app._notifications]

    cell, sub_title, notifications = asyncio.run(run())
    client.timeout = REQUEST_TIMEOUT_SECONDS

    assert cell == "○"
    assert "saving" not in sub_title
    assert len(notifications) == 1
    assert "timed out" in notifications[0]
    assert client.project(test_project.id).tags == test_project.tags


@live
def test_resource_slugs_lists_every_resource(test_project):
    slugs = TransifexClient(TOKEN, ORGANISATION).resource_slugs(test_project.id)

    assert slugs
    assert len(set(slugs)) == len(slugs)


@live
def test_basic_mode_does_not_load_branches(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return app._branches_requested, _column_keys(app)

    requested, columns = asyncio.run(run())

    assert requested is False
    assert "branches" not in columns


def _set_uses_branches(client: TransifexClient, project: Project, enabled: bool) -> Project:
    """Sets the project's tags in Transifex so that exactly Daily Sync, or no sync type or automerge, is enabled."""
    others = tuple(tag for tag in project.tags if tag not in TOGGLE_TAGS)
    return client.set_project_tags(project.id, others + (("jenkins-app-sync",) if enabled else ()))


def test_uses_branches_for_any_sync_type_or_automerge():
    def project(tags: list[str]) -> Project:
        return Project.from_api({**PROJECT_PAYLOAD, "attributes": {**PROJECT_PAYLOAD["attributes"], "tags": tags}})

    assert [uses_branches(project([tag])) for tag in TOGGLE_TAGS] == [True, True, True, True]
    assert uses_branches(project(["extra-sync-branches:main", "docs"])) is False


@live
def test_advanced_mode_shows_branches_from_resources(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    _set_uses_branches(client, test_project, True)
    expected = ", ".join(resource_branches(client.resource_slugs(test_project.id)))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            # Read the cell before yielding, so the branches cannot have arrived yet.
            app.action_toggle_advanced()
            before = str(app.query_one(DataTable).get_cell(test_project.id, "branches"))
            await app.workers.wait_for_complete()
            await pilot.pause()
            loaded = str(app.query_one(DataTable).get_cell(test_project.id, "branches"))
            await pilot.press("a", "a")
            await pilot.pause()
            after_switching = str(app.query_one(DataTable).get_cell(test_project.id, "branches"))
            return before, loaded, after_switching

    before, loaded, after_switching = asyncio.run(run())

    assert before == "…"
    assert loaded == expected
    assert after_switching == expected


@live
def test_refresh_in_advanced_mode_reloads_branches(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    _set_uses_branches(client, test_project, True)
    expected = ", ".join(resource_branches(client.resource_slugs(test_project.id)))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("a")
            await app.workers.wait_for_complete()
            generation = app._branches_generation
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await app.workers.wait_for_complete()
            await pilot.pause()
            return app._branches_generation > generation, str(app.query_one(DataTable).get_cell(test_project.id, "branches"))

    assert asyncio.run(run()) == (True, expected)


@live
def test_branch_load_failure_is_shown_once(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    _set_uses_branches(client, test_project, True)

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            client.timeout = 0.000001
            await pilot.press("a")
            await app.workers.wait_for_complete()
            await pilot.pause()
            client.timeout = REQUEST_TIMEOUT_SECONDS
            notifications = [n for n in app._notifications if n.title == "Could not load branches"]
            return str(app.query_one(DataTable).get_cell(test_project.id, "branches")), len(notifications)

    assert asyncio.run(run()) == ("failed", 1)


@live
def test_columns_widen_to_show_updated_cells(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    _set_uses_branches(client, test_project, True)
    branches = tuple(f"release-{n:02}" for n in range(12))
    url = "https://example.org/" + "a-long-homepage-path/" * 4

    async def run():
        app = ProjectsApp(client)
        async with app.run_test(size=(200, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("a")
            await app.workers.wait_for_complete()
            app._show_branches(app._branches_generation, test_project.id, branches)
            await _select_cell(app, pilot, test_project.id, "homepage")
            await _save_text(app, pilot, url)
            await pilot.pause()
            columns = app.query_one(DataTable).columns
            return columns["branches"].content_width, columns["homepage"].content_width

    branches_width, homepage_width = asyncio.run(run())

    assert branches_width >= len(", ".join(branches))
    assert homepage_width >= len(url)


@live
def test_branches_are_skipped_until_a_sync_type_or_automerge_is_enabled(test_project):
    client = TransifexClient(TOKEN, ORGANISATION)
    _set_uses_branches(client, test_project, False)
    expected = ", ".join(resource_branches(client.resource_slugs(test_project.id)))

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table = app.query_one(DataTable)
            await pilot.press("a")
            await app.workers.wait_for_complete()
            await pilot.pause()
            states = [(str(table.get_cell(test_project.id, "branches")), test_project.id in app._branches)]
            for _ in range(2):
                await _select_cell(app, pilot, test_project.id, "jenkins-app-sync")
                await pilot.press("y")
                await app.workers.wait_for_complete()
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                states.append((str(table.get_cell(test_project.id, "branches")), test_project.id in app._branches))
            return states

    assert asyncio.run(run()) == [("—", False), (expected, True), ("—", True)]
