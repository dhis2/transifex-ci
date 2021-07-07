#!/usr/bin/env bash
# Script to exchange translation files between repo and Transifex via Jenkins.
# It relies on $TXTOKEN and $GHTOKEN being set as env vars for the given job

# set up the python environment
if [ ! -d "venv" ]; then
    source setup_venv
fi
source ./venv/bin/activate

# Ensure required tools are available
for exe in "git" "hub" "tx" "jq" "iconv" "native2ascii"; do
  if [[ ! $(command -v $exe) ]]; then
    echo "This script requires $exe. Exiting"
    exit 1
  fi
done

# Ensure ENV variables are set
if [[ -z "$TXTOKEN" ]]; then
   echo "TXTOKEN environment variable must be set."
   exit 1
fi
if [[ -z "$GITHUB_USER" ]]; then
   echo "GITHUB_USER environment variable must be set."
   exit 1
fi
if [[ -z "$GITHUB_PASSWORD" ]]; then
   echo "GITHUB_PASSWORD environment variable must be set."
   exit 1
fi

# set -xv


GITHUB_BASE="https://github.com/dhis2/"
GITHUB_CLONE_BASE="https://${GITHUB_USER}:${GITHUB_PASSWORD}@github.com/dhis2/"
SYNC_DATE=$(date +"%Y%m%d_%H%M%S")
TX_API=https://www.transifex.com/api/2
SYNC_FLAG="jenkins-single-app-sync"

# --- options : set the following to `0` to test without pushing anything to remote systems
PUSH_TRANSLATION_STRINGS=1
CREATE_PULL_REQUEST=1


# --- functions
tx_init() {

if [[ ! -f ~/.transifexrc ]]
then

  echo "[https://www.transifex.com]
api_hostname = https://api.transifex.com
hostname = https://www.transifex.com
username = api
password = $TXTOKEN" > ~/.transifexrc

fi

}

git_setup() {
  git config user.email "apps@dhis2.org"
  git config user.name "dhis2-bot"
  git config hub.protocol https
}

make_branch_pr() {
  local branch=$1
  # local language=$2
  # local code=$3
  local pull_mode=$2

  # checkout the branch
  git checkout $branch

  # If a transifex PR is still open, use that branch
  # otherwise we create a new one later (if there are changes to push)
  open_pr=$(hub pr list --base ${branch} --format %H%n | grep ${branch}-transifex-ALL | head -1) # there shall only be one open at a time
  if [[ $open_pr != "" ]]; then
    # use the existing branch for the PR
    sync_branch=${open_pr}
    git checkout ${sync_branch}
    # rebase to the head of the target branch
    git rebase $branch
  fi

  # Temp - update the tx config mapping and remove any unmapped Uzbek files
  find . -name "*uz@*.p[or]*" -exec rm {} ';'
  sed -i 's/^lang_map.*/lang_map = fa_AF: prs, uz@Cyrl: uz, uz@Latn: uz_Latn/' .tx/config

  # pull all transifex translations for that branch
  # only pull reviewed strings, ignoring resources with less than 10% translated
  echo "tx pull --all --branch $branch --force --skip --minimum-perc=1 --mode $pull_mode"
  tx pull --all --branch $branch --force --skip --minimum-perc=1 --mode $pull_mode

  # ensure that the properties files have the correct encoding (escaped utf-8)
  for propfile in $(grep "file_filter.*properties" .tx/config | sed "s/.*= *// ; s/<lang>/*/")
  do
    # set encoding
    iconv -f iso-8859-1 -t utf-8 ${propfile} -o ${propfile}.tmp
    # escape characters
    native2ascii ${propfile}.tmp ${propfile}
    # remove temp file
    rm ${propfile}.tmp
  done

  # IF THERE ARE CHANGES:
  if [[ $(git status --porcelain) ]]; then

    if [[ $open_pr == "" ]]; then
      # we are on the base branch, so create a new branch for the PR
      sync_branch=${branch}-transifex-ALL-${SYNC_DATE}
      git checkout -b ${sync_branch}
    fi

# set -xv
    commit_detail=/tmp/commit_message_$$.md
    echo -e "fix(translations): sync translations from transifex ($branch)\n" >${commit_detail}
    diff_added=$(git diff --stat | tail -1 | awk '{print $4}')
    diff_deleted=$(git diff --stat | tail -1 | awk '{print $6}')
    if [[ "$diff_added" -lt "$diff_deleted" ]]; then
      echo -e "WARNING: This automated sync from transifex removed more lines than it added." >>${commit_detail}
      echo -e "Please check carefully before merging!\n" >>${commit_detail}
    fi

# unset -xv

    # commit back to git
    git add .
    git commit -F ${commit_detail}

    # raise a PR on github (using hub command)
    if [[ $CREATE_PULL_REQUEST == 1 ]]; then
      if [[ $open_pr == "" ]]; then
        git push --set-upstream origin $sync_branch
        # open the new pull request
        sed -i 's/WARNING/> :warning: **WARNING**/' ${commit_detail}
        echo -e "_Subsequent transifex translations will be added to this PR until it is merged._" >>${commit_detail}
        sleep 1
        hub pull-request --base $branch --file ${commit_detail} --labels "translations"
      else
        # need to force push the branch because of the previous rebase
        git push -f origin $sync_branch
      fi
    fi

    rm ${commit_detail}

  fi
}



