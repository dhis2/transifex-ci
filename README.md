# transifex-ci

Scripts for syncing translations between transifex and github

## Requirements

The following tools are required to run the script:

- git
- hub
- tx
- jq
- iconv
- native2ascii

The script also relies on the following being set as env vars:

- $TXTOKEN : API token for transifex
- $GITHUB_USER : guthub user name
- $GITHUB_PASSWORD : access token for guthub
- [optional] $TRANSIFEX_SYNC_TAG: tag to identify projects to sync (default `jenkins-app-sync`)

## Scripts

```
./transyncosaurus_ALL.sh
```

This is a bash script that performs the following:

- Loops over the projects in transifex looking for tags that include the `jenkins-app-sync` flag.
  - Loops over all branches that have resources in the project.
    - Pushes the latest source strings to transifex
    - Pulls translations from transifex (where more than 20% complete)
    - Raises a PR on github if changes are found for any of the languages  
      (if a PR already exists, then the changes are pushed to that PR)

> ./transyncosaurus_ALL.sh can be used to target a single app by temporarily adding the tag `jenkins-single-app-sync` to the transifex project, and running the script with the TRANSIFEX_SYNC_TAG environment variable set to `jenkins-single-app-sync`

```
./pulltergeist.sh
```

This is a bash script that performs the following:

- Loops over the projects in transifex looking for tags that include the `jenkins-pr-automerge` flag.
  - Loops over all branches that have resources in the project.
    - Merges any translation PRs on that branch


## txadmin (maintenance TUI)

A terminal UI for maintaining the `hisp-uio` Transifex organisation. It lists all projects with their key attributes (source language, visibility, archived state, last modified, tags). Click a column header to sort.

The CI tags each have a toggle column; select a toggle cell (Enter, or click it twice) and confirm to add or remove the tag in Transifex:

| Column      | Tag                       |
| ----------- | ------------------------- |
| Daily Sync  | `jenkins-app-sync`        |
| Weekly Sync | `jenkins-weekly-app-sync` |
| Single Sync | `jenkins-single-app-sync` |
| Automerge   | `jenkins-pr-automerge`    |

The "TM Fill" column toggles the project's translation memory fillup setting in the same way. Transifex can take up to a minute to apply that setting; while any change is saving, its cell shows `…` and the title bar shows "saving…".

Select a "Homepage" cell to edit the project's homepage URL (an http:// or https:// URL of up to 200 characters; empty clears it).

The "Add branches" column lists extra branches to sync that are not found from the project's resources. Select it to edit the comma-separated list. The branches are stored in a single project tag, `extra-sync-branches:main;2.43` (semicolon-separated, because Transifex joins tags with commas); clearing the list removes the tag.

Press `n` to create a project. The dialog asks for the name, slug (suggested from the name until you edit it), homepage and team (DHIS 2 Core Apps by default). The project is created public, with the `permissive_open_source` license, English as its source language, and the homepage as its repository URL. The Transifex API cannot manage translation memory groups, so after creating a DHIS 2 Core Apps project the tool reminds you to add it to the `dhis2-ui` group in the Transifex web UI. Creating projects and listing teams need an organisation admin's token.

Any other tags are listed in the "Other tags" column. Transifex stores all of a project's tags as one comma-joined string of at most 255 characters, so the tool refuses changes that would exceed that.

It is run with [uv](https://docs.astral.sh/uv/), which creates the environment (Python 3.10 or newer) from `pyproject.toml` and `uv.lock` on first use:

```
uv run txadmin
```

The API token is taken from the `TX_TOKEN` environment variable or, if that is unset, from the `tx` CLI config in `~/.transifexrc` (the `token` key, or `password` in older files).

Keys: `r` refresh, `a` switch between basic and advanced columns (basic, the default, hides Homepage, Modified and Other tags), `n` new project, `q` quit.

Tests (the live API tests are skipped unless a token is found; they change tags and settings on the `test-phil-temp` project and restore them afterwards):

```
uv run pytest
```
