import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = None
_init_error = ""

try:
    from app import app as application
    app = application
except Exception:
    import traceback
    _init_error = traceback.format_exc()
    print("VERCEL_INIT_ERROR:", _init_error, flush=True, file=sys.stderr)
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return f"<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>{_init_error}</pre>", 500

if app is None:
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return "<h1>App failed to start</h1>", 500

# Uploads are stored in the database (shared/file_store.py), so there is no
# upload folder to prepare on Vercel's read-only filesystem.
