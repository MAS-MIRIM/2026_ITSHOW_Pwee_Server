import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///memory"

    # Flask-Mail
    MAIL_SERVER   = os.getenv("MAILER_HOST")
    MAIL_PORT     = int(os.getenv("MAILER_PORT", 0))
    MAIL_USE_TLS  = os.getenv("MAILER_TLS", "false").lower() == "true"
    MAIL_USE_SSL  = os.getenv("MAILER_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.getenv("MAILER_USER")
    MAIL_PASSWORD = os.getenv("MAILER_PASS")
    MAIL_DEFAULT_SENDER = os.getenv("MAILER_FROM")

class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}

def get_config():
    env = os.getenv("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
