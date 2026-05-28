import json
from pathlib import Path

from capture.capture import _storage_state_has_data, load_cookies_from_file
from main import default_cookie_file_for_url


def write_text(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_load_playwright_storage_state(tmp_path):
    cookie_file = write_text(
        tmp_path / "storage_state.json",
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc",
                        "domain": ".example.com",
                        "path": "/",
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            }
        ),
    )

    cookies = load_cookies_from_file(cookie_file, "https://example.com/app")

    assert cookies == [
        {
            "name": "session",
            "value": "abc",
            "domain": ".example.com",
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        }
    ]


def test_default_cookie_file_uses_target_site():
    cookie_file = default_cookie_file_for_url("https://vip.yaozh.com/member")

    assert Path(cookie_file).as_posix() == "config/vip.yaozh.com.storage_state.json"


def test_default_cookie_file_keeps_port_when_present():
    cookie_file = default_cookie_file_for_url("http://localhost:8000/app")

    assert Path(cookie_file).as_posix() == "config/localhost_8000.storage_state.json"


def test_storage_state_has_data_for_cookies_or_local_storage():
    assert _storage_state_has_data({"cookies": [{"name": "sid"}], "origins": []})
    assert _storage_state_has_data(
        {
            "cookies": [],
            "origins": [{"origin": "https://example.com", "localStorage": [{"name": "token"}]}],
        }
    )
    assert not _storage_state_has_data({"cookies": [], "origins": []})


def test_load_simple_cookie_header(tmp_path):
    cookie_file = write_text(tmp_path / "cookie.txt", "sid=123; theme=dark")

    cookies = load_cookies_from_file(cookie_file, "https://example.com/app")

    assert cookies == [
        {"name": "sid", "value": "123", "url": "https://example.com/"},
        {"name": "theme", "value": "dark", "url": "https://example.com/"},
    ]


def test_load_cookie_mapping(tmp_path):
    cookie_file = write_text(
        tmp_path / "cookie.json",
        json.dumps({"sid": "123", "theme": "dark"}),
    )

    cookies = load_cookies_from_file(cookie_file, "https://example.com/app")

    assert cookies == [
        {"name": "sid", "value": "123", "url": "https://example.com/"},
        {"name": "theme", "value": "dark", "url": "https://example.com/"},
    ]


def test_load_netscape_cookies(tmp_path):
    cookie_file = write_text(
        tmp_path / "cookies.txt",
        ".example.com\tTRUE\t/\tFALSE\t1893456000\tsid\t123",
    )

    cookies = load_cookies_from_file(cookie_file, "https://example.com/app")

    assert cookies == [
        {
            "name": "sid",
            "value": "123",
            "domain": ".example.com",
            "path": "/",
            "secure": False,
            "expires": 1893456000,
        }
    ]
