from capture import api_request_dedup_key


def test_dedup_key_ignores_query_values():
    first = api_request_dedup_key("GET", "https://example.com/api/zgqxss/list?page=1&size=10")
    second = api_request_dedup_key("GET", "https://example.com/api/zgqxss/list?page=2&size=10")

    assert first == second


def test_dedup_key_keeps_query_field_set():
    first = api_request_dedup_key("GET", "https://example.com/api/zgqxss/list?page=1")
    second = api_request_dedup_key("GET", "https://example.com/api/zgqxss/list?page=1&status=1")

    assert first != second


def test_dedup_key_ignores_json_body_values():
    first = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/save",
        post_body='{"id": 1, "name": "A", "items": [{"code": "x"}]}',
        headers={"content-type": "application/json"},
    )
    second = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/save",
        post_body='{"id": 2, "name": "B", "items": [{"code": "y"}]}',
        headers={"content-type": "application/json"},
    )

    assert first == second


def test_dedup_key_keeps_json_body_shape():
    first = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/save",
        post_body='{"id": 1, "name": "A"}',
        headers={"content-type": "application/json"},
    )
    second = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/save",
        post_body='{"id": 1, "name": "A", "status": 1}',
        headers={"content-type": "application/json"},
    )

    assert first != second


def test_dedup_key_ignores_form_values():
    first = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/search",
        post_body="keyword=a&page=1",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    second = api_request_dedup_key(
        "POST",
        "https://example.com/api/zgqxss/search",
        post_body="keyword=b&page=2",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert first == second
