# Works out a project's sync branches: those found from its resources, and the extra ones in a project tag.
# The tag looks like "extra-sync-branches:main;2.43"; branch names are separated by semicolons.

from collections.abc import Iterable

EXTRA_BRANCHES_PREFIX = "extra-sync-branches:"
BRANCH_SEPARATOR = ";"


def resource_branches(resource_slugs: Iterable[str]) -> tuple[str, ...]:
    """Derives the branches a project has resources for, as transyncosaurus_ALL.sh does: the part of each
    resource slug before "--", with hyphens turned back into dots (so "2-43--app" becomes "2.43").
    Slugs without "--" do not name a branch and are skipped."""
    return tuple(
        dict.fromkeys(slug.split("--")[0].replace("-", ".") for slug in resource_slugs if "--" in slug)
    )


def is_extra_branches_tag(tag: str) -> bool:
    return tag.startswith(EXTRA_BRANCHES_PREFIX)


def extra_branches(tags: tuple[str, ...]) -> tuple[str, ...]:
    """Returns the branches listed in the project's extra-sync-branches tags, in order."""
    branches = (
        branch.strip()
        for tag in tags
        if is_extra_branches_tag(tag)
        for branch in tag.removeprefix(EXTRA_BRANCHES_PREFIX).split(BRANCH_SEPARATOR)
    )
    return tuple(dict.fromkeys(branch for branch in branches if branch))


def with_extra_branches(tags: tuple[str, ...], branches: tuple[str, ...]) -> tuple[str, ...]:
    """Returns the tags with the extra-sync-branches tag replaced by one listing these branches."""
    others = tuple(tag for tag in tags if not is_extra_branches_tag(tag))
    if not branches:
        return others
    return others + (EXTRA_BRANCHES_PREFIX + BRANCH_SEPARATOR.join(branches),)


def parse_branch_list(text: str) -> tuple[str, ...]:
    """Parses a comma-separated list of branch names as typed by the user."""
    branches = tuple(dict.fromkeys(branch.strip() for branch in text.split(",") if branch.strip()))
    for branch in branches:
        if any(character.isspace() for character in branch):
            raise ValueError(f"Branch name {branch!r} contains whitespace.")
        if BRANCH_SEPARATOR in branch:
            raise ValueError(f"Branch name {branch!r} contains a semicolon.")
    return branches
