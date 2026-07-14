import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(24).hex())
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///erp.db")
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")

    # Serverless/Vercel: detect read-only filesystem
    _readonly = False
    try:
        test_path = os.path.join(os.getcwd(), ".vercel_write_test")
        with open(test_path, "w") as f:
            f.write("test")
        os.remove(test_path)
    except (OSError, IOError):
        _readonly = True

    if _readonly:
        if not SQLALCHEMY_DATABASE_URI or "sqlite" in SQLALCHEMY_DATABASE_URI:
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        UPLOAD_FOLDER = "/tmp/uploads"
