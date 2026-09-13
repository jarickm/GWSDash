import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'coolaire-oneworkspace-secret-key-2026')
    SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE', 'old/credentials-old.json')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'jarick.montojo@coolaireconsolidated.com')
    DB_NAME = os.environ.get('DB_NAME', 'adoption_cache.db')