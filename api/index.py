import sys, os, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

debug_info = {
    "cwd": os.getcwd(),
    "python": sys.version,
    "path": sys.path,
    "databases_url": os.environ.get("DATABASE_URL", "(not set)"),
    "vercel_env": os.environ.get("VERCEL_ENV", "(not set)"),
}

try:
    from app import app as application
    app = application
    print("INIT OK", file=sys.stderr)
except Exception as e:
    print("INIT FAILED:", str(e), file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    from flask import Flask
    app = Flask(__name__)
    tb = traceback.format_exc()
    debug_str = "<br>".join(f"<b>{k}:</b> {v}" for k, v in debug_info.items())

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return f"""<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;
border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>
<h2>App Initialization Failed</h2>
{debug_str}
<hr><pre>{tb}</pre></pre>""", 500

upload_dir = app.config.get("UPLOAD_FOLDER", "")
if upload_dir:
    os.makedirs(os.path.join(upload_dir, "avatars"), exist_ok=True)
