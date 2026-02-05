from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, executor, types

from .github_client import apply_profile_to_repo
from .models import CareerItem, Course, Profile, University


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TEMPLATE_OWNER = os.getenv("HUGO_TEMPLATE_OWNER", "our-org")
TEMPLATE_REPO = os.getenv("HUGO_TEMPLATE_REPO", "iziPortfolio-template")


if not TELEGRAM_BOT_TOKEN:
    logger.warning(
        "Environment variable TELEGRAM_BOT_TOKEN is not set. "
        "The bot will not be able to start until you export it."
    )


@dataclass
class UserSession:
    """
    In‑memory session that accumulates all answers from a single user
    before we generate hugo.toml and update the GitHub repository.
    """

    github_token: Optional[str] = None
    github_username: Optional[str] = None
    repo_name: Optional[str] = None

    # Profile data (single‑value fields)
    profile_data: Dict[str, Any] = field(default_factory=dict)

    # Collections
    career_items: List[Dict[str, Any]] = field(default_factory=list)
    universities: List[Dict[str, Any]] = field(default_factory=list)
    courses: List[Dict[str, Any]] = field(default_factory=list)

    author_image_bytes: Optional[bytes] = None

    # Cursor for the dialog flow
    step: str = "github_username"
    pending_career: Dict[str, Any] = field(default_factory=dict)
    pending_university: Dict[str, Any] = field(default_factory=dict)
    pending_course: Dict[str, Any] = field(default_factory=dict)


bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher(bot) if bot else None

# user_id -> UserSession
SESSIONS: Dict[int, UserSession] = {}


def _get_session(user_id: int) -> UserSession:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = UserSession()
    return SESSIONS[user_id]


async def _start_dialog(message: types.Message) -> None:
    session = _get_session(message.from_user.id)
    session.step = "github_username"
    await message.answer(
        "Привет! Я помогу собрать портфолио и опубликовать его на GitHub Pages.\n\n"
        "Бот создаст (или обновит) репозиторий на GitHub из Hugo‑шаблона, "
        "запишет туда конфиг и фото, а затем запустит GitHub Actions.\n\n"
        "На одном из шагов потребуется GitHub Personal Access Token с правами "
        "public_repo (и опционально workflow). Токен используется только во время "
        "этой сессии и не сохраняется.\n\n"
        "Сначала введи, пожалуйста, свой GitHub username."
    )


@dp.message_handler(commands=["start", "restart"])
async def cmd_start(message: types.Message) -> None:
    await _start_dialog(message)


@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message) -> None:
    user_id = message.from_user.id
    session = _get_session(user_id)

    if session.step != "author_photo":
        # Ignore unrelated photos.
        return

    photo = message.photo[-1]
    buffer = io.BytesIO()
    await photo.download(destination_file=buffer)
    session.author_image_bytes = buffer.getvalue()

    await message.answer("Фото получено ✅")

    # Move to career section.
    session.step = "career_company"
    await message.answer(
        "Давай теперь заполним карьеру.\n"
        "Укажи название компании для первого места работы."
    )


