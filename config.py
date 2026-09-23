import os
from datetime import timedelta


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "mysql+pymysql://parking_user:change-me@localhost/parking_management"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.getenv("SESSION_MINUTES", "60")))
    WTF_CSRF_TIME_LIMIT = timedelta(hours=1)
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "10"))
    RESET_TOKEN_MINUTES = int(os.getenv("RESET_TOKEN_MINUTES", "30"))
    FACILITY_NAME = os.getenv("FACILITY_NAME", "ParkFlow Parking Facility")
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.invalid")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-before-deployment")
    SESSION_COOKIE_SECURE = False


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "testing-secret-key-not-for-production"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        secret = cls.SECRET_KEY
        if not secret or len(secret) < 32 or secret.startswith("dev-") or "replace-with" in secret:
            raise RuntimeError("Production SECRET_KEY must be a random value of at least 32 characters.")
        if "change-me" in cls.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("Production DATABASE_URL must be configured.")
        if cls.RATELIMIT_STORAGE_URI == "memory://":
            raise RuntimeError("Production RATELIMIT_STORAGE_URI must use a shared backend such as Redis.")


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
