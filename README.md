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

## Script

```
./transyncosaurus.sh
```

This is a bash script that performs the following:

- Loops over the projects in transifex looking for tags that include the `jenkins-app-sync` flag.
  - Loops over all branches that have resources in the project.
    - Pushes the latest source strings to transifex
    - Loops over all [supported languages](#Supported_languages), doing the following:
      1. pull translations from transifex (where more than 20% complete)
      2. raises a PR on github if changes are found for the language  
      (if a PR already exists, then the changes are pushed to that PR)

## Supported Languages

Supported languages (code:name mappings) are configured in the following file:
```
./transifex_languages.json
```
_New languages should be added to transifex and also configured in this file._
