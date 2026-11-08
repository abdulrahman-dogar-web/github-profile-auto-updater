# TEST-LOG — GitHub Profile Auto-Updater

Last verified: **2026-11-08 14:21 UTC** · Tester: rebuild run (no token, no
GitHub writes — the script only ever did read-only `GET` requests to the
public GitHub API; the only files written are the two generated READMEs in
this folder).

## 1. Read-only run against the live profile

Command (twice — once `--dry-run`, once via the script's own client to list
repos; both unauthenticated, no `GITHUB_TOKEN`):

```bash
python3 update_profile.py --dry-run
python3 update_profile.py --output PROFILE_README.md
python3 update_profile.py --output example/PROFILE_README.md
```

Result: exit 0. Fetched the live profile `abdulrahman-dogar-web` and
**13 public repos** (one page, `per_page=100`), 0 total stars.

### Live repos at 2026-11-08 14:20 UTC (newest first, from the API)

| Repo | Updated | Language | Fork | Description (API) |
| --- | --- | --- | --- | --- |
| github-profile-auto-updater | 2026-11-08 | Python | No | Auto-update GitHub profile README from live repos |
| parents-expense-tracker | 2026-11-08 | JavaScript | No | Parents expense and bill tracker app with meter photo comparison |
| free-llm-gateway | 2026-11-08 | — | No | Own OpenRouter clone, one unified LLM API key |
| airdrop-hunter | 2026-11-08 | — | No | Fresh free working crypto airdrops tracker |
| url-shortener | 2026-11-08 | — | No | URL shortener with analytics and QR codes |
| linkhub | 2026-11-08 | — | No | Link-in-bio and mini store |
| secretdrop | 2026-11-08 | — | No | Self-destructing secret sharing, one-time links |
| digital-marketplace | 2026-05-28 | TypeScript | No | — (none) |
| cyber-mail-engin | 2026-05-24 | HTML | No | — (none) |
| register | 2026-05-24 | JavaScript | Yes 🍴 | Get your free '{name}.thedev.me' domain |
| abdulrahman-dogar-web | 2026-05-24 | — | No | — (none; the profile repo itself) |
| cyber-mail-engine | 2026-05-22 | HTML | No | — (none) |
| github_badges | 2026-03-13 | — | No | — (none) |

Cross-checked against `GET /users/abdulrahman-dogar-web/repos` (same names,
same `updated_at` values, same descriptions for the first three entries
shown). Followers 0, following 0, on GitHub since 2025-09-14, hireable
("Open to work") — all match the generated README.

### What the generated README contains (2026-11-08 14:21 UTC)

- Badges: Followers **0**, Repos **13**, Stars **0**.
- About: **0** total stars across **13** public repositories; **0**
  followers · **0** following.
- Languages: JavaScript ×2 (33%), HTML ×2 (33%), Python ×1 (17%),
  TypeScript ×1 (17%) — counted from the 6 repos with a detected language.
- Latest Projects table (6 = `max_repos` limit), newest first:
  `github-profile-auto-updater`, `parents-expense-tracker`,
  `free-llm-gateway`, `airdrop-hunter`, `url-shortener`, `linkhub`.
  The 7th newest (`secretdrop`) is correctly cut off by `max_repos: 6`.
- `PROFILE_README.md` and `example/PROFILE_README.md` are byte-identical
  (same run, same timestamp 2026-11-08 14:21 UTC).

### Finding: the committed README was stale before this run

The `PROFILE_README.md` in the repo before this rebuild was generated
2026-11-08 13:11 UTC and said **6 repos** — the 7 new repos above were
all created/pushed between 13:48 and 14:12 UTC, after that generation.
The regenerated files now say 13 and match the live profile. This is
exactly what the weekly GitHub Action is for; nothing was wrong with the
script, the file was simply generated before the repos existed.

## 2. Checks that passed

| Check | Result |
| --- | --- |
| `python3 -m py_compile update_profile.py` | PASS |
| `python3 update_profile.py --dry-run` (exit 0, stdout = fresh README) | PASS |
| Generated README matches live API data (names, counts, dates, languages) | PASS — see table above |
| Workflow YAML parses (`yaml.safe_load`) | PASS |
| Workflow triggers: `schedule` Mon 00:00 UTC, `push` (main, 3 paths), `workflow_dispatch` | PASS |
| Workflow uses automatic `secrets.GITHUB_TOKEN` only — no extra secrets | PASS |
| Workflow commits the generated files back (`git push`, `[skip ci]`, only if changed) | PASS (read, not executed) |
| Workflow `permissions: contents: write` present | PASS |
| Pagination: all 13 repos returned on one page (`per_page=100`); loop breaks correctly on a short page | PASS (code read + live single-page result) |
| Retry behaviour observed live | The first profile `GET` hit the shared-IP unauthenticated rate limit (403) and the script retried after 2 s and succeeded; the same happened on the repo-listing call. Retry + back-off works as designed. |

## 3. Bug fixed in this rebuild

**Shallow copy of defaults could mutate module state (`update_profile.py`,
`load_config`).** When `config.json` was missing, `load_config` returned
`dict(DEFAULTS)` — a shallow copy — so the nested `social`/`sections`
dicts were still the module-level ones, and `--username` (which rewrites
`config["social"]["github"]`) would have mutated `DEFAULTS` for the rest
of the process. The file-loaded path had the same exposure for any key
absent from the user's config. Fixed by `copy.deepcopy` on both paths.
No behaviour change for the shipped `config.json`; verified by
`py_compile` + the regeneration runs above.

No other bugs found: API field names (`login`, `public_repos`,
`followers`, `stargazers_count`, `forks_count`, `updated_at`, `language`,
`fork`, `archived`, `html_url`, `description`) all match the live API
responses; `format_date` handles the `…Z` timestamps GitHub returns;
missing descriptions render as `—`; the profile repo is excluded by name.

## 4. Not tested here (needs the parent / GitHub)

- The GitHub Action itself has not run on GitHub yet — it runs on push /
  schedule / manual dispatch after the repo is pushed. Its YAML was
  validated and its steps read, but the Actions run is still to be
  observed once (see `DEPLOY.md` — run it once manually from the Actions
  tab).
- Copying `PROFILE_README.md` into the `abdulrahman-dogar-web` profile
  repo as `README.md` is a manual owner step, not done here.

© 2026 Mr. Abdul Rahman Dogar