# --- starting point
tx_init
projects=$(curl -s -L --user api:$TXTOKEN -X GET "$TX_API/projects" | jq '.[].slug')
mkdir temp$$
pushd temp$$

for p in $projects; do
  # Get the name and the git url of the project
  # The git url is stored in the "homepage" attribute of the transifex project
  curl -s -L --user api:$TXTOKEN -X GET "$TX_API/project/${p//\"/}?details" >/tmp/proj$$
  name=$(cat /tmp/proj$$ | jq '.name')
  tags=$(cat /tmp/proj$$ | jq '.tags')
  giturl=$(cat /tmp/proj$$ | jq '.homepage')
  cleanurl=${giturl//\"/}
  # trim the name of the repo from the full git url (everything after $GITHUB_BASE)
  gitslug=${cleanurl:${#GITHUB_BASE}}
  rm /tmp/proj$$

  # Loop through all APP projects
  if [[ $tags == *"$SYNC_FLAG"* ]]; then

    echo "Syncing $name : $giturl : $gitslug"

    tx_pull_mode="developer"
    if [[ $gitslug == "dhis2-android-capture-app" ]]; then
      tx_pull_mode="reviewed"
    fi
    # The supported modes are:
    #   developer: The files downloaded will be compatible with the i18n support of the development framework you’re using. This is the default mode when you run tx pull. Use this mode when you intend to use the file e.g. in production. This mode auto-fills empty translations with the source language text for most of the file formats we support, which is critical in the case of file formats that require all translations to be non-empty.
    #   translator: The files will be suitable for offline translation. Equivalent to the web app's option "Download file to translate" (for_translation).
    #   reviewed: The files will include reviewed strings in the translation language. All other strings will either be empty or in the source language depending on the file format.
    #   onlytranslated: The files will include the translated strings. The untranslated ones will be left empty.
    #   onlyreviewed: The files will only include reviewed strings. The rest of the strings will be returned empty regardless of if they’re translated or not.

    # Get the list of branches translated in this project
    # The branch names are at the beginnig of each resource slug, followed by double hyphen '--'
    # The `2.xx` branches appear as `2-xx` and must be converted back (replace hyphen with period)
    # We only want each branch to be listed once
    branches=$(curl -s -L --user api:$TXTOKEN -X GET "$TX_API/project/${p//\"/}/resources" | jq '.[].slug | split("--")[0] | split("-") | join(".")' | uniq)

    # clone the project repository and go into it
    git clone ${GITHUB_CLONE_BASE}${gitslug}
    pushd "$gitslug"
    git_setup

    # loop over the branches
    for b in $branches; do
      branch=${b//\"/}

      # checkout the branch
      git checkout $branch

      # sync the current source files to transifex, for the current branch
      if [[ $PUSH_TRANSLATION_STRINGS == 1 ]]; then
        echo "pushing to transifex: tx push -source --branch $branch --skip"
        tx push --source --branch $branch --skip
      fi

      echo "Checking ${branch} branch for updated translations..."
      make_branch_pr $branch $tx_pull_mode

    done

    # leave the repo folder
    popd
    # delete the repo clone
    rm -rf "$gitslug"

  fi

done

popd

rm -rf temp$$
