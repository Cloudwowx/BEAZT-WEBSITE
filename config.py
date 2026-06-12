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
    SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")
    DISCORD_PUBLIC_URL = os.getenv("DISCORD_PUBLIC_URL", "https://discord.gg/bU4tFA43KK")
    DISCORD_PRIVATE_URL = os.getenv("DISCORD_PRIVATE_URL", "")
    CHAIRFBI_API_TOKEN = os.getenv("CHAIRFBI_API_TOKEN", "")
    CHAIRFBI_API_BASE = os.getenv("CHAIRFBI_API_BASE", "https://access.chairfbi.com")
    LOADER_TOKEN = os.getenv("LOADER_TOKEN", "")
    LOADER_URL = os.getenv("LOADER_URL", "")
    IVNO_API_KEY = os.getenv("IVNO_API_KEY", "")
    IVNO_API_SECRET = os.getenv("IVNO_API_SECRET", "")
    IVNO_BASE_URL = os.getenv("IVNO_BASE_URL", "https://app.ivno.io/api/ivno/v1")
    LOADER_PUBLIC_URL = os.getenv("LOADER_PUBLIC_URL", "")
    LOADER_PRIVATE_URL = os.getenv("LOADER_PRIVATE_URL", "")
    IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")


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
    }


def get_ivno_config():
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
        "api_key": _lookup("ivno_api_key", Config.IVNO_API_KEY),
        "api_secret": _lookup("ivno_api_secret", Config.IVNO_API_SECRET),
        "base_url": _lookup("ivno_base_url", Config.IVNO_BASE_URL),
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
