#!/usr/bin/env bash
# Script to exchange translation files between repo and Transifex via Jenkins.
# It relies on $TXTOKEN and $GHTOKEN being set as env vars for the given job

# set up the python environment
if [ ! -d "venv" ]; then
    source setup_venv
fi
source ./venv/bin/activate

for exe in "git" "hub" "tx" "jq"; do
  if [[ ! $(command -v $exe) ]]; then
    echo "This script requires $exe. Exiting"
    exit 1
  fi
done

# set -xv


GITHUB_BASE="https://dhis2-bot:${GHTOKEN}@github.com/dhis2/"
LANG_FILE=${PWD}/$(dirname ${0})/transifex_languages.json
SYNC_DATE=$(date +"%Y%m%d_%H%M%S")
TX_API=https://www.transifex.com/api/2
SYNC_FLAG="jenkins-app-sync"

# --- options
PUSH_TRANSLATION_STRINGS=0
CREATE_PULL_REQUEST=1


# --- functions
tx_init() {
  echo "[https://www.transifex.com]
api_hostname = https://api.transifex.com
hostname = https://www.transifex.com
username = api
password = $TXTOKEN" > ~/.transifexrc
}

git_setup() {
  git config user.email "apps@dhis2.org"
  git config user.name "dhis2-bot"
}

make_branch_pr() {
  local branch=$1
  local language=$2
  local code=$3

  # checkout the branch
  git checkout $branch

  # If a transifex PR is still open, use that branch
  # otherwise we create a new one later (if there are changes to push)
  open_pr=$(hub pr list -b ${branch} -f %H%n | grep ${branch}-transifex-${code} | head -1) # there should only be one open at a time
  if [[ $open_pr != "" ]]; then
    # use the existing branch for the PR
    sync_branch=${open_pr}
    git checkout ${sync_branch}
  fi

  # pull all transifex translations for that branch
  # only pull reviewed strings, ignoring resources with less than 10% translated
  echo "tx pull -l $code -b $branch -f --skip --minimum-perc=20 # --mode reviewed"
  tx pull -l $code -b $branch -f --skip --minimum-perc=20 # --mode reviewed

  # IF THERE ARE CHANGES:
  if [[ $(git status --porcelain) ]]; then

    if [[ $open_pr == "" ]]; then
      # we are on the base branch, so create a new branch for the PR
      sync_branch=${branch}-transifex-${code}-${SYNC_DATE}
      git checkout -b ${sync_branch}
    fi

    commit_detail=/tmp/commit_message_$$.md
    echo -e "chore(translations): sync ${language} translations from transifex ($branch)\n" >${commit_detail}
    diff_added=$(git diff --numstat | awk '{print $1}')
    diff_deleted=$(git diff --numstat | awk '{print $2}')
    if [[ diff_added -lt diff_deleted ]]; then
      echo -e "WARNING: This automated sync from transifex removed more lines than it added." >>${commit_detail}
      echo -e "Please check carefully before merging!\n" >>${commit_detail}
    fi

    # commit back to git
    git add .
    git commit -F ${commit_detail}

    # raise a PR on github (using hub command)
    if [[ $CREATE_PULL_REQUEST == 1 ]]; then
      git push -u origin $sync_branch
      if [[ $open_pr == "" ]]; then
        # open the new pull request
        sed -i 's/WARNING/> :warning: **WARNING**/' ${commit_detail}
        echo -e "_Subsequent transifex translations will be added to this PR until it is merged._" >>${commit_detail}
        hub pull-request -b $branch -F ${commit_detail}
      fi
    fi

    rm ${commit_detail}

  fi
}



# --- starting point
tx_init
projects=$(curl -s -L --user api:$TXTOKEN -X GET "$TX_API/projects" | jq '.[].slug')

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

    echo "Syncing $name : $giturl"

    # Get the list of branches translated in this project
    # The branch names are at the beginnig of each resource slug, followed by double hyphen '--'
    # The `2.xx` branches appear as `2-xx` and must be converted back (replace hyphen with period)
    # We only want each branch to be listed once
    branches=$(curl -s -L --user api:$TOKEN -X GET "$TX_API/project/${p//\"/}/resources" | jq '.[].slug | split("--")[0] | split("-") | join(".")' | uniq)

    # clone the project repository and go into it
    git clone ${GITHUB_BASE}${gitslug}
    pushd "$gitslug"
    git_setup

    # loop over the branches
    for b in $branches; do
      branch=${b//\"/}

      # checkout the branch
      git checkout $branch

      # sync the current source files to transifex, for the current branch
      if [[ $PUSH_TRANSLATION_STRINGS == 1 ]]; then
        echo "tx push"
        #      tx push -s -b -f --skip
      fi

      for lang_code in $(cat ${LANG_FILE} | jq 'keys | .[]'); do
        lang=$(cat ${LANG_FILE} | jq ".$lang_code")
        language=${lang//[\" ()]/}
        code=${lang_code//\"/}
        echo "Checking ${branch} branch for changes to ${language} language..."

        make_branch_pr $branch $language $code
      done

    done

    # leave the repo folder
    popd

  fi

done
