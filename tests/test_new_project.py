# Tests for creating projects: slug suggestion, validation, the request sent and the dialog.
# Live tests use a token without permission to create projects, so they cover the refusal path only.

import asyncio

import pytest
from textual.widgets import DataTable, Input, Label, Select
from test_txadmin import ORGANISATION, TOKEN, live

from txadmin.app import ProjectsApp
from txadmin.client import Team, TransifexClient, ValueTooLongError, new_project_payload
from txadmin.new_project import DEFAULT_TEAM, NewProject, NewProjectScreen, creation_fields, parse_new_project
from txadmin.validation import parse_project_name, parse_slug, suggest_slug

NEW_PROJECT = NewProject("APP: Dashboard", "app-dashboard", "https://github.com/dhis2/dashboard-app", DEFAULT_TEAM.id)


@pytest.mark.parametrize(
    "name, slug",
    [
        ("APP: Dashboard", "app-dashboard"),
        ("ANDROID: APK Distribution", "android-apk-distribution"),
        ("  Capture -- App 2.0 ", "capture-app-2-0"),
        ("", ""),
    ],
)
def test_suggest_slug(name, slug):
    assert suggest_slug(name) == slug


def test_parse_project_name_strips_and_requires_a_name():
    assert parse_project_name("  APP: Dashboard ") == "APP: Dashboard"
    with pytest.raises(ValueError, match="Name is required."):
        parse_project_name("  ")
    with pytest.raises(ValueError, match="at most 255 characters"):
        parse_project_name("x" * 256)


@pytest.mark.parametrize("text", ["", "app dashboard", "app:dashboard", "x" * 256])
def test_parse_slug_rejects_invalid_slugs(text):
    with pytest.raises(ValueError, match="Slug"):
        parse_slug(text)


def test_parse_slug_accepts_letters_digits_dashes_and_underscores():
    assert parse_slug(" App_dashboard-2 ") == "App_dashboard-2"


def test_parse_new_project_requires_homepage():
    with pytest.raises(ValueError, match="Homepage is required."):
        parse_new_project("APP: Dashboard", "app-dashboard", " ", DEFAULT_TEAM.id)


def test_parse_new_project_returns_cleaned_values():
    assert parse_new_project(" APP: Dashboard", "app-dashboard ", " https://github.com/dhis2/dashboard-app", DEFAULT_TEAM.id) == NEW_PROJECT


def test_creation_fields_apply_our_project_settings():
    assert creation_fields(NEW_PROJECT) == {
        "name": "APP: Dashboard",
        "slug": "app-dashboard",
        "private": False,
        "license": "permissive_open_source",
        "source_language": "en",
        "homepage_url": "https://github.com/dhis2/dashboard-app",
        "repository_url": "https://github.com/dhis2/dashboard-app",
        "team_id": "o:hisp-uio:t:dhis-2-core-apps",
    }


def test_new_project_payload_is_a_json_api_project():
    assert new_project_payload(f"o:{ORGANISATION}", **creation_fields(NEW_PROJECT)) == {
        "data": {
            "type": "projects",
            "attributes": {
                "name": "APP: Dashboard",
                "slug": "app-dashboard",
                "private": False,
                "license": "permissive_open_source",
                "homepage_url": "https://github.com/dhis2/dashboard-app",
                "repository_url": "https://github.com/dhis2/dashboard-app",
            },
            "relationships": {
                "organization": {"data": {"type": "organizations", "id": "o:hisp-uio"}},
                "source_language": {"data": {"type": "languages", "id": "l:en"}},
                "team": {"data": {"type": "teams", "id": "o:hisp-uio:t:dhis-2-core-apps"}},
            },
        }
    }


def test_new_project_payload_rejects_urls_transifex_cannot_store():
    fields = creation_fields(NEW_PROJECT)
    with pytest.raises(ValueTooLongError, match="Homepage URL would take 201"):
        new_project_payload("o:hisp-uio", **{**fields, "homepage_url": "https://" + "a" * 189 + ".com"})
    with pytest.raises(ValueTooLongError, match="Repository URL would take 256"):
        new_project_payload("o:hisp-uio", **{**fields, "repository_url": "https://" + "a" * 244 + ".com"})


async def _open_new_project_dialog(app: ProjectsApp, pilot) -> NewProjectScreen:
    await app.workers.wait_for_complete()
    await pilot.press("n")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    assert isinstance(app.screen, NewProjectScreen)
    return app.screen


async def _set_input(pilot, screen: NewProjectScreen, field: str, value: str) -> None:
    screen.query_one(f"#{field}", Input).value = value
    await pilot.pause()


@live
def test_dialog_defaults_to_core_apps_team():
    async def run():
        app = ProjectsApp(TransifexClient(TOKEN, ORGANISATION))
        async with app.run_test() as pilot:
            screen = await _open_new_project_dialog(app, pilot)
            return screen.query_one("#team", Select).value, str(screen.query_one("#teams-note", Label).render())

    team, note = asyncio.run(run())

    assert team == DEFAULT_TEAM.id
    assert note == "" or note.startswith(f"Could not load teams, so only {DEFAULT_TEAM.name} is offered:")


