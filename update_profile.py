#!/usr/bin/env python3
"""
GitHub Profile Auto-Updater
============================

Regenerates a GitHub profile README (``PROFILE_README.md``) from a user's
live public repository data, fetched from the GitHub REST API.

What it does
------------
1. Fetches the user's public profile (name, bio, location, follower count,
   account creation date) from ``https://api.github.com/users/<username>``.
2. Fetches every public repository (paginated, newest first), sorts them by
   ``updated_at`` descending, and applies the exclusions in ``config.json``.
3. Renders a complete profile README from a template: header, live
   shields.io badges, GitHub Readme Stats cards, a language breakdown, a
   table of the latest projects, social links, and a "last updated"
   timestamp. Nothing in the output is invented -- every number comes from
   the API response received in this run.
4. Writes the result to ``PROFILE_README.md`` (or the path given with
   ``--output``). Re-running the script after adding a repository updates
   the table automatically.

Authentication
--------------
No token is needed for public data. If the ``GITHUB_TOKEN`` environment
variable is set, it is sent as a Bearer token and raises the rate limit
from 60 requests/hour (unauthenticated) to 5,000/hour. The token is never
written to any file, never printed, and never hard-coded here.

Dependencies
------------
Standard library only. ``requests`` is used when installed (it gives
cleaner retry / timeout handling); if it is absent the script falls back
to ``urllib`` automatically, so ``pip install -r requirements.txt`` is
optional, not required.

Usage
-----
    python3 update_profile.py                      # config.json -> PROFILE_README.md
    python3 update_profile.py --output example/PROFILE_README.md
    python3 update_profile.py --username octocat --max-repos 8
    python3 update_profile.py --config my-config.json --dry-run
    GITHUB_TOKEN=ghp_... python3 update_profile.py

Exit codes: 0 = success, 1 = usage/config error, 2 = GitHub API error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Optional: nicer HTTP client when available, stdlib fallback otherwise.
    import requests  # type: ignore

    HAVE_REQUESTS = True
except ImportError:  # pragma: no cover - exercised on stdlib-only systems.
    requests = None  # type: ignore
    HAVE_REQUESTS = False

import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
DEFAULT_CONFIG = "config.json"
DEFAULT_OUTPUT = "PROFILE_README.md"
USER_AGENT = "github-profile-auto-updater/1.0 (+https://github.com/abdulrahman-dogar-web)"
MAX_RETRIES = 4
TIMEOUT_SECONDS = 30

# GitHub's official language colours (subset -- the languages this profile
# actually uses, plus the most common ones; unknown languages fall back
# to a neutral grey dot). Source: github/linguist `languages.yml`.
LANGUAGE_COLOURS = {
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Java": "#b07219",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Shell": "#89e051",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Dart": "#00B4AB",
    "Vue": "#41b883",
    "SCSS": "#c6538c",
    "Jupyter Notebook": "#DA5B0B",
}

DEFAULTS: dict[str, Any] = {
    "username": "abdulrahman-dogar-web",
    "display_name": "Mr. Abdul Rahman Dogar",
    "bio": "Jack of All Trades ♠ — Master of none, but often better than the master of ONE ⚜️",
    "tagline": "Building in public — one project at a time.",
    "location": "Pakistan",
    "website": "",
    "max_repos": 6,
    "exclude_forks": False,
    "exclude_profile_repo": True,
    "exclude_archived": True,
    "stats_theme": "tokyonight",
    "show_streak": True,
    "social": {
        "github": "https://github.com/abdulrahman-dogar-web",
        "twitter": "",
        "instagram": "",
        "linkedin": "",
        "youtube": "",
        "website": "",
    },
    "sections": {
        "header": True,
        "badges": True,
        "about": True,
        "stats": True,
        "languages": True,
        "latest_projects": True,
        "social": True,
        "footer": True,
    },
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Print a timestamped progress line to stderr (keeps stdout clean)."""
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp} UTC] {message}", file=sys.stderr)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* (nested dicts merge, not replace)."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str) -> dict[str, Any]:
    """Load ``config.json`` and merge it over the built-in defaults."""
    config_path = Path(path)
    if not config_path.exists():
        log(f"Config file '{path}' not found -- using built-in defaults.")
        return dict(DEFAULTS)
    try:
        with config_path.open(encoding="utf-8") as handle:
            user_config = json.load(handle)
    except json.JSONDecodeError as exc:
        print(f"Error: '{path}' is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(user_config, dict):
        print(f"Error: '{path}' must contain a JSON object.", file=sys.stderr)
        sys.exit(1)
    config = deep_merge(DEFAULTS, user_config)
    if not config.get("username"):
        print("Error: 'username' must be set in the config file.", file=sys.stderr)
        sys.exit(1)
    return config


def escape_markdown(text: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def truncate(text: str, limit: int = 100) -> str:
    """Shorten *text* to *limit* characters, keeping whole words where possible."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip() + "…"


def format_date(iso_date: str) -> str:
    """'2026-05-28T12:29:19Z' -> '2026-05-28'. Returns the raw value if unparsable."""
    try:
        return datetime.strptime(iso_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_date or "—"


def language_dot(language: str | None) -> str:
    """A coloured-dot HTML span for a language, e.g. ``<span ...>●</span> TypeScript``."""
    if not language:
        return "—"
    colour = LANGUAGE_COLOURS.get(language, "#8b949e")
    return f'<span style="color:{colour}">●</span> {escape_markdown(language)}'


# ---------------------------------------------------------------------------
# GitHub API client (requests when available, urllib otherwise)
# ---------------------------------------------------------------------------

class GitHubError(Exception):
    """Raised when the GitHub API cannot be used (network, auth, rate limit)."""


class GitHubClient:
    """Minimal read-only GitHub REST client with retries and rate-limit handling."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN") or None
        if self.token:
            log("Using GITHUB_TOKEN from the environment (higher rate limit).")
        else:
            log("No GITHUB_TOKEN set -- using the unauthenticated limit (60 req/hour).")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_json(self, url: str) -> Any:
        """GET *url*, retrying on 429 / 5xx, and return the parsed JSON body."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if HAVE_REQUESTS:
                    return self._get_with_requests(url)
                return self._get_with_urllib(url)
            except GitHubError as exc:
                last_error = exc
                # _get_* raises GitHubError only for non-retryable statuses;
                # retryable ones raise _RetryableError (a GitHubError subclass
                # handled below) -- re-raise immediately for the rest.
                if not isinstance(exc, _RetryableError):
                    raise
                wait = 2 ** attempt
                log(f"Attempt {attempt}/{MAX_RETRIES} failed ({exc}); retrying in {wait}s…")
                time.sleep(wait)
        raise GitHubError(f"GitHub API request failed after {MAX_RETRIES} attempts: {last_error}")

    def _raise_for_status(self, status: int, body: bytes, url: str) -> None:
        if status == 404:
            raise GitHubError(f"Not found (404) for {url} -- check the username / repo name.")
        if status == 401:
            raise GitHubError("Unauthorized (401) -- the GITHUB_TOKEN is invalid or expired.")
        if status == 403:
            try:
                detail = json.loads(body).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            if "rate limit" in detail.lower():
                raise _RetryableError(f"Rate limit exceeded (403): {detail}")
            raise GitHubError(f"Forbidden (403) for {url}: {detail or 'access denied'}")
        if status == 429 or 500 <= status < 600:
            raise _RetryableError(f"GitHub returned HTTP {status} for {url}")
        if status != 200:
            raise GitHubError(f"GitHub returned HTTP {status} for {url}")

    def _get_with_requests(self, url: str) -> Any:
        assert requests is not None
        try:
            response = requests.get(url, headers=self._headers(), timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise _RetryableError(f"Network error talking to GitHub: {exc}") from exc
        self._raise_for_status(response.status_code, response.content, url)
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError(f"GitHub returned invalid JSON for {url}") from exc

    def _get_with_urllib(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read()
                self._raise_for_status(response.status, body, url)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            self._raise_for_status(exc.code, body, url)
            raise GitHubError(f"GitHub returned HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise _RetryableError(f"Network error talking to GitHub: {exc}") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise GitHubError(f"GitHub returned invalid JSON for {url}") from exc

    def get_user(self, username: str) -> dict[str, Any]:
        """Fetch one user's public profile."""
        log(f"Fetching profile for @{username}…")
        user = self.get_json(f"{API_BASE}/users/{urllib.parse.quote(username)}")
        if not isinstance(user, dict) or "login" not in user:
            raise GitHubError(f"Unexpected profile response for @{username}.")
        return user

    def get_repos(self, username: str) -> list[dict[str, Any]]:
        """Fetch *all* public repos for a user, following pagination."""
        log(f"Fetching public repositories for @{username}…")
        repos: list[dict[str, Any]] = []
        page = 1
        while True:
            url = (
                f"{API_BASE}/users/{urllib.parse.quote(username)}/repos"
                f"?per_page=100&page={page}&sort=updated&direction=desc"
            )
            batch = self.get_json(url)
            if not isinstance(batch, list):
                raise GitHubError(f"Unexpected repository response for @{username}.")
            repos.extend(batch)
            log(f"  Page {page}: {len(batch)} repos (total so far: {len(repos)})")
            if len(batch) < 100:
                break
            page += 1
        return repos


class _RetryableError(GitHubError):
    """A transient failure (network blip, 429, 5xx) worth retrying."""


# ---------------------------------------------------------------------------
# Repository filtering / statistics
# ---------------------------------------------------------------------------

def filter_repos(repos: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the config exclusions, then sort newest-first and cap the count."""
    username = str(config["username"]).lower()
    kept: list[dict[str, Any]] = []
    for repo in repos:
        if config.get("exclude_forks") and repo.get("fork"):
            continue
        if config.get("exclude_archived") and repo.get("archived"):
            continue
        if config.get("exclude_profile_repo") and repo.get("name", "").lower() == username:
            continue
        kept.append(repo)
    kept.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return kept[: int(config.get("max_repos", 6))]


def repo_stats(repos: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals and language breakdown computed from the fetched repos."""
    total_stars = sum(int(r.get("stargazers_count") or 0) for r in repos)
    total_forks = sum(int(r.get("forks_count") or 0) for r in repos)
    languages = Counter(r.get("language") for r in repos if r.get("language"))
    return {
        "total_stars": total_stars,
        "total_forks": total_forks,
        "languages": languages,
    }


# ---------------------------------------------------------------------------
# README rendering
# ---------------------------------------------------------------------------

def build_badge_url(label: str, message: str, colour: str, logo: str = "") -> str:
    """One shields.io static badge URL (all values URL-encoded)."""
    base = "https://img.shields.io/badge"
    label_enc = urllib.parse.quote(label, safe="")
    message_enc = urllib.parse.quote(message, safe="")
    url = f"{base}/{label_enc}-{message_enc}-{colour}?style=for-the-badge"
    if logo:
        url += f"&logo={urllib.parse.quote(logo, safe='')}"
    return url


def render_readme(
    user: dict[str, Any],
    all_repos: list[dict[str, Any]],
    shown_repos: list[dict[str, Any]],
    config: dict[str, Any],
    generated_at: datetime,
) -> str:
    """Render the full profile README Markdown from live API data + config."""
    username = str(config["username"])
    display_name = str(config.get("display_name") or user.get("name") or username)
    # Prefer the bio from GitHub when the config bio is empty, and vice versa.
    bio = str(config.get("bio") or user.get("bio") or "").replace("\r", " ").strip()
    tagline = str(config.get("tagline") or "")
    location = str(config.get("location") or user.get("location") or "")
    theme = str(config.get("stats_theme") or "tokyonight")
    social = config.get("social") or {}
    sections = config.get("sections") or {}
    stats = repo_stats(all_repos)
    followers = int(user.get("followers") or 0)
    following = int(user.get("following") or 0)
    public_repos = int(user.get("public_repos") or len(all_repos))
    created = format_date(str(user.get("created_at") or ""))
    timestamp = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    encoded_user = urllib.parse.quote(username, safe="")

    lines: list[str] = []

    # -- Header -------------------------------------------------------------
    if sections.get("header", True):
        lines.append(f"# Hi there, I'm {display_name} 👋")
        lines.append("")
        if bio:
            lines.append(f"> {escape_markdown(bio)}")
            lines.append("")
        if tagline:
            lines.append(f"*{escape_markdown(tagline)}*")
            lines.append("")
        meta_bits = []
        if location:
            meta_bits.append(f"📍 {escape_markdown(location)}")
        if created and created != "—":
            meta_bits.append(f"🗓️ On GitHub since {created}")
        if user.get("hireable"):
            meta_bits.append("💼 Open to work")
        if meta_bits:
            lines.append(" | ".join(meta_bits))
            lines.append("")

    # -- Badges (all live: shields.io computes them when the README loads) --
    if sections.get("badges", True):
        badges = [
            f"[![GitHub followers]({build_badge_url('Followers', str(followers), '181717', 'github')})]"
            f"(https://github.com/{encoded_user}?tab=followers)",
            f"[![Public repos]({build_badge_url('Repos', str(public_repos), '2ea44f', 'github')})]"
            f"(https://github.com/{encoded_user}?tab=repositories)",
            f"[![Total stars]({build_badge_url('Stars', str(stats['total_stars']), 'FFD700', 'github')})]"
            f"(https://github.com/{encoded_user}?tab=stars)",
            f"[![Profile views](https://komarev.com/ghpvc/?username={encoded_user}&style=for-the-badge&color=0e75b6)]"
            f"(https://github.com/{encoded_user})",
        ]
        lines.append(" ".join(badges))
        lines.append("")

    # -- About --------------------------------------------------------------
    if sections.get("about", True):
        lines.append("## 🙋‍♂️ About Me")
        lines.append("")
        lines.append(f"- 🔭 I'm currently building projects and learning in public.")
        lines.append(f"- 🌱 Focus: shipping small, useful tools — and finishing them.")
        lines.append(f"- ⭐ **{stats['total_stars']}** total stars across **{public_repos}** public repositories.")
        lines.append(f"- 👥 **{followers}** followers · **{following}** following.")
        if user.get("blog"):
            lines.append(f"- 🌐 Website: {user['blog']}")
        lines.append("")

    # -- Stats cards ----------------------------------------------------------
    if sections.get("stats", True):
        lines.append("## 📊 GitHub Stats")
        lines.append("")
        lines.append("<!-- Stats cards are images rendered live by github-readme-stats. -->")
        lines.append(
            f"![GitHub Stats](https://github-readme-stats.vercel.app/api"
            f"?username={encoded_user}&show_icons=true&theme={theme}"
            f"&count_private=false&hide_border=false)"
        )
        lines.append("")
        lines.append(
            f"![Top Languages](https://github-readme-stats.vercel.app/api/top-langs"
            f"/?username={encoded_user}&layout=compact&theme={theme}&hide_border=false)"
        )
        lines.append("")
        if config.get("show_streak", True):
            lines.append(
                f"![GitHub Streak](https://github-readme-streak-stats.herokuapp.com"
                f"/?user={encoded_user}&theme={theme}&hide_border=false)"
            )
            lines.append("")

    # -- Language breakdown (computed from this run's API data) -------------
    if sections.get("languages", True) and stats["languages"]:
        lines.append("## 🧑‍💻 Languages I Use")
        lines.append("")
        total = sum(stats["languages"].values())
        for language, count in stats["languages"].most_common():
            share = round(count / total * 100) if total else 0
            bar = "█" * max(1, share // 5) + "░" * max(0, 20 - max(1, share // 5))
            lines.append(
                f"- {language_dot(language)} — {count} repo{'s' if count != 1 else ''} "
                f"({share}%) `{bar}`"
            )
        lines.append("")

    # -- Latest projects ------------------------------------------------------
    if sections.get("latest_projects", True):
        lines.append("## 🚀 Latest Projects")
        lines.append("")
        if not shown_repos:
            lines.append("_No public repositories to show yet — check back soon._")
            lines.append("")
        else:
            lines.append("| Project | Description | Language | ⭐ Stars | 🍴 Forks | Updated |")
            lines.append("| ------- | ----------- | -------- | -------: | -------: | ------- |")
            for repo in shown_repos:
                name = repo.get("name") or "—"
                url = repo.get("html_url") or f"https://github.com/{encoded_user}/{name}"
                description = repo.get("description") or "—"
                description = escape_markdown(truncate(str(description), 100))
                language = language_dot(repo.get("language"))
                stars = int(repo.get("stargazers_count") or 0)
                forks = int(repo.get("forks_count") or 0)
                updated = format_date(str(repo.get("updated_at") or ""))
                fork_mark = " 🍴" if repo.get("fork") else ""
                lines.append(
                    f"| [{escape_markdown(name)}]({url}){fork_mark} | {description} | "
                    f"{language} | {stars} | {forks} | {updated} |"
                )
            lines.append("")
            lines.append(
                f"👉 [View all {public_repos} repositories on GitHub]"
                f"(https://github.com/{encoded_user}?tab=repositories)"
            )
            lines.append("")

    # -- Social links ---------------------------------------------------------
    if sections.get("social", True):
        social_links = []
        labels = {
            "github": "GitHub",
            "twitter": "X / Twitter",
            "instagram": "Instagram",
            "linkedin": "LinkedIn",
            "youtube": "YouTube",
            "website": "Website",
        }
        for key, label in labels.items():
            url = str(social.get(key) or "").strip()
            if url:
                social_links.append(f"[{label}]({url})")
        if social_links:
            lines.append("## 📫 Connect With Me")
            lines.append("")
            lines.append(" · ".join(social_links))
            lines.append("")

    # -- Footer ---------------------------------------------------------------
    if sections.get("footer", True):
        lines.append("---")
        lines.append("")
        lines.append(
            f"_Last updated: **{timestamp}** · "
            f"Generated automatically by [GitHub Profile Auto-Updater]"
            f"(https://github.com/{encoded_user}/github-profile-auto-updater) "
            f"from live GitHub data._"
        )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate a GitHub profile README from live public repo data.",
        epilog="No token is required for public data. Set GITHUB_TOKEN for a higher rate limit.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"Path to the config file (default: {DEFAULT_CONFIG})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output Markdown file (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--username", default=None,
                        help="Override the username from the config file")
    parser.add_argument("--max-repos", type=int, default=None,
                        help="Override how many repos to show in the Latest Projects table")
    parser.add_argument("--template", default=None,
                        help="Optional custom template file (reserved for future use)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the generated README to stdout instead of writing a file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    if args.username:
        # A different username was requested on the command line: the
        # config's personal details belong to the configured user, so clear
        # them and let the render fall back to the new user's GitHub data.
        if args.username.lower() != str(config["username"]).lower():
            config["display_name"] = ""
            config["bio"] = ""
            config["location"] = ""
            config.setdefault("social", {})["github"] = (
                f"https://github.com/{args.username}"
            )
        config["username"] = args.username
    if args.max_repos is not None:
        if args.max_repos < 1:
            print("Error: --max-repos must be at least 1.", file=sys.stderr)
            return 1
        config["max_repos"] = args.max_repos
    if args.template:
        print("Note: --template is accepted but custom templates are not used yet; "
              "the built-in template is rendered instead.", file=sys.stderr)

    username = str(config["username"])
    client = GitHubClient()
    try:
        user = client.get_user(username)
        all_repos = client.get_repos(username)
    except GitHubError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    shown_repos = filter_repos(all_repos, config)
    generated_at = datetime.now(timezone.utc)
    readme = render_readme(user, all_repos, shown_repos, config, generated_at)

    if args.dry_run:
        print(readme)
        return 0

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(readme, encoding="utf-8")

    total_stars = sum(int(r.get("stargazers_count") or 0) for r in all_repos)
    log(f"Fetched {len(all_repos)} public repos for @{username} "
        f"({total_stars} total stars); showing {len(shown_repos)} in the table.")
    log(f"Wrote {len(readme)} characters to {output_path} "
        f"(last updated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}).")
    print(f"✅ Done — {output_path} updated with {len(shown_repos)} latest projects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
