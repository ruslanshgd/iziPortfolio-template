from __future__ import annotations

from typing import List

from .models import CareerItem, Course, Profile, University, profile_to_hugo_params


def _toml_string(value: str) -> str:
    """
    Safely quote a Python string for TOML.
    We keep it simple here and escape only the most common characters.
    """

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )
    return f'"{escaped}"'


def generate_hugo_toml(profile: Profile) -> str:
    """
    Generate full hugo.toml content for a user portfolio based on the Profile.

    We intentionally keep base settings (baseURL, title, languageCode, etc.)
    aligned with the template repo and only make the [params] section dynamic.
    """

    params = profile_to_hugo_params(profile)

    # Top‑level site settings – mirrors current hugo.toml in this repo.
    lines: List[str] = []
    lines.append('baseURL = "/"')
    lines.append('title = "Портфолио"')
    lines.append('languageCode = "ru-ru"')
    lines.append('defaultContentLanguage = "ru"')
    lines.append("")

    # [params] – flat keys first
    lines.append("[params]")
    flat_keys = [
        "description",
        "author_name",
        "author_surname",
        "author_grade",
        "author_city",
        "author_intro",
        "author_image",
        "author_email",
        "author_telegram",
        "author_linkedin",
        "author_dribbble",
        "author_behance",
        "author_cv",
    ]

    for key in flat_keys:
        value = params.get(key, "")
        lines.append(f"  {key} = {_toml_string(value)}")

    # [params.education]
    education = params["education"]
    lines.append("")
    lines.append("  [params.education]")

    courses: List[Course] = profile.courses
    for course in courses:
        lines.append("")
        lines.append("  [[params.education.courses]]")
        lines.append(f"    title = {_toml_string(course.title)}")
        if course.url:
            lines.append(f"    url = {_toml_string(course.url)}")
        if course.provider:
            lines.append(f"    provider = {_toml_string(course.provider)}")
        if course.status:
            lines.append(f"    status = {_toml_string(course.status)}")
        if course.year:
            lines.append(f"    year = {_toml_string(course.year)}")
        if course.certificate:
            lines.append(f"    certificate = {_toml_string(course.certificate)}")

    universities: List[University] = profile.universities
    for uni in universities:
        lines.append("")
        lines.append("  [[params.education.universities]]")
        lines.append(f"    name = {_toml_string(uni.name)}")
        lines.append(f"    year = {_toml_string(uni.year)}")
        lines.append(f"    speciality = {_toml_string(uni.speciality)}")
        if uni.degree:
            lines.append(f"    degree = {_toml_string(uni.degree)}")
        if uni.note:
            lines.append(f"    note = {_toml_string(uni.note)}")

    # [params.career]
    career_items: List[CareerItem] = profile.career_items
    lines.append("")
    lines.append("  [params.career]")
    for item in career_items:
        lines.append("")
        lines.append("  [[params.career.items]]")
        lines.append(f"    company = {_toml_string(item.company)}")
        lines.append(f"    role = {_toml_string(item.role)}")
        if item.location:
            lines.append(f"    location = {_toml_string(item.location)}")
        lines.append(f"    start = {_toml_string(item.start)}")
        lines.append(f"    end = {_toml_string(item.end)}")
        lines.append(f"    description = {_toml_string(item.description)}")

    # Keep non‑params sections from the template as constants.
    lines.append("")
    lines.append("[outputs]")
    lines.append('  home = ["HTML", "RSS"]')
    lines.append('  section = ["HTML"]')
    lines.append("")
    lines.append("[taxonomies]")
    lines.append('  # optional later: tag = "tags"')
    lines.append("")

    return "\n".join(lines)

