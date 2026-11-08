# Deploying / hosting

This project is a script, not a website, so there is no site to host.
"Deploying" it means: push it to GitHub once, and the included workflow
keeps the generated README fresh automatically.

## One-time setup (owner does this once)

1. **Push this folder to GitHub** as a public repository named
   `github-profile-auto-updater`, on the default branch (`main`).
   The workflow file must be on that branch:
   `.github/workflows/update-profile.yml`.
2. **No secrets to create. No settings to change.** The workflow uses the
   automatic `GITHUB_TOKEN` GitHub provides to every workflow run
   (`secrets.GITHUB_TOKEN` in the YAML) — it is enough for public data
   (5,000 API requests/hour) and for committing the result back.
   The workflow also declares `permissions: contents: write`, so it can
   push even on repositories whose default workflow permissions are
   read-only. Never put a personal access token in the repo or the workflow.
   - *Only if the workflow ever fails with a 403 on `git push`* (an
     organisation can force read-only tokens): go to the repo's
     **Settings → Actions → General → Workflow permissions** and select
     **"Read and write permissions"**, then re-run the workflow.
3. **Verify with a manual run:** open the repo's **Actions** tab →
   **Update Profile README** → **Run workflow** → **Run workflow**.
   After it finishes (about a minute), check that `PROFILE_README.md`
   was committed (or that the run reports "No changes"). If the run is
   green, the schedule below will keep working on its own.

## What happens on each run

The workflow (`.github/workflows/update-profile.yml`) runs:

- **Every Monday at 00:00 UTC** (`cron: "0 0 * * 1"`),
- **On every push to `main`** that touches `update_profile.py`,
  `config.json`, or the workflow file itself,
- **On demand** from Actions → Update Profile README → Run workflow.

Each run:

1. Checks out the repo and sets up Python 3.12.
2. Installs `requirements.txt` (`requests` — optional; the script falls
   back to the standard library if it is absent).
3. Runs the script twice with the automatic token — once for
   `PROFILE_README.md`, once for `example/PROFILE_README.md` — fetching
   the live profile and all public repositories from the GitHub API.
4. Commits and pushes the two files **only if they changed**, with the
   message `chore: auto-update profile README [skip ci]`. The
   `[skip ci]` flag means that commit never triggers the workflow again,
   so it cannot loop on itself. If nothing changed, the run reports
   "No changes — profile README is already up to date." and pushes nothing.

## Run it locally

```bash
pip install -r requirements.txt   # optional — stdlib-only fallback exists
python3 update_profile.py         # writes PROFILE_README.md
python3 update_profile.py --dry-run   # read-only: prints, writes nothing
```

No token is needed for public data (60 requests/hour unauthenticated;
the script retries on 429/5xx). Set `GITHUB_TOKEN` in the environment
for 5,000 requests/hour if you run it often. The token is never written
to a file or printed in logs.

## Use the output as your live GitHub profile README

GitHub shows the README of a repository named exactly like your username
on your profile page. To use this output there:

1. Open (or create) the public repository named exactly
   `abdulrahman-dogar-web` (your username).
2. Copy the generated `PROFILE_README.md` into it as `README.md`
   (rename it — GitHub only renders a file called `README.md`).
3. Commit and push. Your profile page at
   `github.com/abdulrahman-dogar-web` shows it immediately.
4. To keep it fresh, re-run the script and copy the file again — or add
   the workflow above to the profile repo as well and point its output at
   `README.md` (change `--output PROFILE_README.md` to
   `--output README.md` in the workflow).

## Test log

See [`TEST-LOG.md`](TEST-LOG.md) for the last verified run against the
live profile (2026-11-08): what was fetched, what the generated README
contains, and the checks that passed.
