from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CareerItem:
    """
    Single career entry to be rendered as part of [[params.career.items]] in hugo.toml.
    """

    company: str
    role: str
    start: str  # e.g. "2021-05"
    end: str  # e.g. "2024-01" or "по настоящее время"
    description: str
    location: Optional[str] = None


@dataclass
class Course:
    """
    Course entry for [[params.education.courses]].
    """

    title: str
    url: Optional[str] = None
    provider: Optional[str] = None
    year: Optional[str] = None
    status: Optional[str] = None
    certificate: Optional[str] = None


@dataclass
class University:
    """
    University entry for [[params.education.universities]].
    """

    name: str
    year: str
    speciality: str
    degree: Optional[str] = None
    note: Optional[str] = None


@dataclass
class Profile:
    """
    High‑level profile model that mirrors the Hugo params schema and
    groups all user‑provided data.
    """

    # GitHub / repo metadata
    github_username: str
    repo_name: str

    # Basic profile (maps to [params] in hugo.toml)
    author_name: str
    author_surname: str
    author_grade: str
    author_city: str
    author_intro: str
    author_image_path: str = "/images/author.jpg"

    # Contacts
    author_email: Optional[str] = None
    author_telegram: Optional[str] = None
    author_linkedin: Optional[str] = None
    author_dribbble: Optional[str] = None
    author_behance: Optional[str] = None
    author_cv: Optional[str] = None

    # Collections
    career_items: List[CareerItem] = field(default_factory=list)
    courses: List[Course] = field(default_factory=list)
    universities: List[University] = field(default_factory=list)


def profile_to_hugo_params(profile: Profile) -> dict:
    """
    Convert Profile instance into a dict that matches the expected Hugo params
    structure. This is the only function that needs to know about the exact
    TOML layout.
    """

    education_block = {
        "courses": [
            {
                "title": c.title,
                "url": c.url or "",
                "provider": c.provider or "",
                # Either year or status is used in templates; keep both if present
                "year": c.year or "",
                "status": c.status or "",
                "certificate": c.certificate or "",
            }
            for c in profile.courses
        ],
        "universities": [
            {
                "name": u.name,
                "year": u.year,
                "speciality": u.speciality,
                "degree": u.degree or "",
                "note": u.note or "",
            }
            for u in profile.universities
        ],
    }

    career_block = {
        "items": [
            {
                "company": item.company,
                "role": item.role,
                "location": item.location or "",
                "start": item.start,
                "end": item.end,
                "description": item.description,
            }
            for item in profile.career_items
        ]
    }

    params = {
        "description": "Кейсы и портфолио",
        "author_name": profile.author_name,
        "author_surname": profile.author_surname,
        "author_grade": profile.author_grade,
        "author_city": profile.author_city,
        "author_intro": profile.author_intro,
        "author_image": profile.author_image_path,
        "author_email": profile.author_email or "",
        "author_telegram": profile.author_telegram or "",
        "author_linkedin": profile.author_linkedin or "",
        "author_dribbble": profile.author_dribbble or "",
        "author_behance": profile.author_behance or "",
        "author_cv": profile.author_cv or "",
        "education": education_block,
        "career": career_block,
    }

    return params

