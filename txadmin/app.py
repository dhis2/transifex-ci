# Textual TUI for browsing and maintaining the projects of a Transifex organisation.
# Shows projects in a sortable table; selecting a toggle cell flips that setting, selecting a text cell edits it.

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, TypeVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label

from txadmin.branches import extra_branches, is_extra_branches_tag, parse_branch_list, resource_branches, with_extra_branches
from txadmin.client import Project, TransifexClient, TransifexError, ValueTooLongError
from txadmin.new_project import DEFAULT_TEAM, TM_GROUP_FOR_DEFAULT_TEAM, NewProject, NewProjectScreen
from txadmin.validation import parse_homepage_url

T = TypeVar("T")

TAG_COLUMNS = (
    ("Daily Sync", "jenkins-app-sync"),
    ("Weekly Sync", "jenkins-weekly-app-sync"),
    ("Single Sync", "jenkins-single-app-sync"),
    ("Automerge", "jenkins-pr-automerge"),
)
TOGGLE_TAGS = tuple(tag for _, tag in TAG_COLUMNS)

COLUMNS = (
    ("Name", "name"),
    ("Slug", "slug"),
    ("Homepage", "homepage"),
    ("Source", "source"),
    ("Private", "private"),
    ("Archived", "archived"),
    *TAG_COLUMNS,
    ("TM Fill", "tm_fill"),
    ("Branches", "branches"),
    ("Add branches", "extra_branches"),
    ("Modified", "modified"),
    ("Other tags", "other_tags"),
)
COLUMN_KEYS = tuple(key for _, key in COLUMNS)
ADVANCED_COLUMN_KEYS = frozenset({"homepage", "branches", "modified", "other_tags"})
# Resource listings fetched at once when loading branches, well within Transifex's 500 requests a minute.
BRANCH_LOADERS = 4


def _flag(value: bool) -> str:
    return "✓" if value else ""


def _toggle(value: bool) -> Text:
    """Renders a tag toggle as a radio button."""
    if value:
        return Text("◉", style="bold green", justify="center")
    return Text("○", style="dim", justify="center")


SAVING = Text("…", justify="center")
LOADING = Text("…")
LOAD_FAILED = Text("failed", style="red")
NO_BRANCH_JOBS = Text("—", style="dim")


def uses_branches(project: Project) -> bool:
    """Whether any sync type or automerge is enabled for the project, so the CI scripts work on its branches."""
    return any(tag in project.tags for tag in TOGGLE_TAGS)


def _sort_key(value: str | Text) -> str:
    return str(value).lower()


def project_row(project: Project, branches: str | Text) -> tuple[str | Text, ...]:
    """The project's cells in column order; branches come from its resources, so they are passed in."""
    return (
        project.name,
        project.slug,
        project.homepage_url,
        project.source_language,
        _flag(project.private),
        _flag(project.archived),
        *(_toggle(tag in project.tags) for tag in TOGGLE_TAGS),
        _toggle(project.translation_memory_fillup),
        branches,
        ", ".join(extra_branches(project.tags)),
        project.modified.strftime("%Y-%m-%d %H:%M"),
        ", ".join(tag for tag in project.tags if tag not in TOGGLE_TAGS and not is_extra_branches_tag(tag)),
    )