async def _finalize_profile_and_deploy(message: types.Message, session: UserSession) -> None:
    """
    Convert collected answers into a Profile model and push them to GitHub.
    """

    if not session.github_token or not session.github_username or not session.repo_name:
        await message.answer(
            "Не хватает данных GitHub (username / токен / имя репозитория). "
            "Попробуй начать сначала командой /start."
        )
        return

    if not session.author_image_bytes:
        await message.answer(
            "Похоже, ты не отправил фотографию. "
            "Сейчас она обязательна для генерации портфолио."
        )
        return

    pd = session.profile_data

    try:
        profile = Profile(
            github_username=session.github_username,
            repo_name=session.repo_name,
            author_name=pd["author_name"],
            author_surname=pd["author_surname"],
            author_grade=pd["author_grade"],
            author_city=pd["author_city"],
            author_intro=pd["author_intro"],
            author_email=pd.get("author_email"),
            author_telegram=pd.get("author_telegram"),
            author_linkedin=pd.get("author_linkedin"),
            author_dribbble=pd.get("author_dribbble"),
            author_behance=pd.get("author_behance"),
            author_cv=pd.get("author_cv"),
            career_items=[
                CareerItem(
                    company=item["company"],
                    role=item["role"],
                    location=item.get("location"),
                    start=item["start"],
                    end=item["end"],
                    description=item["description"],
                )
                for item in session.career_items
            ],
            courses=[
                Course(
                    title=item["title"],
                    url=item.get("url"),
                    provider=item.get("provider"),
                    year=item.get("year"),
                    status=item.get("status"),
                    certificate=item.get("certificate"),
                )
                for item in session.courses
            ],
            universities=[
                University(
                    name=item["name"],
                    year=item["year"],
                    speciality=item["speciality"],
                    degree=item.get("degree"),
                    note=item.get("note"),
                )
                for item in session.universities
            ],
        )
    except KeyError as exc:
        await message.answer(
            f"Не удалось собрать профиль – не хватает поля {exc!s}. "
            "Попробуй начать сначала командой /start."
        )
        return

    await message.answer("Формирую репозиторий на GitHub и запускаю сборку Hugo…")

    try:
        pages_url = apply_profile_to_repo(
            token=session.github_token,
            profile=profile,
            author_image_bytes=session.author_image_bytes,
            template_owner=TEMPLATE_OWNER,
            template_repo=TEMPLATE_REPO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to apply profile to GitHub repo")
        await message.answer(
            "Произошла ошибка при работе с GitHub API. "
            "Проверь, пожалуйста, что токен корректный и у него есть права public_repo."
        )
        return

    # Reset session after successful deployment.
    SESSIONS.pop(message.from_user.id, None)

    await message.answer(
        "Готово! 🚀\n\n"
        f"Твоё портфолио будет доступно по ссылке (с небольшой задержкой на сборку GitHub Pages):\n{pages_url}\n\n"
        "Если захочешь обновить данные, просто снова вызови /start."
    )


@dp.message_handler()
async def dialog_flow(message: types.Message) -> None:
    """
    Основной обработчик диалога. Маршрутизирует входящие сообщения
    по текущему шагу сессии пользователя.
    """

    user_id = message.from_user.id
    session = _get_session(user_id)
    text = (message.text or "").strip()

    # On a fresh chat without /start, guide the user.
    if not session.github_username and session.step == "github_username" and not text:
        await _start_dialog(message)
        return

    if session.step == "github_username":
        session.github_username = text
        session.step = "github_token"
        await message.answer(
            "Теперь пришли GitHub Personal Access Token.\n"
            "Он нужен только для того, чтобы создать репозиторий из шаблона "
            "и записать туда файлы. Мы не храним токен после завершения сессии."
        )
        return

    if session.step == "github_token":
        session.github_token = text
        session.step = "repo_name"
        await message.answer(
            "Как назвать репозиторий для портфолио?\n"
            "Например: portfolio или izi-portfolio.\n\n"
            "Важно: токен нужен только для создания репозитория из шаблона и "
            "записи/обновления файлов (hugo.toml и фото). Рекомендуемые права токена: "
            "public_repo (и, по желанию, workflow для управления GitHub Actions). "
            "Токен не сохраняется после завершения этой сессии."
        )
        return

    if session.step == "repo_name":
        session.repo_name = text
        session.step = "author_name"
        await message.answer("Отлично. Теперь давай перейдём к профилю.\n\nКак тебя зовут (имя)?")
        return

    if session.step == "author_name":
        session.profile_data["author_name"] = text
        session.step = "author_surname"
        await message.answer("Фамилия:")
        return

    if session.step == "author_surname":
        session.profile_data["author_surname"] = text
        session.step = "author_grade"
        await message.answer("Твой грейд / роль (например, «Senior Product Designer»):")
        return

    if session.step == "author_grade":
        session.profile_data["author_grade"] = text
        session.step = "author_city"
        await message.answer("Город, в котором ты сейчас живёшь:")
        return

    if session.step == "author_city":
        session.profile_data["author_city"] = text
        session.step = "author_intro"
        await message.answer(
            "Напиши, пожалуйста, краткое интро (2–4 предложения) о себе. "
            "Оно попадёт в hero‑блок на главной странице."
        )
        return

    if session.step == "author_intro":
        session.profile_data["author_intro"] = text
        session.step = "contacts_email"
        await message.answer(
            "Теперь контакты.\n\n"
            "Укажи e‑mail (или напиши «-», если не хочешь его добавлять):"
        )
        return

    if session.step == "contacts_email":
        if text != "-":
            session.profile_data["author_email"] = text
        session.step = "contacts_telegram"
        await message.answer(
            "Ссылка на Telegram (например, https://t.me/username) "
            "или «-», если не нужно:"
        )
        return

    if session.step == "contacts_telegram":
        if text != "-":
            session.profile_data["author_telegram"] = text
        session.step = "contacts_linkedin"
        await message.answer(
            "Ссылка на LinkedIn (если есть) или «-», если не нужно:"
        )
        return

    if session.step == "contacts_linkedin":
        if text != "-":
            session.profile_data["author_linkedin"] = text
        session.step = "contacts_dribbble"
        await message.answer(
            "Ссылка на Dribbble (если есть) или «-», если не нужно:"
        )
        return

    if session.step == "contacts_dribbble":
        if text != "-":
            session.profile_data["author_dribbble"] = text
        session.step = "contacts_behance"
        await message.answer(
            "Ссылка на Behance (если есть) или «-», если не нужно:"
        )
        return

    if session.step == "contacts_behance":
        if text != "-":
            session.profile_data["author_behance"] = text
        session.step = "contacts_cv"
        await message.answer(
            "Ссылка на резюме / CV (Google Drive, Notion и т.п.) "
            "или «-», если не нужно:"
        )
        return

    if session.step == "contacts_cv":
        if text != "-":
            session.profile_data["author_cv"] = text
        session.step = "author_photo"
        await message.answer(
            "Теперь пришли, пожалуйста, фотографию, которую хочешь использовать в портфолио."
        )
        return

    # --------------- Career flow ---------------
    if session.step == "career_company":
        session.pending_career = {"company": text}
        session.step = "career_role"
        await message.answer("Твоя роль / позиция в этой компании:")
        return

    if session.step == "career_role":
        session.pending_career["role"] = text
        session.step = "career_location"
        await message.answer(
            "Город / локация (можно оставить пустым, отправив «-»):"
        )
        return

    if session.step == "career_location":
        if text != "-":
            session.pending_career["location"] = text
        session.step = "career_start"
        await message.answer(
            "Дата начала работы (например, 2021-05 или просто 2021):"
        )
        return

    if session.step == "career_start":
        session.pending_career["start"] = text
        session.step = "career_end"
        await message.answer(
            "Дата окончания работы (например, 2023-10) или напиши «по настоящее время»:"
        )
        return

    if session.step == "career_end":
        session.pending_career["end"] = text
        session.step = "career_description"
        await message.answer(
            "Опиши кратко, чем ты занимался(ась) и каких результатов добился(ась). "
            "Можно несколькими предложениями."
        )
        return

    if session.step == "career_description":
        session.pending_career["description"] = text
        session.career_items.append(session.pending_career)
        session.pending_career = {}
        session.step = "career_more"
        await message.answer(
            "Добавить ещё одно место работы? Напиши «да» или «нет»."
        )
        return

    if session.step == "career_more":
        if text.lower() in ("да", "yes", "y"):
            session.step = "career_company"
            await message.answer("Окей, укажи название следующей компании:")
            return

        # Move to education section.
        session.step = "edu_university_name"
        await message.answer(
            "Перейдём к образованию.\n"
            "Сначала университеты. Укажи название первого университета:"
        )
        return

    # --------------- Education: universities ---------------
    if session.step == "edu_university_name":
        session.pending_university = {"name": text}
        session.step = "edu_university_year"
        await message.answer("Год окончания (например, 2021):")
        return

    if session.step == "edu_university_year":
        session.pending_university["year"] = text
        session.step = "edu_university_speciality"
        await message.answer("Специальность:")
        return

    if session.step == "edu_university_speciality":
        session.pending_university["speciality"] = text
        session.step = "edu_university_degree"
        await message.answer("Степень (бакалавр, магистр и т.п.) или «-», если не нужно:")
        return

    if session.step == "edu_university_degree":
        if text != "-":
            session.pending_university["degree"] = text
        session.step = "edu_university_note"
        await message.answer(
            "Дополнительная приметка (например, средний балл) или «-», если не нужно:"
        )
        return

    if session.step == "edu_university_note":
        if text != "-":
            session.pending_university["note"] = text
        session.universities.append(session.pending_university)
        session.pending_university = {}
        session.step = "edu_university_more"
        await message.answer("Добавить ещё один университет? «да» или «нет»:")
        return

    if session.step == "edu_university_more":
        if text.lower() in ("да", "yes", "y"):
            session.step = "edu_university_name"
            await message.answer("Название следующего университета:")
            return

        # Move to courses.
        session.step = "edu_course_title"
        await message.answer(
            "Теперь курсы. Укажи название первого курса (или напиши «нет», если курсов не было):"
        )
        return

    # --------------- Education: courses ---------------
    if session.step == "edu_course_title":
        if text.lower() in ("нет", "no", "none"):
            # No courses – we can finish and deploy.
            await _finalize_profile_and_deploy(message, session)
            return

        session.pending_course = {"title": text}
        session.step = "edu_course_url"
        await message.answer(
            "Ссылка на страницу курса (если есть) или «-», если не нужно:"
        )
        return

    if session.step == "edu_course_url":
        if text != "-":
            session.pending_course["url"] = text
        session.step = "edu_course_provider"
        await message.answer("Организатор / провайдер курса (например, название школы):")
        return

    if session.step == "edu_course_provider":
        session.pending_course["provider"] = text
        session.step = "edu_course_year_or_status"
        await message.answer(
            "Год окончания курса (например, 2024) или статус (например, «прохожу сейчас»):"
        )
        return

    if session.step == "edu_course_year_or_status":
        # Не пытаемся строго разделять статус/год, просто сохраняем строку.
        session.pending_course["status"] = text
        session.step = "edu_course_certificate"
        await message.answer(
            "Ссылка на сертификат (если есть) или «-», если не нужно:"
        )
        return

    if session.step == "edu_course_certificate":
        if text != "-":
            session.pending_course["certificate"] = text
        session.courses.append(session.pending_course)
        session.pending_course = {}
        session.step = "edu_course_more"
        await message.answer("Добавить ещё один курс? «да» или «нет»:")
        return

    if session.step == "edu_course_more":
        if text.lower() in ("да", "yes", "y"):
            session.step = "edu_course_title"
            await message.answer("Название следующего курса:")
            return

        # All data collected – deploy to GitHub.
        await _finalize_profile_and_deploy(message, session)
        return

    # Fallback: if we got here, something went out of sync.
    await message.answer(
        "Похоже, диалог сбился. Попробуй, пожалуйста, начать сначала командой /start."
    )


def main() -> None:
    """
    Entry‑point for running the Telegram bot.

    Example:
        export TELEGRAM_BOT_TOKEN=123456:ABC...
        export HUGO_TEMPLATE_OWNER=our-org
        export HUGO_TEMPLATE_REPO=iziPortfolio-template
        python -m telegram_bot.bot
    """

    if bot is None or dp is None:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured. "
            "Set it in the environment before running the bot."
        )

    executor.start_polling(dp, skip_updates=True)


if __name__ == "__main__":
    main()

