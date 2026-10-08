# Dialog for creating a project with the settings we use for DHIS2 projects.
# New projects are public, permissively licensed, in English, and use the homepage as their repository URL.

from dataclasses import dataclass

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from txadmin.client import Project, Team, TransifexClient, TransifexError, ValueTooLongError
from txadmin.validation import parse_homepage_url, parse_project_name, parse_slug, suggest_slug

DEFAULT_TEAM = Team(id="o:hisp-uio:t:dhis-2-core-apps", name="DHIS 2 Core Apps")
LICENSE = "permissive_open_source"
SOURCE_LANGUAGE = "en"
TM_GROUP_FOR_DEFAULT_TEAM = "dhis2-ui"


@dataclass(frozen=True)
class NewProject:
    name: str
    slug: str
    homepage_url: str
    team_id: str


def parse_new_project(name: str, slug: str, homepage: str, team_id: str) -> NewProject:
    homepage_url = parse_homepage_url(homepage)
    if not homepage_url:
        raise ValueError("Homepage is required.")
    return NewProject(parse_project_name(name), parse_slug(slug), homepage_url, team_id)


def creation_fields(new_project: NewProject) -> dict:
    """The fields for TransifexClient.create_project, with our standard settings for new projects."""
    return {
        "name": new_project.name,
        "slug": new_project.slug,
        "private": False,
        "license": LICENSE,
        "source_language": SOURCE_LANGUAGE,
        "homepage_url": new_project.homepage_url,
        "repository_url": new_project.homepage_url,
        "team_id": new_project.team_id,
    }


class NewProjectScreen(ModalScreen[tuple[Project, NewProject] | None]):
    """Collects a new project's details and creates it; dismisses with the created project, or None when cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, client: TransifexClient):
        super().__init__()
        self.client = client
        self._suggested_slug = ""
        self._creating = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("New project")
            yield Label("Name")
            yield Input(placeholder="APP: Dashboard", id="name", compact=True)
            yield Label("Slug")
            yield Input(placeholder="app-dashboard", id="slug", compact=True)
            yield Label("Homepage (also used as the repository URL)")
            yield Input(placeholder="https://github.com/dhis2/…", id="homepage", compact=True)
            yield Label("Team")
            yield Select([(DEFAULT_TEAM.name, DEFAULT_TEAM.id)], value=DEFAULT_TEAM.id, allow_blank=False, id="team", compact=True)
            yield Label("Loading teams…", id="teams-note")
            yield Label("", id="error")
            yield Label("", id="status")
            with Horizontal():
                yield Button("Create", variant="primary", id="create")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.load_teams()

    @work(thread=True)
    def load_teams(self) -> None:
        try:
            teams = self.client.teams()
        except (TransifexError, OSError) as error:
            self.app.call_from_thread(self._show_teams_error, str(error))
        else:
            self.app.call_from_thread(self._show_teams, teams)

    def _show_teams(self, teams: list[Team]) -> None:
        """Offers the teams by name, keeping the current choice if possible, else the default team, else the first."""
        if not teams:
            self._show_teams_error("Transifex returned no teams.")
            return
        teams = sorted(teams, key=lambda team: team.name.lower())
        team_ids = [team.id for team in teams]
        select = self.query_one("#team", Select)
        selected = select.value
        select.set_options((team.name, team.id) for team in teams)
        select.value = next(team_id for team_id in (selected, DEFAULT_TEAM.id, team_ids[0]) if team_id in team_ids)
        self.query_one("#teams-note", Label).update("")

    def _show_teams_error(self, message: str) -> None:
        self.query_one("#teams-note", Label).update(f"Could not load teams, so only {DEFAULT_TEAM.name} is offered: {message}")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Keeps the slug following the name until the slug is edited by hand."""
        slug = self.query_one("#slug", Input)
        if event.input.id == "name" and slug.value == self._suggested_slug:
            self._suggested_slug = suggest_slug(event.value)
            slug.value = self._suggested_slug

    def on_input_submitted(self) -> None:
        self.create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self.create()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        if not self._creating:
            self.dismiss(None)

    def create(self) -> None:
        """Validates the form and, if it is valid, starts creating the project."""
        if self._creating:
            return
        try:
            new_project = parse_new_project(
                self.query_one("#name", Input).value,
                self.query_one("#slug", Input).value,
                self.query_one("#homepage", Input).value,
                self.query_one("#team", Select).value,
            )
        except ValueError as error:
            self._show_error(str(error))
            return
        self._show_error("")
        self._set_creating(True)
        self.run_create(new_project)

    @work(thread=True)
    def run_create(self, new_project: NewProject) -> None:
        try:
            project = self.client.create_project(**creation_fields(new_project))
        except (TransifexError, ValueTooLongError, OSError) as error:
            self.app.call_from_thread(self._create_failed, str(error))
        else:
            self.app.call_from_thread(self.dismiss, (project, new_project))

    def _create_failed(self, message: str) -> None:
        self._set_creating(False)
        self._show_error(message)

    def _set_creating(self, creating: bool) -> None:
        self._creating = creating
        self.query_one("#status", Label).update("Creating…" if creating else "")
        self.query_one("#create", Button).disabled = creating
        self.query_one("#cancel", Button).disabled = creating

    def _show_error(self, message: str) -> None:
        self.query_one("#error", Label).update(message)
