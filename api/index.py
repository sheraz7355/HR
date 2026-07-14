import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = None

try:
    from app import app as application
    app = application
except Exception:
    import traceback
    _tb = traceback.format_exc()
    print("FATAL: cannot import app:", _tb, file=sys.stderr)
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return f"<pre>{_tb}</pre>", 500

if app is None:
    from flask import Flask
    app = Flask(__name__)

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return "<h1>App failed to start</h1>", 500

upload_dir = app.config.get("UPLOAD_FOLDER", "")
if upload_dir:
    os.makedirs(os.path.join(upload_dir, "avatars"), exist_ok=True)