@live
def test_dialog_suggests_slug_until_it_is_edited():
    async def run():
        app = ProjectsApp(TransifexClient(TOKEN, ORGANISATION))
        async with app.run_test() as pilot:
            screen = await _open_new_project_dialog(app, pilot)
            slug = screen.query_one("#slug", Input)
            slugs = []
            await _set_input(pilot, screen, "name", "APP: Dashboard")
            slugs.append(slug.value)
            await _set_input(pilot, screen, "slug", "dashboard")
            await _set_input(pilot, screen, "name", "APP: Dashboard 2")
            slugs.append(slug.value)
            return slugs

    assert asyncio.run(run()) == ["app-dashboard", "dashboard"]


@live
def test_dialog_shows_validation_errors_without_creating():
    async def run():
        app = ProjectsApp(TransifexClient(TOKEN, ORGANISATION))
        async with app.run_test() as pilot:
            screen = await _open_new_project_dialog(app, pilot)
            await _set_input(pilot, screen, "name", "TEST: txadmin")
            await pilot.click("#create")
            await pilot.pause()
            return (
                str(screen.query_one("#error", Label).render()),
                str(screen.query_one("#status", Label).render()),
                screen.query_one("#create").disabled,
                app.screen is screen,
            )

    assert asyncio.run(run()) == ("Homepage is required.", "", False, True)


@live
def test_dialog_stays_open_with_transifex_error_when_creation_is_refused():
    client = TransifexClient(TOKEN, ORGANISATION)
    projects_before = {p.id for p in client.projects()}

    async def run():
        app = ProjectsApp(client)
        async with app.run_test() as pilot:
            screen = await _open_new_project_dialog(app, pilot)
            await _set_input(pilot, screen, "name", "TEST: txadmin refused")
            await _set_input(pilot, screen, "homepage", "https://github.com/dhis2/txadmin-test")
            # Read the state before yielding, so the response cannot have arrived yet.
            screen.create()
            creating = (str(screen.query_one("#status", Label).render()), screen.query_one("#create").disabled)
            await app.workers.wait_for_complete()
            await screen.workers.wait_for_complete()
            await pilot.pause()
            after = (
                str(screen.query_one("#error", Label).render()),
                str(screen.query_one("#status", Label).render()),
                screen.query_one("#create").disabled,
                app.screen is screen,
            )
            await pilot.press("escape")
            await pilot.pause()
            return creating, after, isinstance(app.screen, NewProjectScreen), app.query_one(DataTable).row_count

    creating, after, still_open, rows = asyncio.run(run())

    assert creating == ("Creating…", True)
    assert after == ("Transifex API error 403: You do not have permission to perform this action.", "", False, True)
    assert still_open is False
    assert rows == len(projects_before)
    assert {p.id for p in client.projects()} == projects_before


ANDROID_TEAM = Team(id="o:hisp-uio:t:android", name="Android")
ZULU_TEAM = Team(id="o:hisp-uio:t:zulu", name="zulu team")


def _team_choices(teams_loaded: list[list[Team]], choose: str | None = None) -> tuple[list[str], str, str]:
    """Opens the dialog, optionally chooses a team, shows each team list in turn as if loaded from Transifex,
    and returns the offered team ids, the selected team id and the teams note."""

    async def run():
        app = ProjectsApp(TransifexClient("not-a-real-token", ORGANISATION))
        async with app.run_test() as pilot:
            screen = await _open_new_project_dialog(app, pilot)
            select = screen.query_one("#team", Select)
            for teams in teams_loaded:
                screen._show_teams(teams)
                if choose:
                    select.value = choose
                await pilot.pause()
            offered = [value for _, value in select._options]
            return offered, select.value, str(screen.query_one("#teams-note", Label).render())

    return asyncio.run(run())


def test_teams_are_offered_by_name_with_default_selected():
    offered, selected, note = _team_choices([[ZULU_TEAM, DEFAULT_TEAM, ANDROID_TEAM]])

    assert offered == [ANDROID_TEAM.id, DEFAULT_TEAM.id, ZULU_TEAM.id]
    assert selected == DEFAULT_TEAM.id
    assert note == ""


def test_first_team_is_selected_when_default_team_is_missing():
    offered, selected, _ = _team_choices([[ZULU_TEAM, ANDROID_TEAM]])

    assert offered == [ANDROID_TEAM.id, ZULU_TEAM.id]
    assert selected == ANDROID_TEAM.id


def test_chosen_team_is_kept_when_teams_are_shown_again():
    _, selected, _ = _team_choices([[DEFAULT_TEAM, ZULU_TEAM], [ANDROID_TEAM, DEFAULT_TEAM, ZULU_TEAM]], choose=ZULU_TEAM.id)

    assert selected == ZULU_TEAM.id


def test_empty_team_list_keeps_default_team_and_explains():
    offered, selected, note = _team_choices([[]])

    assert offered == [DEFAULT_TEAM.id]
    assert selected == DEFAULT_TEAM.id
    assert note == f"Could not load teams, so only {DEFAULT_TEAM.name} is offered: Transifex returned no teams."
