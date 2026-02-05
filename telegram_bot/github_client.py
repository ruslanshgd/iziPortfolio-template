from __future__ import annotations

import base64
import re
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


def check_repo_exists(
    *,
    token: str,
    owner: str,
    repo: str,
) -> bool:
    """Check if repository exists."""
    session = requests.Session()
    session.headers.update(_auth_headers(token))
    
    repo_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}"
    resp = session.get(repo_url)
    return resp.status_code == 200


def check_workflow_exists(
    *,
    token: str,
    owner: str,
    repo: str,
) -> bool:
    """Check if GitHub Actions workflow file exists."""
    session = requests.Session()
    session.headers.update(_auth_headers(token))
    
    workflow_path = ".github/workflows/deploy.yml"
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{workflow_path}"
    resp = session.get(url)
    return resp.status_code == 200


def ensure_workflow_file(
    *,
    token: str,
    owner: str,
    repo: str,
    workflow_content: str,
) -> bool:
    """
    Ensure that GitHub Actions workflow file exists.
    If it doesn't exist, create it.
    Returns True if file was created, False if it already existed.
    """
    session = requests.Session()
    session.headers.update(_auth_headers(token))
    
    workflow_path = ".github/workflows/deploy.yml"
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{workflow_path}"
    
    # Check if file exists
    resp = session.get(url)
    if resp.status_code == 200:
        return False  # File already exists
    
    # Create workflow file
    encoded = base64.b64encode(workflow_content.encode("utf-8")).decode("ascii")
    payload = {
        "message": "chore: add GitHub Actions workflow for Hugo deployment",
        "content": encoded,
        "branch": "main",
    }
    
    resp = session.put(url, json=payload)
    if resp.status_code not in (200, 201):
        raise GitHubError(
            f"Failed to create workflow file: {resp.status_code} {resp.text}"
        )
    return True  # File was created


def apply_profile_to_repo(
    *,
    token: str,
    profile: Profile,
    author_image_bytes: bytes,
    template_owner: str,
    template_repo: str,
) -> tuple[str, list[str]]:
    """
    High‑level helper used by the Telegram‑бот:

    1. Ensure repo exists (create from template if needed).
    2. Generate hugo.toml based on the collected Profile.
    3. Upload hugo.toml and author.jpg into the user's repo.

    Returns:
        - Expected GitHub Pages URL
        - List of warnings/notes for the user
    """
    warnings = []

    repo_json = ensure_repo_from_template(
        token=token,
        owner=profile.github_username,
        repo_name=profile.repo_name,
        template_owner=template_owner,
        template_repo=template_repo,
        private=False,
    )

    # Check if workflow file exists, create if missing
    workflow_content = """name: Deploy Hugo site to Pages

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

defaults:
  run:
    shell: bash

jobs:
  build:
    runs-on: ubuntu-latest
    env:
      HUGO_VERSION: 0.128.0
    steps:
      - name: Install Hugo CLI
        run: |
          wget -O ${{ runner.temp }}/hugo.deb https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.deb
          sudo dpkg -i ${{ runner.temp }}/hugo.deb
      - name: Install Dart Sass
        run: sudo snap install dart-sass
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: recursive
          fetch-depth: 0
      - name: Setup Pages
        id: pages
        uses: actions/configure-pages@v5
      - name: Build with Hugo
        env:
          HUGO_ENVIRONMENT: production
          HUGO_ENV: production
        run: |
          hugo \\
            --gc \\
            --minify \\
            --baseURL "${{ steps.pages.outputs.base_url }}/"
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""
    
    workflow_created = False
    if not check_workflow_exists(
        token=token,
        owner=profile.github_username,
        repo=profile.repo_name,
    ):
        try:
            workflow_created = ensure_workflow_file(
                token=token,
                owner=profile.github_username,
                repo=profile.repo_name,
                workflow_content=workflow_content,
            )
            if workflow_created:
                warnings.append(
                    "✅ Файл .github/workflows/deploy.yml создан автоматически. "
                    "GitHub Actions должен запуститься в ближайшее время."
                )
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"⚠️ Не удалось создать workflow файл: {exc}. "
                "Убедись, что у токена есть права workflow, или создай файл вручную."
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

    warnings.append(
        "📝 Важно: Убедись, что в настройках репозитория GitHub Pages использует "
        "GitHub Actions как источник (Settings → Pages → Source: GitHub Actions)."
    )

    return pages_url, warnings


def get_file_content(
    *,
    token: str,
    owner: str,
    repo: str,
    path: str,
) -> bytes:
    """
    Get file content from GitHub repository.
    """
    session = requests.Session()
    session.headers.update(_auth_headers(token))

    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{path}"
    resp = session.get(url)
    if resp.status_code == 200:
        data = resp.json()
        import base64
        return base64.b64decode(data["content"])
    raise GitHubError(f"Failed to get file {path}: {resp.status_code} {resp.text}")


def update_hugo_toml_field(
    *,
    token: str,
    owner: str,
    repo: str,
    field_path: str,
    value: str,
) -> None:
    """
    Update a specific field in hugo.toml.
    
    field_path examples:
    - "author_name" -> [params] author_name = "..."
    - "education.courses" -> [params.education.courses] (complex, handled separately)
    """
    # Get current hugo.toml
    current_content = get_file_content(
        token=token,
        owner=owner,
        repo=repo,
        path="hugo.toml",
    ).decode("utf-8")

    # Update the field using regex
    # Pattern: field_name = "old_value" or field_name = 'old_value'
    pattern = rf'^(\s*{re.escape(field_path)}\s*=\s*)(["\'])(.*?)\2'
    
    def _toml_string(v: str) -> str:
        escaped = (
            v.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "")
        )
        return f'"{escaped}"'

    new_value = _toml_string(value)
    replacement = rf'\1{new_value}'
    
    updated_content = re.sub(pattern, replacement, current_content, flags=re.MULTILINE)
    
    if updated_content == current_content:
        # Field not found, try to add it in [params] section
        params_section_pattern = r'(\[params\]\s*\n)'
        if re.search(params_section_pattern, updated_content):
            # Insert after [params]
            updated_content = re.sub(
                params_section_pattern,
                rf'\1  {field_path} = {new_value}\n',
                updated_content,
            )
        else:
            raise GitHubError(f"Could not find [params] section or field {field_path}")

    # Upload updated file
    upsert_file(
        token=token,
        owner=owner,
        repo=repo,
        path="hugo.toml",
        content_bytes=updated_content.encode("utf-8"),
        message=f"chore: update {field_path} from Telegram bot",
    )

