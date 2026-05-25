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

## Bot commit signing

`dhis2-core` (and likely other target repos) require **signed commits with a DCO sign-off** on every commit before a PR is mergeable. Without both, the auto-generated sync PRs sit blocked indefinitely and have to be manually amended.

The `transyncosaurus_ALL.sh` script calls `git commit --signoff` (DCO). For the cryptographic signature, the workflow imports an SSH signing key from a repository secret and configures git to sign every commit.

### One-time setup (requires admin on the `dhis2-bot` GitHub account and on this repo)

1. **Generate an ed25519 SSH key for signing** on a trusted local machine:

   ```bash
   ssh-keygen -t ed25519 -C "dhis2-bot signing key" -f dhis2-bot-signing -N ""
   ```

   That produces `dhis2-bot-signing` (private) and `dhis2-bot-signing.pub` (public).

2. **Add the public key to `dhis2-bot`'s GitHub account** as a *signing* key:
   - https://github.com/settings/keys (while logged in as `dhis2-bot`)
   - Click **New SSH key**, set **Key type → Signing Key**
   - Paste the contents of `dhis2-bot-signing.pub`

3. **Add the private key as a secret in this repo** (`dhis2/transifex-ci`):
   - Settings → Secrets and variables → Actions → New repository secret
   - Name: `DHIS2_BOT_SSH_SIGNING_KEY`
   - Value: the full content of `dhis2-bot-signing` (including the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines)

4. **Delete the local keypair** after both halves are stored remotely:

   ```bash
   shred -u dhis2-bot-signing dhis2-bot-signing.pub
   ```

5. **Verify** by running the workflow manually (Actions → Transifex App Sync → Run workflow). The next sync PR's commits should appear as **Verified** on GitHub and pass DCO.

### Rotation

To rotate the signing key, repeat steps 1–4 with a fresh keypair, then remove the old public key from the bot's GitHub signing keys list.
