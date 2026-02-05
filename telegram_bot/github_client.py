from __future__ import annotations

import base64
from typing import Optional

import requests

from .hugo_generator import generate_hugo_toml
from .models import Profile


GITHUB_API_URL = "https://api.github.com"


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def ensure_repo_from_template(
    *,
    token: str,
    owner: str,
    repo_name: str,
    template_owner: str,
    template_repo: str,
    private: bool = False,
) -> dict:
    """
    Ensure that a repository {owner}/{repo_name} exists. If it does not,
    create it from the specified template repository.
    """

    session = requests.Session()
    session.headers.update(_auth_headers(token))

    # 1) Check if repo already exists.
    repo_url = f"{GITHUB_API_URL}/repos/{owner}/{repo_name}"
    resp = session.get(repo_url)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code not in (404,):
        raise GitHubError(f"Failed to inspect repo: {resp.status_code} {resp.text}")

    # 2) Create from template.
    generate_url = f"{GITHUB_API_URL}/repos/{template_owner}/{template_repo}/generate"
    payload = {
        "owner": owner,
        "name": repo_name,
        "private": private,
    }
    resp = session.post(generate_url, json=payload)
    if resp.status_code not in (201, 202):
        raise GitHubError(
            f"Failed to create repo from template: {resp.status_code} {resp.text}"
        )
    return resp.json()


def _get_existing_file_sha(
    session: requests.Session,
    owner: str,
    repo: str,
    path: str,
) -> Optional[str]:
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}"
    resp = session.get(url)
    if resp.status_code == 200:
        data = resp.json()
        return data.get("sha")
    if resp.status_code in (404,):
        return None
    raise GitHubError(f"Failed to inspect file {path}: {resp.status_code} {resp.text}")


def upsert_file(
    *,
    token: str,
    owner: str,
    repo: str,
    path: str,
    content_bytes: bytes,
    message: str,
) -> None:
    """
    Create or update a file in the repo using the GitHub contents API.
    """

    session = requests.Session()
    session.headers.update(_auth_headers(token))

    sha = _get_existing_file_sha(session, owner, repo, path)

    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}"
    encoded = base64.b64encode(content_bytes).decode("ascii")
    payload = {
        "message": message,
        "content": encoded,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    resp = session.put(url, json=payload)
    if resp.status_code not in (200, 201):
        raise GitHubError(
            f"Failed to upsert {path}: {resp.status_code} {resp.text}"
        )


def apply_profile_to_repo(
    *,
    token: str,
    profile: Profile,
    author_image_bytes: bytes,
    template_owner: str,
    template_repo: str,
) -> str:
    """
    High‑level helper used by the Telegram‑бот:

    1. Ensure repo exists (create from template if needed).
    2. Generate hugo.toml based on the collected Profile.
    3. Upload hugo.toml and author.jpg into the user's repo.

    Returns an expected GitHub Pages URL, which the бот can send to the user.
    """

    repo_json = ensure_repo_from_template(
        token=token,
        owner=profile.github_username,
        repo_name=profile.repo_name,
        template_owner=template_owner,
        template_repo=template_repo,
        private=False,
    )

    hugo_toml_content = generate_hugo_toml(profile)
    upsert_file(
        token=token,
        owner=profile.github_username,
        repo=profile.repo_name,
        path="hugo.toml",
        content_bytes=hugo_toml_content.encode("utf-8"),
        message="chore: update portfolio configuration from Telegram bot",
    )

    # Upload author photo into static/images/author.jpg
    upsert_file(
        token=token,
        owner=profile.github_username,
        repo=profile.repo_name,
        path="static/images/author.jpg",
        content_bytes=author_image_bytes,
        message="chore: update author photo from Telegram bot",
    )

    # Simplest heuristic for Pages URL – user can override later if needed.
    pages_url = f"https://{profile.github_username}.github.io/{profile.repo_name}/"
    # If the repo is named like username.github.io, Pages URL is slightly different.
    if repo_json.get("name", "").lower() == f"{profile.github_username.lower()}.github.io":
        pages_url = f"https://{profile.github_username}.github.io/"

    return pages_url

