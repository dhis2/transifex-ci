#!/usr/bin/env bash
# Script to exchange translation files between repo and Transifex.
# It relies on $TXTOKEN set as env vars for the given job

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

# set -xv

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



# --- starting point
tx_init
pushd test

tx_pull_mode="developer"
tx migrate
echo "pushing to transifex: tx push -source --skip"
tx push --source --skip
# pull all transifex translations for that branch
# only pull reviewed strings, ignoring resources with less than 10% translated
echo "tx pull --all --force --skip --minimum-perc=1 --mode $tx_pull_mode"
tx pull --all --force --skip --minimum-perc=1 --mode $tx_pull_mode

popd
