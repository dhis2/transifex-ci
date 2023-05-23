#!/usr/bin/env bash
# Script to merge translation Pull Reqests in Github via Jenkins.
# It relies on $TXTOKEN, $GITHUB_USER and $GITHUB_PASSWORD being set as env vars for the given job


# Ensure required tools are available
for exe in "git" "hub" "jq"; do
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
MERGE_FLAG="jenkins-pr-automerge"

# --- options : set the following to `0` to test without pushing anything to remote systems
PUSH_TRANSLATION_STRINGS=1
CREATE_PULL_REQUEST=1


# --- functions
git_setup() {
  git config user.email "apps@dhis2.org"
  git config user.name "dhis2-bot"
  git config hub.protocol https
}

auto_varl () {
    local BASE="$1"
    declare -a array
    readarray -t array < <(hub pr list --base="$BASE" --format='%I|%t|%sH%n')

    for PR in "${array[@]}"; do
        local pr_id="$(echo $PR | cut -d "|" -f 1)"
        local pr_title="$(echo $PR | cut -d "|" -f 2)"
        local scope="$(echo $pr_title | cut -d ":" -f 1)"
        local pr_commit="$(echo $PR | cut -d "|" -f 3)"
        local body="/tmp/${pr_id}-body.json"

        if [ "fix(translations)" == "$scope" ]; then
            pr_url=$(hub pr show "$pr_id" --url)
            echo "Transifex PR: ${pr_id} ${pr_title}"
            echo "${pr_url}"
            cat << EOF > "$body"
{
  "commit_title": "${pr_title}",
  "commit_message": "Automatically merged.",
  "merge_method": "squash"
}
EOF
            local ci_status="$(hub ci-status ${pr_commit})"
            echo "CI status of PR: ${ci_status}"
            # explicitly check if the CI status of the PR is successful
            if [[ "${ci_status}" == "success" ]]
            then
                res=$(hub api --method PUT "repos/{owner}/{repo}/pulls/${pr_id}/merge" --input "$body")
                echo "Merge PR. Result: $res"
            fi
            # if the CI status is a failure, close the PR (A new one will be opened with changes during the next sync)
            if [[ "${ci_status}" == "failure" ]]
            then
                res=$(hub pr close ${pr_id})
                echo "Close failed PR. Result: $res"
            fi
            # if the CI status is open, check if the version is deprecated, and close if it is
            if [[ "${ci_status}" == "open" ]]
            then
              deprecated_versions=("v29" "v30" "v31" "v32" "v33" "v34")
              deprecated=false

              for value in "${deprecated_versions[@]}"; do
                  if [[ ${pr_title} == *"${value}"* ]]; then
                      deprecated=true
                      break
                  fi
              done

              if $deprecated
              then
                  res=$(hub pr close ${pr_id})
                  echo "Close deprecated PR. Result: $res"
              fi


            rm "$body"
            sleep 1
        fi
    done
}

# --- starting point
projects=$(curl -s -X GET "$TX_API3/projects?filter[organization]=o:hisp-uio" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.data[].attributes.slug')
mkdir temp$$
pushd temp$$

for p in $projects; do
  # Get the name and the git url of the project
  # The git url is stored in the "homepage" attribute of the transifex project
  curl -s -X GET "$TX_API3/projects/o:hisp-uio:p:${p//\"/}" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.[].attributes' >/tmp/proj$$
  name=$(cat /tmp/proj$$ | jq '.name')
  tags=$(cat /tmp/proj$$ | jq '.tags | join(",")')
  giturl=$(cat /tmp/proj$$ | jq '.homepage_url')
  cleanurl=${giturl//\"/}
  # trim the name of the repo from the full git url (everything after $GITHUB_BASE)
  gitslug=${cleanurl:${#GITHUB_BASE}}
  rm /tmp/proj$$

  # Loop through all APP projects
  if [[ $tags == *"$MERGE_FLAG"* ]]; then

    echo "Attempting to merge translation PRs for $name : $giturl : $gitslug"

    # Get the list of branches translated in this project
    # The branch names are at the beginnig of each resource slug, followed by double hyphen '--'
    # The `2.xx` branches appear as `2-xx` and must be converted back (replace hyphen with period)
    # We only want each branch to be listed once
    branches=$(curl -s -X GET "$TX_API3/resources?filter[project]=o:hisp-uio:p:${p//\"/}" -H "Content: application/json" -H "Authorization: Bearer $TXTOKEN" | jq '.data[].attributes.slug | split("--")[0] | split("-") | join(".")' | uniq)
    # echo "Branches: $branches"

    # clone the project repository and go into it
    git clone --depth 1 --no-single-branch ${GITHUB_CLONE_BASE}${gitslug}
    pushd "$gitslug"
    git_setup

    # loop over the branches
    for b in $branches; do
      branch=${b//\"/}

      echo "Checking ${branch} branch for translation PRs..."
      auto_varl $branch

    done
    
    # delete all transifex branches except for unmerged PRs
    echo "Clean up merged transifex-ALL branches..."
    hub pr list --format='%H%n' > OPEN_PRS
    for g in $(git branch -r | grep 'transifex-ALL' | sed 's/origin\///')
    do 
      if grep -q "$g" OPEN_PRS
      then
        echo "  Skipping open PR: $g"
      else
        git push -d origin $g
      fi
    done
    rm -f OPEN_PRS
    echo "Cleaned."

    # leave the repo folder
    popd

  fi

done

popd

rm -rf temp$$
