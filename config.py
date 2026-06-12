import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

_is_vercel = os.environ.get("VERCEL") == "1"

if _is_vercel:
    _db_path = "/tmp/beazt.db"
else:
    _db_path = os.path.join(basedir, "instance", "beazt.db")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + _db_path,
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SELLIX_API_KEY = os.getenv("SELLIX_API_KEY", "")
    SELLIX_WEBHOOK_SECRET = os.getenv("SELLIX_WEBHOOK_SECRET", "")
    SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")
    DISCORD_PUBLIC_URL = os.getenv("DISCORD_PUBLIC_URL", "https://discord.gg/TvxrADZhNR")
    DISCORD_PRIVATE_URL = os.getenv("DISCORD_PRIVATE_URL", "")
    CHAIRFBI_API_TOKEN = os.getenv("CHAIRFBI_API_TOKEN", "")
    CHAIRFBI_API_BASE = os.getenv("CHAIRFBI_API_BASE", "https://access.chairfbi.com")
    LOADER_TOKEN = os.getenv("LOADER_TOKEN", "")
    LOADER_URL = os.getenv("LOADER_URL", "")
    LOADER_PUBLIC_URL = os.getenv("LOADER_PUBLIC_URL", "")
    LOADER_PRIVATE_URL = os.getenv("LOADER_PRIVATE_URL", "")
    IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")


def get_sellix_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "api_key": _lookup("sellix_api_key", Config.SELLIX_API_KEY),
        "webhook_secret": _lookup("sellix_webhook_secret", Config.SELLIX_WEBHOOK_SECRET),
    }


def get_chairfbi_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "api_token": _lookup("chairfbi_api_token", Config.CHAIRFBI_API_TOKEN),
        "api_base": _lookup("chairfbi_api_base", Config.CHAIRFBI_API_BASE),
    }


def get_loader_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "loader_token": _lookup("loader_token", Config.LOADER_TOKEN),
        "loader_url": _lookup("loader_url", Config.LOADER_URL),
        "loader_public_url": _lookup("loader_public_url", Config.LOADER_PUBLIC_URL),
        "loader_private_url": _lookup("loader_private_url", Config.LOADER_PRIVATE_URL),
    }


def get_discord_config():
    from models import Setting

    def _lookup(key, default):
        try:
            val = Setting.get(key)
            if val:
                return val
        except Exception:
            pass
        return default

    return {
        "public_url": _lookup("discord_public_url", Config.DISCORD_PUBLIC_URL),
        "private_url": _lookup("discord_private_url", Config.DISCORD_PRIVATE_URL),
    }
