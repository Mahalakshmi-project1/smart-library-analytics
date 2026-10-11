import os

DB_HOST = os.getenv("LIBRARY_DB_HOST", "localhost")
DB_PORT = int(os.getenv("LIBRARY_DB_PORT", "3306"))
DB_USER = os.getenv("LIBRARY_DB_USER", "root")
DB_PASSWORD = os.getenv("LIBRARY_DB_PASSWORD", "root123")
DB_NAME = os.getenv("LIBRARY_DB_NAME", "library_db1")
DB_SSL_CA = os.getenv("LIBRARY_DB_SSL_CA", "")

SECRET_KEY = os.getenv("LIBRARY_SECRET_KEY", "smart_library_secret_key_2026")
FINE_PER_DAY = int(os.getenv("LIBRARY_FINE_PER_DAY", "5"))
