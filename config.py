import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(basedir, "instance", "beazt.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    SITE_URL = os.getenv("SITE_URL", "http://localhost:5000")


def get_stripe_config():
    from flask import current_app
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
        "secret_key": _lookup("stripe_secret_key", Config.STRIPE_SECRET_KEY),
        "publishable_key": _lookup("stripe_publishable_key", Config.STRIPE_PUBLISHABLE_KEY),
        "webhook_secret": _lookup("stripe_webhook_secret", Config.STRIPE_WEBHOOK_SECRET),
        "site_url": _lookup("site_url", Config.SITE_URL),
    }


def _db_or_env(key, env_default):
    try:
        val = Setting.get(key)
        if val:
            return val
    except Exception:
        pass
    return env_default
    DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://discord.gg/beazt")