class ConfirmScreen(ModalScreen[bool]):
    """Asks a yes/no question and dismisses with the answer."""

    BINDINGS = [
        ("y", "answer(True)", "Yes"),
        ("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question)
            with Horizontal():
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, answer: bool) -> None:
        self.dismiss(answer)


class EditScreen(ModalScreen[Optional[T]]):
    """Edits one text value; dismisses with the parsed value, or None when cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str, placeholder: str, parse: Callable[[str], T]):
        super().__init__()
        self.prompt = prompt
        self.value = value
        self.placeholder = placeholder
        self.parse = parse

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.prompt)
            yield Input(self.value, placeholder=self.placeholder)
            yield Label("", id="error")
            with Horizontal():
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        try:
            value = self.parse(self.query_one(Input).value)
        except ValueError as error:
            self.query_one("#error", Label).update(str(error))
        else:
            self.dismiss(value)


class ProjectsApp(App):
    TITLE = "Transifex maintenance"
    CSS = """
    ModalScreen {
        align: center middle;
    }
    .dialog {
        width: 70;
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    .dialog > Horizontal {
        height: auto;
        margin-top: 1;
    }
    .dialog Button {
        width: 1fr;
        margin: 0 1;
    }
    .dialog Label {
        width: 100%;
    }
    .dialog #error {
        color: $error;
    }
    """
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("a", "toggle_advanced", "Basic/Advanced"),
        ("n", "new_project", "New project"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, client: TransifexClient):
        super().__init__()
        self.client = client
        self._projects: dict[str, Project] = {}
        self._sort_column = "name"
        self._sort_reverse = False
        self._advanced = False
        self._status = "loading…"
        self._saves_in_progress = 0
        self._branches: dict[str, tuple[str, ...]] = {}
        self._branch_load_failures: set[str] = set()
        self._branches_requested = False
        self._branches_generation = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="cell", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_table()
        self.action_refresh()

    def visible_columns(self) -> tuple[tuple[str, str], ...]:
        return tuple((label, key) for label, key in COLUMNS if self._advanced or key not in ADVANCED_COLUMN_KEYS)

    def action_toggle_advanced(self) -> None:
        """Switches between the basic and advanced column sets."""
        self._advanced = not self._advanced
        self._rebuild_table()
        self._load_branches_if_shown()

    def _rebuild_table(self) -> None:
        """Recreates the table's columns for the current mode and fills it from the loaded projects."""
        table = self.query_one(DataTable)
        table.clear(columns=True)
        visible = self.visible_columns()
        for label, key in visible:
            table.add_column(label, key=key)
        for project in self._projects.values():
            table.add_row(*self._visible_cells(project), key=project.id)
        if self._sort_column not in {key for _, key in visible}:
            self._sort_column, self._sort_reverse = "name", False
        self._sort()

    def _visible_cells(self, project: Project) -> list[str | Text]:
        cells = dict(zip(COLUMN_KEYS, project_row(project, self._branches_cell(project))))
        return [cells[key] for _, key in self.visible_columns()]

    def _show_status(self, status: str) -> None:
        self._status = status
        saving = " · saving…" if self._saves_in_progress else ""
        self.sub_title = f"{self.client.organisation_id} · {status}{saving}"

    def action_refresh(self) -> None:
        self._forget_branches()
        self._show_status("loading…")
        self.query_one(DataTable).loading = True
        self.load_projects()

    @work(thread=True, exclusive=True)
    def load_projects(self) -> None:
        try:
            projects = self.client.projects()
        except (TransifexError, OSError) as error:
            self.call_from_thread(self._show_error, str(error))
        else:
            self.call_from_thread(self._show_projects, projects)

    def _show_projects(self, projects: list[Project]) -> None:
        self._projects = {project.id: project for project in projects}
        self._rebuild_table()
        self.query_one(DataTable).loading = False
        self._show_project_count()
        self._load_branches_if_shown()

    def _show_project_count(self) -> None:
        noun = "project" if len(self._projects) == 1 else "projects"
        self._show_status(f"{len(self._projects)} {noun}")

    def action_new_project(self) -> None:
        def created(result: tuple[Project, NewProject] | None) -> None:
            if result is None:
                return
            project, new_project = result
            self._projects[project.id] = project
            self._branches[project.id] = ()
            self._rebuild_table()
            self._show_project_count()
            self.notify(f"Created {project.name}.", title="Project created")
            if new_project.team_id == DEFAULT_TEAM.id:
                self.notify(
                    f"Add {project.name} to the {TM_GROUP_FOR_DEFAULT_TEAM} translation memory group in the Transifex web UI; "
                    "the API cannot do this.",
                    title="Translation memory group",
                    severity="warning",
                    timeout=30,
                )

        self.push_screen(NewProjectScreen(self.client), created)

    def _branches_cell(self, project: Project) -> str | Text:
        if not uses_branches(project):
            return NO_BRANCH_JOBS
        if project.id in self._branches:
            return ", ".join(self._branches[project.id])
        return LOAD_FAILED if project.id in self._branch_load_failures else LOADING

    def _forget_branches(self) -> None:
        """Discards loaded branches, including results still arriving from an earlier load."""
        self._branches = {}
        self._branch_load_failures = set()
        self._branches_requested = False
        self._branches_generation += 1

    def _load_branches_if_shown(self) -> None:
        """Starts loading branches for projects that use them, once the Branches column is first shown for these projects."""
        if self._advanced and self._projects and not self._branches_requested:
            self._branches_requested = True
            self._load_branches([project for project in self._projects.values() if uses_branches(project)])

    def _load_branches_if_newly_used(self, project: Project) -> None:
        """Loads a project's branches when a sync type or automerge has just been enabled for it."""
        known = project.id in self._branches or project.id in self._branch_load_failures
        if self._branches_requested and uses_branches(project) and not known:
            self._load_branches([project])

    def _load_branches(self, projects: list[Project]) -> None:
        if projects:
            self.load_branches(self._branches_generation, [project.id for project in projects])

    @work(thread=True, group="branches")
    def load_branches(self, generation: int, project_ids: list[str]) -> None:
        """Lists the projects' resources a few at a time; stops early once a refresh has made the results stale."""
        failures: list[str] = []
        executor = ThreadPoolExecutor(max_workers=BRANCH_LOADERS)
        futures = {executor.submit(self.client.resource_slugs, project_id): project_id for project_id in project_ids}
        for future in as_completed(futures):
            if generation != self._branches_generation:
                break
            project_id = futures[future]
            try:
                branches = resource_branches(future.result())
            except (TransifexError, OSError) as error:
                failures.append(str(error))
                self.call_from_thread(self._show_branches, generation, project_id, None)
            else:
                self.call_from_thread(self._show_branches, generation, project_id, branches)
        executor.shutdown(wait=False, cancel_futures=True)
        if failures and generation == self._branches_generation:
            message = f"{len(failures)} project(s) failed, e.g. {failures[0]}"
            self.call_from_thread(self.notify, message, title="Could not load branches", severity="error", timeout=10)

    def _show_branches(self, generation: int, project_id: str, branches: tuple[str, ...] | None) -> None:
        """Shows one project's branches, or that loading them failed, unless a refresh has made them stale."""
        if generation != self._branches_generation or project_id not in self._projects:
            return
        if branches is None:
            self._branch_load_failures.add(project_id)
        else:
            self._branches[project_id] = branches
        if self._advanced:
            cell = self._branches_cell(self._projects[project_id])
            self.query_one(DataTable).update_cell(project_id, "branches", cell, update_width=True)

    def _show_error(self, message: str) -> None:
        self.query_one(DataTable).loading = False
        self._show_status("load failed")
        self.notify(message, title="Could not load projects", severity="error", timeout=10)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_key.value
        self._sort_reverse = column == self._sort_column and not self._sort_reverse
        self._sort_column = column
        self._sort()

    def _sort(self) -> None:
        self.query_one(DataTable).sort(self._sort_column, key=_sort_key, reverse=self._sort_reverse)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        column = event.cell_key.column_key.value
        project = self._projects[event.cell_key.row_key.value]
        if column in TOGGLE_TAGS:
            self._confirm_toggle(project, column)
        elif column == "homepage":
            self._edit_homepage(project)
        elif column == "tm_fill":
            self._confirm_translation_memory_fillup(project)
        elif column == "extra_branches":
            self._edit_extra_branches(project)

    def _confirm_toggle(self, project: Project, tag: str) -> None:
        add = tag not in project.tags
        question = f"{'Add' if add else 'Remove'} tag {tag} {'to' if add else 'from'} {project.name}?"

        def toggled(tags: tuple[str, ...]) -> tuple[str, ...]:
            if (tag in tags) == add:
                return tags
            return tags + (tag,) if add else tuple(t for t in tags if t != tag)

        def apply(confirmed: bool | None) -> None:
            if confirmed:
                self.update_tags(project.id, tag, toggled)

        self.push_screen(ConfirmScreen(question), apply)

    def _confirm_translation_memory_fillup(self, project: Project) -> None:
        enable = not project.translation_memory_fillup
        question = f"{'Enable' if enable else 'Disable'} translation memory fillup for {project.name}?"

        def apply(confirmed: bool | None) -> None:
            if confirmed:
                self.save_project(project.id, "tm_fill", lambda: self.client.set_translation_memory_fillup(project.id, enable))

        self.push_screen(ConfirmScreen(question), apply)

    def _edit_extra_branches(self, project: Project) -> None:
        def apply(branches: tuple[str, ...] | None) -> None:
            if branches is not None:
                self.update_tags(project.id, "extra_branches", lambda tags: with_extra_branches(tags, branches))

        prompt = f"Extra branches to sync for {project.name} (comma-separated):"
        branches = ", ".join(extra_branches(project.tags))
        self.push_screen(EditScreen(prompt, branches, "main, 2.43", parse_branch_list), apply)

    def _edit_homepage(self, project: Project) -> None:
        def apply(url: str | None) -> None:
            if url is not None:
                self.save_project(project.id, "homepage", lambda: self.client.set_homepage_url(project.id, url))

        prompt = f"Homepage for {project.name} (empty to clear):"
        self.push_screen(EditScreen(prompt, project.homepage_url, "https://github.com/dhis2/…", parse_homepage_url), apply)

    def update_tags(self, project_id: str, column: str, change: Callable[[tuple[str, ...]], tuple[str, ...]]) -> None:
        """Applies a change to the project's current tags in Transifex, saving only if they differ."""

        def save() -> Project:
            current = self.client.project(project_id)
            tags = change(current.tags)
            return current if tags == current.tags else self.client.set_project_tags(project_id, tags)

        self.save_project(project_id, column, save)

    def save_project(self, project_id: str, column: str, save: Callable[[], Project]) -> None:
        """Marks the cell being changed as saving, then runs the change against Transifex."""
        if column in {key for _, key in self.visible_columns()}:
            self.query_one(DataTable).update_cell(project_id, column, SAVING)
        self._saves_in_progress += 1
        self._show_status(self._status)
        self._run_save(project_id, save)

    @work(thread=True, group="saves")
    def _run_save(self, project_id: str, save: Callable[[], Project]) -> None:
        try:
            updated = save()
        except (TransifexError, ValueTooLongError, OSError) as error:
            self.call_from_thread(self._finish_save, project_id, self._current_project(project_id), str(error))
        else:
            self.call_from_thread(self._finish_save, project_id, updated, None)

    def _current_project(self, project_id: str) -> Project | None:
        """Re-reads a project after a failed save, which Transifex may still have applied (e.g. after a timeout)."""
        try:
            return self.client.project(project_id)
        except (TransifexError, OSError):
            return None

    def _finish_save(self, project_id: str, updated: Project | None, error: str | None) -> None:
        """Shows the project as Transifex has it, falling back to the last known state, and any error."""
        self._saves_in_progress -= 1
        self._show_status(self._status)
        self._show_project(updated or self._projects[project_id])
        if error:
            self.notify(error, title="Could not save changes", severity="error", timeout=10)

    def _show_project(self, project: Project) -> None:
        self._projects[project.id] = project
        table = self.query_one(DataTable)
        for (_, key), value in zip(self.visible_columns(), self._visible_cells(project)):
            table.update_cell(project.id, key, value, update_width=True)
        self._load_branches_if_newly_used(project)
