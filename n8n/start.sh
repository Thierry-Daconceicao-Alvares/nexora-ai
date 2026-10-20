#!/bin/sh
# Starts n8n with the NEXORA workflows: imports the SMTP credential and the
# four workflows from this folder, publishes them, then starts n8n. Run at
# every start, so the workflows always match the repository; a change made in
# the n8n editor is kept until the next start, export it to keep it.
set -e
n8n import:credentials --input=/nexora/credentials.json
for file in /nexora/workflows/*.json; do
  n8n import:workflow --input="$file"
  id=$(node -e "console.log(require(process.argv[1]).id)" "$file")
  n8n publish:workflow --id="$id"
done
exec n8n start
