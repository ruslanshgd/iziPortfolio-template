from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, executor, types

from .github_client import apply_profile_to_repo, update_hugo_toml_field
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
    
    # For /update command
    update_mode: bool = False
    update_field: Optional[str] = None


bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher(bot) if bot else None

# user_id -> UserSession
SESSIONS: Dict[int, UserSession] = {}

# Path to store user repository info (persistent across bot restarts)
REPO_INFO_FILE = Path("telegram_bot/user_repos.json")


def _load_repo_info() -> Dict[str, Dict[str, str]]:
    """Load repository info from file. Returns dict with string keys (user_id as str)."""
    if not REPO_INFO_FILE.exists():
        return {}
    try:
        with open(REPO_INFO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure all keys are strings
            return {str(k): v for k, v in data.items()}
    except Exception:  # noqa: BLE001
        return {}


def _find_repo_by_username(username: str) -> Optional[Dict[str, str]]:
    """Find repository info by GitHub username across all users."""
    repo_info = _load_repo_info()
    for user_data in repo_info.values():
        if user_data.get("github_username") == username:
            return user_data
    return None


def _save_repo_info(user_id: int, github_username: str, repo_name: str) -> None:
    """Save repository info to file."""
    repo_info = _load_repo_info()
    user_id_str = str(user_id)
    repo_info[user_id_str] = {
        "github_username": github_username,
        "repo_name": repo_name,
    }
    REPO_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(repo_info, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved repo info for user {user_id}: {github_username}/{repo_name}")


def _get_session(user_id: int) -> UserSession:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = UserSession()
        # Try to restore repo info from file
        repo_info = _load_repo_info()
        user_id_str = str(user_id)
        if user_id_str in repo_info:
            data = repo_info[user_id_str]
            SESSIONS[user_id].github_username = data.get("github_username")
            SESSIONS[user_id].repo_name = data.get("repo_name")
            logger.info(f"Restored repo info for user {user_id}: {SESSIONS[user_id].github_username}/{SESSIONS[user_id].repo_name}")
    return SESSIONS[user_id]


def _get_welcome_message() -> str:
    """Generate welcome message with available commands."""
    return (
        "👋 Привет! Я бот для создания портфолио на GitHub Pages.\n\n"
        "📋 **Доступные команды:**\n\n"
        "• `/start` — создать новое портфолио или управлять существующим\n"
        "• `/update` — обновить отдельные поля в существующем портфолио\n"
        "• `/help` — показать справку по командам\n"
        "• `/restart` — начать заново\n\n"
        "🔧 **Как это работает:**\n"
        "Бот создаст репозиторий на GitHub из Hugo‑шаблона, "
        "запишет туда конфиг и фото, а затем запустит GitHub Actions для автоматического деплоя.\n\n"
        "🔑 **GitHub токен:**\n"
        "На одном из шагов потребуется GitHub Personal Access Token с правами "
        "`public_repo` (и опционально `workflow`). Токен используется только во время "
        "сессии и не сохраняется.\n\n"
        "💡 **Начни с команды** `/start` для создания портфолио!"
    )


async def _start_dialog(message: types.Message) -> None:
    session = _get_session(message.from_user.id)
    # If we already have repo info, ask for token again (it might have expired)
    if session.github_username and session.repo_name:
        session.step = "github_token"
        await message.answer(
            f"У тебя уже есть портфолио: {session.github_username}/{session.repo_name}\n\n"
            "Для создания нового портфолио нужен GitHub токен.\n"
            "Пришли GitHub Personal Access Token:"
        )
        return
    
    session.step = "github_username"
    await message.answer(
        "Сначала введи, пожалуйста, свой GitHub username:"
    )


@dp.message_handler(commands=["start", "restart"])
async def cmd_start(message: types.Message) -> None:
    user_id = message.from_user.id
    session = _get_session(user_id)
    
    # Send welcome message first
    await message.answer(_get_welcome_message(), parse_mode="Markdown")
    
    # Check if user has saved repo info
    repo_info = _load_repo_info()
    if str(user_id) in repo_info:
        saved_data = repo_info[str(user_id)]
        session.github_username = saved_data.get("github_username")
        session.repo_name = saved_data.get("repo_name")
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        keyboard.add("🔄 Создать новое портфолио")
        keyboard.add("✏️ Обновить существующее (/update)")
        keyboard.add("❌ Отмена")
        
        await message.answer(
            f"У тебя уже есть портфолио: {session.github_username}/{session.repo_name}\n\n"
            "Что хочешь сделать?",
            reply_markup=keyboard,
        )
        session.step = "start_choice"
        return
    
    await _start_dialog(message)


@dp.message_handler(commands=["help"])
async def cmd_help(message: types.Message) -> None:
    """Show help message with available commands."""
    help_text = (
        "📚 **Справка по командам:**\n\n"
        "**`/start`** — Главная команда для создания портфолио\n"
        "• Если у тебя еще нет портфолио — начнется процесс создания\n"
        "• Если портфолио уже есть — предложит создать новое или обновить существующее\n\n"
        "**`/update`** — Обновление отдельных полей портфолио\n"
        "• Позволяет изменить имя, фамилию, грейд, город, интро, контакты или фото\n"
        "• Работает только если портфолио уже создано через `/start`\n"
        "• Требует GitHub токен для доступа к репозиторию\n\n"
        "**`/restart`** — Начать заново\n"
        "• Сбрасывает текущую сессию и начинается с начала\n\n"
        "**`/help`** — Показать эту справку\n\n"
        "💡 **Совет:** Используй `/start` для начала работы с ботом!"
    )
    await message.answer(help_text, parse_mode="Markdown")


@dp.message_handler(commands=["update"])
async def cmd_update(message: types.Message) -> None:
    """
    Команда для обновления отдельных полей портфолио.
    Требует, чтобы репозиторий уже был создан через /start.
    """
    user_id = message.from_user.id
    session = _get_session(user_id)
    
    if not session.github_username or not session.repo_name:
        await message.answer(
            "❌ Сначала нужно создать портфолио через команду /start.\n\n"
            "Команда /update позволяет обновлять отдельные поля в уже созданном портфолио."
        )
        return
    
    # If token is missing, ask for it
    if not session.github_token:
        session.step = "update_need_token"
        await message.answer(
            "Для обновления портфолио нужен GitHub токен.\n\n"
            "Пришли GitHub Personal Access Token:"
        )
        return
    
    session.update_mode = True
    session.step = "update_menu"
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add("👤 Имя и фамилия")
    keyboard.add("💼 Грейд / роль")
    keyboard.add("📍 Город")
    keyboard.add("📝 Интро")
    keyboard.add("📧 Контакты")
    keyboard.add("📸 Фото")
    keyboard.add("❌ Отмена")
    
    await message.answer(
        "🔄 Что хочешь обновить?\n\n"
        "Выбери пункт из меню:",
        reply_markup=keyboard,
    )


@dp.message_handler(content_types=types.ContentType.PHOTO)
async def handle_photo(message: types.Message) -> None:
    user_id = message.from_user.id
    session = _get_session(user_id)

    # Handle photo update
    if session.update_mode and session.step == "update_author_photo":
        if not session.github_token or not session.github_username or not session.repo_name:
            await message.answer("❌ Ошибка: данные репозитория не найдены. Используй /start для создания портфолио.")
            return
        
        photo = message.photo[-1]
        buffer = io.BytesIO()
        await photo.download(destination_file=buffer)
        photo_bytes = buffer.getvalue()
        
        try:
            from .github_client import upsert_file
            upsert_file(
                token=session.github_token,
                owner=session.github_username,
                repo=session.repo_name,
                path="static/images/author.jpg",
                content_bytes=photo_bytes,
                message="chore: update author photo from Telegram bot",
            )
            # Ensure workflow exists and trigger it
            from .github_client import ensure_workflow_and_trigger
            workflow_created, workflow_warnings = ensure_workflow_and_trigger(
                token=session.github_token,
                owner=session.github_username,
                repo=session.repo_name,
            )
            
            session.update_mode = False
            session.update_field = None
            session.step = "github_username"
            
            message_text = "✅ Фото обновлено!\n\n"
            if workflow_warnings:
                message_text += "\n".join(f"• {w}" for w in workflow_warnings) + "\n\n"
            message_text += (
                "⏳ GitHub Actions соберет обновленный сайт через несколько минут.\n"
                f"Проверить статус: https://github.com/{session.github_username}/{session.repo_name}/actions"
            )
            await message.answer(message_text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to update photo")
            await message.answer(f"❌ Ошибка при обновлении фото: {exc}")
            return

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
        pages_url, warnings = apply_profile_to_repo(
            token=session.github_token,
            profile=profile,
            author_image_bytes=session.author_image_bytes,
            template_owner=TEMPLATE_OWNER,
            template_repo=TEMPLATE_REPO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to apply profile to GitHub repo")
        error_msg = str(exc)
        await message.answer(
            f"❌ Произошла ошибка при работе с GitHub API:\n\n{error_msg}\n\n"
            "Проверь, пожалуйста:\n"
            "• Токен корректный и не истек\n"
            "• У токена есть права public_repo (и workflow для GitHub Actions)\n"
            "• Репозиторий шаблона существует и доступен\n"
            "• GitHub username указан правильно"
        )
        return

    # Save repository info persistently for /update command
    _save_repo_info(
        user_id=message.from_user.id,
        github_username=profile.github_username,
        repo_name=profile.repo_name,
    )
    
    # Keep repository info for /update command, but reset dialog state
    # Important: keep github_token, github_username, repo_name for future updates
    session.step = "github_username"
    session.profile_data = {}
    session.career_items = []
    session.universities = []
    session.courses = []
    session.author_image_bytes = None
    session.update_mode = False
    # DO NOT clear: github_token, github_username, repo_name - needed for /update

    repo_url = f"https://github.com/{profile.github_username}/{profile.repo_name}"
    actions_url = f"{repo_url}/actions"
    settings_url = f"{repo_url}/settings/pages"
    
    success_message = (
        "Готово! 🚀\n\n"
        f"Репозиторий создан: {repo_url}\n\n"
        f"Твоё портфолио будет доступно по ссылке:\n{pages_url}\n\n"
        "📋 **Обязательные шаги для публикации сайта:**\n\n"
        "**1. Настрой GitHub Pages:**\n"
        f"   Открой: {settings_url}\n\n"
        "   В разделе «Build and deployment»:\n"
        "   • **Source:** выбери **«GitHub Actions»** (не Jekyll, не Static HTML!)\n"
        "   • Нажми «Save»\n\n"
        "   ⚠️ **Важно:** НЕ нажимай «Configure» на карточках "
        "«GitHub Pages Jekyll» или «Static HTML» — они не подходят для Hugo!\n\n"
        "**2. Проверь статус деплоя:**\n"
        f"   {actions_url}\n"
        "   • Должен запуститься workflow «Deploy Hugo site to Pages»\n"
        "   • Дождись завершения (зеленый статус = успех)\n"
        "   • Если ошибка — проверь логи в workflow\n\n"
        "**3. Подожди 2–3 минуты** после успешного деплоя,\n"
        "   затем проверь сайт по ссылке выше.\n\n"
    )
    
    if warnings:
        success_message += "\n⚠️ **Предупреждения:**\n" + "\n".join(f"• {w}" for w in warnings) + "\n\n"
    
    success_message += (
        "💡 **Полезные ссылки:**\n"
        f"• Репозиторий: {repo_url}\n"
        f"• Actions: {actions_url}\n"
        f"• Настройки Pages: {settings_url}\n\n"
        "💡 Чтобы обновить отдельные поля, используй команду /update"
    )
    
    await message.answer(success_message)


@dp.message_handler()
async def dialog_flow(message: types.Message) -> None:
    """
    Основной обработчик диалога. Маршрутизирует входящие сообщения
    по текущему шагу сессии пользователя.
    """

    user_id = message.from_user.id
    session = _get_session(user_id)
    text = (message.text or "").strip()

    # Handle start choice (recreate vs update)
    if session.step == "start_choice":
        if text == "🔄 Создать новое портфолио":
            # Clear repository info to start fresh
            session.github_token = None
            session.github_username = None
            session.repo_name = None
            # Remove from saved repo info
            repo_info = _load_repo_info()
            repo_info.pop(str(user_id), None)
            REPO_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(REPO_INFO_FILE, "w", encoding="utf-8") as f:
                json.dump(repo_info, f, indent=2, ensure_ascii=False)
            await message.answer("Начинаем создание нового портфолио...", reply_markup=types.ReplyKeyboardRemove())
            await _start_dialog(message)
            return
        elif text == "✏️ Обновить существующее (/update)":
            session.step = "github_username"
            await message.answer("Используй команду /update для обновления полей.", reply_markup=types.ReplyKeyboardRemove())
            return
        elif text == "❌ Отмена":
            session.step = "github_username"
            await message.answer("Отменено.", reply_markup=types.ReplyKeyboardRemove())
            return
    
    # Handle token request for update
    if session.step == "update_need_token":
        session.github_token = text
        session.update_mode = True
        session.step = "update_menu"
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        keyboard.add("👤 Имя и фамилия")
        keyboard.add("💼 Грейд / роль")
        keyboard.add("📍 Город")
        keyboard.add("📝 Интро")
        keyboard.add("📧 Контакты")
        keyboard.add("📸 Фото")
        keyboard.add("❌ Отмена")
        await message.answer(
            "Токен получен ✅\n\n"
            "🔄 Что хочешь обновить?\n\n"
            "Выбери пункт из меню:",
            reply_markup=keyboard,
        )
        return
    
    # Handle update mode
    if session.update_mode:
        if text == "❌ Отмена":
            session.update_mode = False
            session.update_field = None
            session.step = "github_username"
            await message.answer("Обновление отменено.", reply_markup=types.ReplyKeyboardRemove())
            return
        
        if session.step == "update_menu":
            if text == "👤 Имя и фамилия":
                session.step = "update_author_name"
                session.update_field = "author_name"
                await message.answer("Введи новое имя:", reply_markup=types.ReplyKeyboardRemove())
                return
            elif text == "💼 Грейд / роль":
                session.step = "update_author_grade"
                session.update_field = "author_grade"
                await message.answer("Введи новый грейд / роль:", reply_markup=types.ReplyKeyboardRemove())
                return
            elif text == "📍 Город":
                session.step = "update_author_city"
                session.update_field = "author_city"
                await message.answer("Введи новый город:", reply_markup=types.ReplyKeyboardRemove())
                return
            elif text == "📝 Интро":
                session.step = "update_author_intro"
                session.update_field = "author_intro"
                await message.answer("Введи новое интро (2–4 предложения):", reply_markup=types.ReplyKeyboardRemove())
                return
            elif text == "📧 Контакты":
                session.step = "update_contacts_menu"
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                keyboard.add("📧 Email")
                keyboard.add("💬 Telegram")
                keyboard.add("💼 LinkedIn")
                keyboard.add("🎨 Dribbble")
                keyboard.add("🖼️ Behance")
                keyboard.add("📄 CV")
                keyboard.add("❌ Отмена")
                await message.answer("Какой контакт обновить?", reply_markup=keyboard)
                return
            elif text == "📸 Фото":
                session.step = "update_author_photo"
                await message.answer("Пришли новое фото:", reply_markup=types.ReplyKeyboardRemove())
                return
        
        # Handle contact update menu
        if session.step == "update_contacts_menu":
            field_map = {
                "📧 Email": "author_email",
                "💬 Telegram": "author_telegram",
                "💼 LinkedIn": "author_linkedin",
                "🎨 Dribbble": "author_dribbble",
                "🖼️ Behance": "author_behance",
                "📄 CV": "author_cv",
            }
            if text in field_map:
                session.update_field = field_map[text]
                session.step = f"update_{field_map[text]}"
                await message.answer(f"Введи новое значение для {text.lower()} (или «-» для удаления):", reply_markup=types.ReplyKeyboardRemove())
                return
        
        # Handle field updates
        if session.step.startswith("update_"):
            field_name = session.update_field
            if not field_name:
                await message.answer("Ошибка: поле не выбрано. Используй /update для начала.")
                return
            
            try:
                if field_name == "author_name":
                    # Ask for surname separately
                    session.step = "update_author_surname"
                    session.profile_data["temp_name"] = text
                    await message.answer("Теперь введи фамилию:")
                    return
                elif field_name in ("author_email", "author_telegram", "author_linkedin", "author_dribbble", "author_behance", "author_cv"):
                    if text == "-":
                        update_hugo_toml_field(
                            token=session.github_token,
                            owner=session.github_username,
                            repo=session.repo_name,
                            field_path=field_name,
                            value="",
                        )
                        await message.answer(f"✅ {field_name} удален!")
                    else:
                        update_hugo_toml_field(
                            token=session.github_token,
                            owner=session.github_username,
                            repo=session.repo_name,
                            field_path=field_name,
                            value=text,
                        )
                        await message.answer(f"✅ {field_name} обновлен!")
                    
                    # Ensure workflow exists and trigger it
                    from .github_client import ensure_workflow_and_trigger
                    workflow_created, workflow_warnings = ensure_workflow_and_trigger(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                    )
                    
                    session.update_mode = False
                    session.update_field = None
                    session.step = "github_username"
                    
                    message_text = "✅ Изменения применены!\n\n"
                    if workflow_warnings:
                        message_text += "\n".join(f"• {w}" for w in workflow_warnings) + "\n\n"
                    message_text += (
                        "⏳ GitHub Actions соберет обновленный сайт через несколько минут.\n"
                        f"Проверить статус: https://github.com/{session.github_username}/{session.repo_name}/actions"
                    )
                    await message.answer(message_text)
                    return
                elif session.step == "update_author_surname":
                    update_hugo_toml_field(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                        field_path="author_name",
                        value=session.profile_data.get("temp_name", ""),
                    )
                    update_hugo_toml_field(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                        field_path="author_surname",
                        value=text,
                    )
                    session.profile_data.pop("temp_name", None)
                    await message.answer("✅ Имя и фамилия обновлены!")
                    # Ensure workflow exists and trigger it
                    from .github_client import ensure_workflow_and_trigger
                    workflow_created, workflow_warnings = ensure_workflow_and_trigger(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                    )
                    
                    session.update_mode = False
                    session.update_field = None
                    session.step = "github_username"
                    
                    message_text = "✅ Изменения применены!\n\n"
                    if workflow_warnings:
                        message_text += "\n".join(f"• {w}" for w in workflow_warnings) + "\n\n"
                    message_text += (
                        "⏳ GitHub Actions соберет обновленный сайт через несколько минут.\n"
                        f"Проверить статус: https://github.com/{session.github_username}/{session.repo_name}/actions"
                    )
                    await message.answer(message_text)
                    return
                else:
                    update_hugo_toml_field(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                        field_path=field_name,
                        value=text,
                    )
                    
                    # Ensure workflow exists and trigger it
                    from .github_client import ensure_workflow_and_trigger
                    workflow_created, workflow_warnings = ensure_workflow_and_trigger(
                        token=session.github_token,
                        owner=session.github_username,
                        repo=session.repo_name,
                    )
                    
                    session.update_mode = False
                    session.update_field = None
                    session.step = "github_username"
                    
                    message_text = f"✅ {field_name} обновлен!\n\n"
                    if workflow_warnings:
                        message_text += "\n".join(f"• {w}" for w in workflow_warnings) + "\n\n"
                    message_text += (
                        "⏳ GitHub Actions соберет обновленный сайт через несколько минут.\n"
                        f"Проверить статус: https://github.com/{session.github_username}/{session.repo_name}/actions"
                    )
                    await message.answer(message_text)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to update field")
                await message.answer(f"❌ Ошибка при обновлении: {exc}")
            return

    # On a fresh chat without /start, guide the user.
    if not session.github_username and session.step == "github_username" and not text:
        await _start_dialog(message)
        return

    if session.step == "github_username":
        session.github_username = text
        
        # Check if THIS user already has a portfolio saved
        repo_info = _load_repo_info()
        user_id_str = str(user_id)
        if user_id_str in repo_info:
            saved_data = repo_info[user_id_str]
            # If saved username matches, use existing repo
            if saved_data.get("github_username") == text:
                session.repo_name = saved_data.get("repo_name")
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                keyboard.add("✅ Использовать существующий")
                keyboard.add("🆕 Создать новый")
                keyboard.add("❌ Отмена")
                
                await message.answer(
                    f"У тебя уже есть портфолио: {text}/{session.repo_name}\n\n"
                    "Что хочешь сделать?",
                    reply_markup=keyboard,
                )
                session.step = "github_username_choice"
                return
        
        session.step = "github_token"
        await message.answer(
            "Теперь пришли GitHub Personal Access Token.\n\n"
            "📋 Как получить токен:\n"
            "1. Перейди на https://github.com/settings/tokens\n"
            "2. Нажми «Generate new token» → «Generate new token (classic)»\n"
            "3. Дай название токену (например, «Portfolio Bot»)\n"
            "4. Выбери срок действия (например, 90 дней)\n"
            "5. Отметь права: ✅ public_repo (обязательно)\n"
            "6. Нажми «Generate token»\n"
            "7. Скопируй токен (он показывается только один раз!)\n\n"
            "⚠️ Токен нужен только для создания репозитория из шаблона "
            "и записи файлов. Мы не храним токен после завершения сессии."
        )
        return
    
    if session.step == "github_username_choice":
        if text == "✅ Использовать существующий":
            # Repo name already set in session from previous step
            session.step = "github_token"
            await message.answer(
                f"Используем существующий репозиторий: {session.github_username}/{session.repo_name}\n\n"
                "Для обновления нужен GitHub токен.\n\n"
                "📋 Как получить токен:\n"
                "1. Перейди на https://github.com/settings/tokens\n"
                "2. Нажми «Generate new token» → «Generate new token (classic)»\n"
                "3. Дай название токену (например, «Portfolio Bot»)\n"
                "4. Выбери срок действия (например, 90 дней)\n"
                "5. Отметь права: ✅ public_repo (обязательно)\n"
                "6. Нажми «Generate token»\n"
                "7. Скопируй токен (он показывается только один раз!)\n\n"
                "Пришли токен:",
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return
        elif text == "🆕 Создать новый":
            # Clear repo_name to create new one
            session.repo_name = None
            session.step = "repo_name"
            await message.answer(
                "Создаем новый репозиторий.\n\n"
                "📝 Как назвать новый репозиторий?\n\n"
                "🔧 Что произойдет:\n"
                "• Бот автоматически создаст репозиторий из шаблона на твоем GitHub\n"
                "• Если репозиторий с таким именем уже существует — бот обновит его\n"
                "• После этого GitHub Actions автоматически соберет и задеплоит сайт\n\n"
                "💡 Примеры названий:\n"
                "• portfolio\n"
                "• izi-portfolio\n"
                "• my-portfolio\n\n"
                "Введи название репозитория:",
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return
        elif text == "❌ Отмена":
            session.step = "github_username"
            session.github_username = None
            session.repo_name = None
            await message.answer("Отменено. Введи GitHub username заново:", reply_markup=types.ReplyKeyboardRemove())
            return

    if session.step == "github_token":
        session.github_token = text
        
        # If repo_name is already set (from existing repo choice), skip to profile
        if session.repo_name:
            session.step = "author_name"
            await message.answer("Отлично. Теперь давай перейдём к профилю.\n\nКак тебя зовут (имя)?")
            return
        
        # Otherwise ask for repo name
        session.step = "repo_name"
        await message.answer(
            "Токен получен ✅\n\n"
            "📝 Теперь придумай название для репозитория портфолио.\n\n"
            "🔧 Что произойдет:\n"
            "• Бот автоматически создаст репозиторий из шаблона на твоем GitHub\n"
            "• Если репозиторий с таким именем уже существует — бот обновит его\n"
            "• После этого GitHub Actions автоматически соберет и задеплоит сайт\n\n"
            "💡 Примеры названий:\n"
            "• portfolio\n"
            "• izi-portfolio\n"
            "• my-portfolio\n\n"
            "⭐ Специальный случай:\n"
            "Если назовешь репозиторий как username.github.io, "
            "сайт будет доступен по адресу https://username.github.io/\n"
            "(вместо https://username.github.io/portfolio/)\n\n"
            "Введи название репозитория:"
        )
        return

    if session.step == "repo_name":
        session.repo_name = text
        session.step = "github_token"
        await message.answer(
            f"Репозиторий будет называться: {text}\n\n"
            "Теперь пришли GitHub Personal Access Token.\n\n"
            "📋 Как получить токен:\n"
            "1. Перейди на https://github.com/settings/tokens\n"
            "2. Нажми «Generate new token» → «Generate new token (classic)»\n"
            "3. Дай название токену (например, «Portfolio Bot»)\n"
            "4. Выбери срок действия (например, 90 дней)\n"
            "5. Отметь права: ✅ public_repo (обязательно)\n"
            "6. Нажми «Generate token»\n"
            "7. Скопируй токен (он показывается только один раз!)\n\n"
            "⚠️ Токен нужен только для создания репозитория из шаблона "
            "и записи файлов. Мы не храним токен после завершения сессии."
        )
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

