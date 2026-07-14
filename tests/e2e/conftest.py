import pytest
import subprocess
import time
import socket
import sys
from pathlib import Path

BASE_URL = "http://localhost:5000"
HR_PROJECT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def flask_server():
    proc = subprocess.Popen(
        [sys.executable, "run_local.py"],
        cwd=str(HR_PROJECT),
        env={"DATABASE_URL": "sqlite:///e2e_test.db", "FLASK_ENV": "testing"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for i in range(60):
        time.sleep(2)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", 5000))
            s.close()
            break
        except ConnectionRefusedError:
            s.close()
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=5)
        raise RuntimeError(f"Flask server did not start\nSTDOUT: {out.decode(errors='replace')[:500]}\nSTDERR: {err.decode(errors='replace')[:500]}")
    yield
    proc.terminate()
    proc.wait()


@pytest.fixture
def login_page(page, flask_server):
    page.goto(f"{BASE_URL}/auth/login")
    return page


@pytest.fixture
def admin_page(page, flask_server):
    page.goto(f"{BASE_URL}/auth/login")
    page.fill("#email", "admin@solarkon.com")
    page.fill("#password", "admin123")
    page.click("button[type='submit']")
    page.wait_for_url("**/dashboard/**")
    return page


@pytest.fixture
def hr_user_page(page, flask_server):
    page.goto(f"{BASE_URL}/auth/login")
    page.fill("#email", "emp@solarkon.com")
    page.fill("#password", "emp123")
    page.click("button[type='submit']")
    page.wait_for_url("**/dashboard/**")
    return page


@pytest.fixture
def mobile_page(page, flask_server):
    page.set_viewport_size({"width": 375, "height": 812})
    return page


@pytest.fixture
def admin_mobile(browser, flask_server):
    ctx = browser.new_context(viewport={"width": 375, "height": 812})
    p = ctx.new_page()
    p.goto(f"{BASE_URL}/auth/login")
    p.fill("#email", "admin@solarkon.com")
    p.fill("#password", "admin123")
    p.click("button[type='submit']")
    p.wait_for_url("**/dashboard/**")
    yield p
    ctx.close()
