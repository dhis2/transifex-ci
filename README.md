# transifex-ci

Scripts for syncing translations between transifex and github

## Requirements

The following tools are required to run the script:

- git
- hub
- tx
- jq

The script also relies on the following being set as env vars:

- $TXTOKEN : API token for transifex
- $GITHUB_USER : guthub user name
- $GITHUB_PASSWORD : guthub password
- $GITHUB_TOKEN : Access token for guthub (not 100% sure we need this!)

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

```
./pulltergeist.sh
```

This is a bash script that performs the following:

- Loops over the projects in transifex looking for tags that include the `jenkins-pr-automerge` flag.
  - Loops over all branches that have resources in the project.
    - Merges any translation PRs on that branch
