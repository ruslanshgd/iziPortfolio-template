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
        with:
          path: ./public

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


def trigger_workflow_dispatch(
    *,
    token: str,
    owner: str,
    repo: str,
    workflow_id: str = "deploy.yml",
) -> None:
    """
    Trigger a workflow_dispatch event to rerun the GitHub Actions workflow.
    """
    session = requests.Session()
    session.headers.update(_auth_headers(token))
    
    # First, get the workflow ID by name
    workflows_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/actions/workflows/{workflow_id}"
    resp = session.get(workflows_url)
    if resp.status_code != 200:
        # Workflow not found, try to create it or skip
        return
    
    workflow_data = resp.json()
    workflow_id_num = workflow_data.get("id")
    if not workflow_id_num:
        return
    
    # Trigger workflow_dispatch
    dispatch_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/actions/workflows/{workflow_id_num}/dispatches"
    payload = {
        "ref": "main",
    }
    resp = session.post(dispatch_url, json=payload)
    if resp.status_code not in (204,):
        # Don't raise error, just log - workflow might not support dispatch
        pass


def ensure_workflow_and_trigger(
    *,
    token: str,
    owner: str,
    repo: str,
) -> tuple[bool, list[str]]:
    """
    Ensure workflow file exists and trigger it.
    Returns (workflow_created, warnings)
    """
    warnings = []
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
        with:
          path: ./public

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
    if not check_workflow_exists(token=token, owner=owner, repo=repo):
        try:
            workflow_created = ensure_workflow_file(
                token=token,
                owner=owner,
                repo=repo,
                workflow_content=workflow_content,
            )
            if workflow_created:
                warnings.append("✅ Workflow файл создан автоматически")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"⚠️ Не удалось создать workflow файл: {exc}")
    
    # Try to trigger workflow
    try:
        trigger_workflow_dispatch(token=token, owner=owner, repo=repo)
        warnings.append("🔄 GitHub Actions workflow перезапущен")
    except Exception:  # noqa: BLE001
        # Workflow will trigger automatically on next push anyway
        pass
    
    return workflow_created, warnings


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
    Removes all existing occurrences of the field to avoid duplicates, then adds the new value.
    
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

    def _toml_string(v: str) -> str:
        escaped = (
            v.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "")
        )
        return f'"{escaped}"'

    new_value = _toml_string(value)
    
    # First, remove ALL existing occurrences of the field to avoid duplicates
    # Pattern matches: field_name = "value" or field_name = 'value' or field_name = value (without quotes)
    # Matches the entire line including leading whitespace and trailing newline
    remove_pattern = rf'^\s*{re.escape(field_path)}\s*=\s*(?:["\'](?:[^"\']|\\["\'])*["\']|[^"\'\n]+)\s*$\n?'
    updated_content = re.sub(remove_pattern, "", current_content, flags=re.MULTILINE)
    
    # Remove empty lines that might have been left after removing fields
    # Replace 3+ consecutive newlines with double newline (preserve section spacing)
    updated_content = re.sub(r'\n{3,}', '\n\n', updated_content)
    
    # Now add the field in the [params] section
    params_section_pattern = r'(\[params\]\s*\n)'
    if re.search(params_section_pattern, updated_content):
        # Find the insertion point - after [params] and before next section or end
        match = re.search(params_section_pattern, updated_content)
        if match:
            insert_pos = match.end()
            # Find the next non-empty line to determine indentation
            next_lines = updated_content[insert_pos:insert_pos+200]  # Look ahead a bit
            indent_match = re.search(r'\n(\s+)(?:[a-zA-Z_])', next_lines)
            indent = indent_match.group(1) if indent_match else "  "
            
            # Insert the field with proper indentation
            field_line = f"{indent}{field_path} = {new_value}\n"
            updated_content = updated_content[:insert_pos] + field_line + updated_content[insert_pos:]
        else:
            raise GitHubError(f"Could not find insertion point in [params] section")
    else:
        raise GitHubError(f"Could not find [params] section in hugo.toml")

    # Upload updated file
    upsert_file(
        token=token,
        owner=owner,
        repo=repo,
        path="hugo.toml",
        content_bytes=updated_content.encode("utf-8"),
        message=f"chore: update {field_path} from Telegram bot",
    )

