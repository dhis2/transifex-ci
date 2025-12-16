#!/usr/bin/env bash
# Script to exchange translation files between repo and Transifex via Jenkins.
# It relies on $TXTOKEN and $GHTOKEN being set as env vars for the given job

# set path to pick up tx
export PATH="$PWD:$PATH"

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
TX_API3=https://rest.api.transifex.com

# Check if the environment variable is set for sync flag
if [ -n "$TRANSIFEX_SYNC_TAG" ]; then
    # Use the value of the environment variable
    SYNC_FLAG="$TRANSIFEX_SYNC_TAG"
else
    # Use the default value
    SYNC_FLAG="jenkins-app-sync"
fi

# --- options : set the following to `0` to test without pushing anything to remote systems
PUSH_TRANSLATION_STRINGS=1
CREATE_PULL_REQUEST=1

# --- ignore older version branches until we clean them up
IGNORE_BRANCHES="v29 2.29 v30 2.30 v31 2.31 v32 32.x 2.32 v33 33.x 2.33 v34 34.x 2.34 v35 35.x 2.35"

# --- functions
tx_init() {

  if [[ ! -f ~/.transifexrc ]]; then

    echo "[https://www.transifex.com]
api_hostname = https://api.transifex.com
hostname = https://www.transifex.com
username = api
password = $TXTOKEN" > ~/.transifexrc

  fi

}

tx_fix() {

  txconf=".tx/config"

  # temporarily migrate configuration to the new format.
  tx migrate
  rm .tx/config*.bak

  if [[ $(git config --get remote.origin.url) != *"android"* ]]; then
    
    # Temp - update the tx config mapping and remove any unmapped Uzbek files
    # find . -name "*uz.po" -exec rm {} ';'
    # find . -name "*_uz.properties" -exec rm {} ';'
    # find . -name "*_uz_Cyrl.properties" -exec rm {} ';'
    # find . -name "*_uz_Latn.properties" -exec rm {} ';'
    # sed -i 's/^lang_map.*/lang_map = fa_AF: prs, uz@Cyrl: uz_UZ_Cyrl, uz@Latn: uz_UZ_Latn/' $txconf

    # remove any invalid resources
    for f in $(cat $txconf | grep source_file | awk {'print $3'}); do
      if [[ ! -f $f ]]; then

        tmpfile=$(mktemp)
        echo "Translation source $f not found. Removing record from transifex config!"
        new=""
        while read line; do
          if [[ ${line::1} == "[" ]];then
            if [[ ! $new =~ "$f" ]];then
              if [[ $new != "" ]];then
                echo -e $new >> $tmpfile
              fi
            fi
            new=""
          fi
          new+="$line\n"
        done <$txconf
        if [[ ! $new =~ "$f" ]];then
          if [[ $new != "" ]];then
            echo -e $new >> $tmpfile
          fi
        fi
        cp "$tmpfile" $txconf

        rm "$tmpfile"
      fi
    done

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

  # # Temp - update the tx config mapping and remove any unmapped Uzbek files
  # # temporarily migrate configuration to the new format.
  # tx_fix

  # pull all transifex translations for that branch
  # only pull reviewed strings, ignoring resources with less than 10% translated
  echo "tx pull --all --branch $branch --use-git-timestamps --skip --minimum-perc=1 --mode $pull_mode --workers 4"
  tx pull --all --branch $branch --use-git-timestamps --skip --minimum-perc=1 --mode $pull_mode --workers 4

  # ensure that the properties files have the correct encoding (escaped utf-8)
  for propfile in $(grep "file_filter.*properties" .tx/config | sed "s/.*= *// ; s/<lang>/*/"); do
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
projects=$(curl -s -X GET "$TX_API3/projects?filter%5Borganization%5D=o%3Ahisp-uio" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.data[].attributes.slug')
mkdir temp$$
pushd temp$$

for p in $projects; do
  # Get the name and the git url of the project
  # The git url is stored in the "homepage" attribute of the transifex project
  curl -s -X GET "$TX_API3/projects/o%3Ahisp-uio%3Ap%3A${p//\"/}" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.[].attributes' >/tmp/proj$$
  name=$(cat /tmp/proj$$ | jq '.name')
  tags=$(cat /tmp/proj$$ | jq '.tags | join(",")')
  giturl=$(cat /tmp/proj$$ | jq '.homepage_url')
  cleanurl=${giturl//\"/}
  # trim the name of the repo from the full git url (everything after $GITHUB_BASE)
  gitslug=${cleanurl:${#GITHUB_BASE}}
  rm /tmp/proj$$
  
  # Debug output to show project details
  echo "Checking project: $name"
  echo "    Tags: $tags"
  echo "    SYNC_FLAG: ${SYNC_FLAG}"

  # Loop through all APP projects
  if [[ $tags == *"${SYNC_FLAG}"* ]]; then

    echo "Syncing $name : $giturl : $gitslug"

    tx_pull_mode="default"
    #if [[ $gitslug == "dhis2-android-capture-app" ]]; then
    #  tx_pull_mode="reviewed"
    #fi
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
    branches=$(curl -s -X GET "$TX_API3/resources?filter%5Bproject%5D=o%3Ahisp-uio%3Ap%3A${p//\"/}" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.data[].attributes.slug | split("--")[0] | split("-") | join(".")' | uniq)
    #temporarily add new release branches
    #branches+=("2.40")
    # echo "Branches: $branches"

    # clone the project repository and go into it
    git clone ${GITHUB_CLONE_BASE}${gitslug}
    pushd "$gitslug"
    git_setup

    #temporarily add new release branches (left for reference, but this is buggy and results in the branch list appending for each project!)
    # branches=( ${branches[@]} "38.x" "v38" )

    # loop over the branches
    for b in ${branches[@]}; do
      branch=${b//\"/}
      # check if branch is in the list of branches to ignore
      if [[ " ${IGNORE_BRANCHES[@]} " =~ " ${branch} " ]]; then
          echo "Ignoring deprecated branch: $branch"
          continue
      fi

      # checkout the branch
      git checkout $branch
      status=$?

      if [[ $status == 0 ]]; then

        # fix issues with tx config
        tx_fix

        # sync the current source files to transifex, for the current branch
        if [[ $PUSH_TRANSLATION_STRINGS == 1 ]]; then
          echo "pushing to transifex: tx push -source --branch $branch --skip"
          tx push --source --branch $branch --use-git-timestamps --skip
        fi

        # undo any changes caused by the migration on this branch
        git stash

        echo "Checking ${branch} branch for updated translations..."
        make_branch_pr $branch $tx_pull_mode
      fi

    done

    # leave the repo folder
    popd
    # delete the repo clone
    rm -rf "$gitslug"

  fi

done

popd

rm -rf temp$$
