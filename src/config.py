"""Configuration management for AI Internship Application Agent."""
import json
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv, set_key
from pydantic import BaseModel, Field

from src.logger import get_logger

logger = get_logger("config")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
SETTINGS_JSON_PATH = BASE_DIR / "data" / "settings.json"

load_dotenv(ENV_PATH)

TARGET_ROLES_DEFAULT = [
    "AI Engineer",
    "Agentic AI Developer",
    "Generative AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
    "LLM Engineer",
    "Python Developer",
]

TARGET_PLATFORMS_DEFAULT = [
    "LinkedIn",
    "Internshala",
    "Wellfound",
    "Naukri",
    "Indeed",
    "Official Career Page",
]


def _default_persistent_profile_dir() -> str:
    """Resolve a dedicated persistent browser profile directory in a private application-data directory."""
    local_app_data = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    primary = Path(local_app_data) / "AIInternshipAgent" / "browser_profile"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        probe = primary / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return str(primary)
    except Exception:
        fallback = BASE_DIR / "data" / ".appdata_private" / "AIInternshipAgent" / "browser_profile"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback)


class AppSettings(BaseModel):
    """Pydantic settings model representing user and system configurations."""

    ai_provider: str = Field(default="none", description="none, gemini, openai, or groq")
    ai_model: str = Field(default="gemini-2.5-flash")
    use_sentence_transformers: bool = Field(default=False)
    embedding_model: str = Field(default="all-MiniLM-L6-v2")
    database_path: str = Field(default="data/internship_agent.db")
    daily_discovery_limit: int = Field(default=50, ge=1, le=500)
    preferred_roles: List[str] = Field(default_factory=lambda: list(TARGET_ROLES_DEFAULT))
    preferred_locations: List[str] = Field(
        default_factory=lambda: ["Remote", "India", "Bangalore", "Hyderabad", "Pune", "Delhi NCR"]
    )
    enabled_platforms: List[str] = Field(default_factory=lambda: list(TARGET_PLATFORMS_DEFAULT))
    allowed_domains: List[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
            "internshala.com",
            "wellfound.com",
            "naukri.com",
            "greenhouse.io",
            "lever.co",
            "workday.com",
        ]
    )
    prohibited_automation_domains: List[str] = Field(
        default_factory=lambda: [
            "linkedin.com",
            "indeed.com",
            "indeed.co.in",
        ]
    )
    terms_verified_domains: List[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
            "greenhouse.io",
            "lever.co",
            "workday.com",
            "internshala.com",
            "wellfound.com",
            "naukri.com",
        ]
    )
    persistent_profile_dir: str = Field(default_factory=_default_persistent_profile_dir)
    browser_headless: bool = Field(default=False, description="Requirement 2: Run browser in visible mode by default")
    browser_timeout_ms: int = Field(default=15000, ge=2000, le=120000)
    require_human_approval: bool = Field(default=True)
    pause_on_captcha: bool = Field(default=True)
    pause_on_auth: bool = Field(default=True)
    allow_file_upload: bool = Field(default=True)

    # Email Notification Settings (Feature 1)
    email_notifications_enabled: bool = Field(default=True)
    recipient_email: str = Field(default="sauravtiwari2712005@gmail.com")
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_use_tls: bool = Field(default=True)
    email_auth_method: str = Field(default="app_password", description="app_password or oauth2")
    notify_on_submission_success: bool = Field(default=True)
    notify_on_submission_failure: bool = Field(default=True)
    notify_on_awaiting_approval: bool = Field(default=True)
    notify_on_high_match: bool = Field(default=True)
    notify_on_interview_status: bool = Field(default=True)
    high_match_threshold: float = Field(default=80.0, ge=50.0, le=100.0)


