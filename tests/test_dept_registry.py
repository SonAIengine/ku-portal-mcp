from ku_portal_mcp.dept_registry import DEFAULT_SITES, list_all_sites, resolve_site


def test_resolve_site_by_default_key():
    site = resolve_site("cs_under")

    assert site == {
        "label": DEFAULT_SITES["cs_under"]["label"],
        "url": DEFAULT_SITES["cs_under"]["url"],
    }


def test_resolve_site_by_partial_label():
    site = resolve_site("컴퓨터학과")

    assert site is not None
    assert site["label"] == DEFAULT_SITES["cs_under"]["label"]


def test_resolve_site_prefers_env_configured_sites(monkeypatch):
    monkeypatch.setenv(
        "KU_DEPT_URLS",
        "테스트학과|https://dept.example.com/notice.do",
    )

    site = resolve_site("테스트학과")

    assert site == {
        "label": "테스트학과",
        "url": "https://dept.example.com/notice.do",
    }


def test_list_all_sites_includes_configured_site_first(monkeypatch):
    monkeypatch.setenv(
        "KU_DEPT_URLS",
        "테스트학과|https://dept.example.com/notice.do",
    )

    sites = list_all_sites()

    assert sites[0] == {
        "label": "테스트학과",
        "url": "https://dept.example.com/notice.do",
    }
    assert any(site["url"] == DEFAULT_SITES["cs_under"]["url"] for site in sites)
