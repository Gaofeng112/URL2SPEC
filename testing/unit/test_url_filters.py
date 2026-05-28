from capture.capture import is_static_resource
from capture import url_matches_filters


def test_url_filter_matches_path_without_leading_slash():
    assert url_matches_filters(
        "https://example.com/api/zgqxss/list?id=1",
        ["api/zgqxss/*"],
    )


def test_url_filter_matches_path_with_leading_slash():
    assert url_matches_filters(
        "https://example.com/api/zgqxss/list?id=1",
        ["/api/zgqxss/*"],
    )


def test_url_filter_rejects_unmatched_path():
    assert not url_matches_filters(
        "https://example.com/api/other/list",
        ["api/zgqxss/*"],
    )


def test_empty_url_filter_allows_all():
    assert url_matches_filters("https://example.com/api/other/list", [])


def test_url_filter_accepts_comma_separated_string():
    assert url_matches_filters(
        "https://example.com/api/user/profile",
        "api/zgqxss/*, api/user/*",
    )


def test_url_filter_matches_absolute_url():
    assert url_matches_filters(
        "https://api.example.com/api/zgqxss/list",
        ["https://api.example.com/api/zgqxss/*"],
    )


def test_txt_file_is_static_resource():
    assert is_static_resource("https://example.com/static/readme.txt")