def load_settings() -> AppSettings:
    """Load application settings from data/settings.json and environment variables."""
    load_dotenv(ENV_PATH, override=True)

    roles_env = os.getenv("DEFAULT_ROLES", "")
    roles_list = [r.strip() for r in roles_env.split(",") if r.strip()] or list(TARGET_ROLES_DEFAULT)

    locs_env = os.getenv("DEFAULT_LOCATIONS", "")
    locs_list = [l.strip() for l in locs_env.split(",") if l.strip()] or [
        "Remote",
        "India",
        "Bangalore",
        "Hyderabad",
        "Pune",
        "Delhi NCR",
    ]

    domains_env = os.getenv("ALLOWED_DOMAINS", "")
    domains_list = [d.strip() for d in domains_env.split(",") if d.strip()] or [
        "localhost",
        "127.0.0.1",
        "internshala.com",
        "wellfound.com",
        "naukri.com",
        "greenhouse.io",
        "lever.co",
        "workday.com",
    ]

    settings_data = {
        "ai_provider": os.getenv("AI_PROVIDER", "none").lower(),
        "ai_model": os.getenv("AI_MODEL", "gemini-2.5-flash"),
        "use_sentence_transformers": os.getenv("USE_SENTENCE_TRANSFORMERS", "false").lower() == "true",
        "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "database_path": os.getenv("DATABASE_PATH", "data/internship_agent.db"),
        "daily_discovery_limit": int(os.getenv("DAILY_DISCOVERY_LIMIT", "50")),
        "preferred_roles": roles_list,
        "preferred_locations": locs_list,
        "enabled_platforms": list(TARGET_PLATFORMS_DEFAULT),
        "allowed_domains": domains_list,
        "persistent_profile_dir": os.getenv("BROWSER_PROFILE_DIR", _default_persistent_profile_dir()),
        "browser_headless": os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
        "browser_timeout_ms": int(os.getenv("BROWSER_TIMEOUT_MS", "15000")),
        "require_human_approval": True,  # Enforced always true for safety
        "pause_on_captcha": os.getenv("PAUSE_ON_CAPTCHA", "true").lower() == "true",
        "pause_on_auth": os.getenv("PAUSE_ON_AUTH", "true").lower() == "true",
        "allow_file_upload": True,
        "email_notifications_enabled": os.getenv("EMAIL_NOTIFICATIONS_ENABLED", "true").lower() == "true",
        "recipient_email": os.getenv("RECIPIENT_EMAIL", "sauravtiwari2712005@gmail.com"),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        "email_auth_method": os.getenv("EMAIL_AUTH_METHOD", "app_password"),
        "notify_on_submission_success": os.getenv("NOTIFY_ON_SUBMISSION_SUCCESS", "true").lower() == "true",
        "notify_on_submission_failure": os.getenv("NOTIFY_ON_SUBMISSION_FAILURE", "true").lower() == "true",
        "notify_on_awaiting_approval": os.getenv("NOTIFY_ON_AWAITING_APPROVAL", "true").lower() == "true",
        "notify_on_high_match": os.getenv("NOTIFY_ON_HIGH_MATCH", "true").lower() == "true",
        "notify_on_interview_status": os.getenv("NOTIFY_ON_INTERVIEW_STATUS", "true").lower() == "true",
    }

    if SETTINGS_JSON_PATH.exists():
        try:
            with open(SETTINGS_JSON_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings_data.update(saved)
            settings_data["require_human_approval"] = True
        except Exception as exc:
            logger.warning("Could not load settings.json: %s", exc)

    return AppSettings(**settings_data)


def save_settings(settings: AppSettings, api_keys: dict | None = None) -> None:
    """Persist settings to data/settings.json and update .env safely."""
    settings.require_human_approval = True
    SETTINGS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(settings.model_dump(), f, indent=2)

    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")

    try:
        set_key(str(ENV_PATH), "AI_PROVIDER", settings.ai_provider)
        set_key(str(ENV_PATH), "AI_MODEL", settings.ai_model)
        set_key(str(ENV_PATH), "USE_SENTENCE_TRANSFORMERS", str(settings.use_sentence_transformers).lower())
        set_key(str(ENV_PATH), "DAILY_DISCOVERY_LIMIT", str(settings.daily_discovery_limit))
        set_key(str(ENV_PATH), "DEFAULT_ROLES", ",".join(settings.preferred_roles))
        set_key(str(ENV_PATH), "DEFAULT_LOCATIONS", ",".join(settings.preferred_locations))
        set_key(str(ENV_PATH), "ALLOWED_DOMAINS", ",".join(settings.allowed_domains))
        set_key(str(ENV_PATH), "BROWSER_HEADLESS", str(settings.browser_headless).lower())
        set_key(str(ENV_PATH), "EMAIL_NOTIFICATIONS_ENABLED", str(settings.email_notifications_enabled).lower())
        set_key(str(ENV_PATH), "RECIPIENT_EMAIL", settings.recipient_email)
        set_key(str(ENV_PATH), "SMTP_HOST", settings.smtp_host)
        set_key(str(ENV_PATH), "SMTP_PORT", str(settings.smtp_port))
        set_key(str(ENV_PATH), "SMTP_USE_TLS", str(settings.smtp_use_tls).lower())
        set_key(str(ENV_PATH), "EMAIL_AUTH_METHOD", settings.email_auth_method)

        if api_keys:
            for key_name, key_val in api_keys.items():
                if key_val is not None and key_val.strip():
                    set_key(str(ENV_PATH), key_name, key_val.strip())
                    os.environ[key_name] = key_val.strip()
    except Exception as exc:
        logger.warning("Failed to update .env file: %s", exc)

    logger.info("Application settings saved successfully.")
