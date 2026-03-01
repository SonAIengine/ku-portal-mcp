"""Department site registry for Korea University department notice boards.

Manages the mapping between site names/codes and their board URLs.
Sites can be configured via the KU_DEPT_URLS environment variable
or fall back to a built-in default registry.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Built-in registry of known department notice board URLs.
# Keys are short identifiers; used for auto-detection in phase 2.
DEFAULT_SITES: dict[str, dict[str, str]] = {
    "gscit_master": {
        "label": "SW·AI융합대학원(석사)",
        "url": "https://gscit.korea.ac.kr/gscit/board/notice_master.do",
    },
    "gscit_contract": {
        "label": "SW·AI융합대학원(계약)",
        "url": "https://gscit.korea.ac.kr/gscit/board/notice_contract.do",
    },
    "cs_under": {
        "label": "컴퓨터학과(학부)",
        "url": "https://cs.korea.ac.kr/cs/board/notice_under.do",
    },
    "info_grad": {
        "label": "정보대학(대학원)",
        "url": "https://info.korea.ac.kr/info/board/notice_grad.do",
    },
    "edu": {
        "label": "교육학과",
        "url": "https://edu.korea.ac.kr/edu/board/notice.do",
    },
}


def get_configured_sites() -> list[dict[str, str]]:
    """Return the list of configured department sites.

    Priority:
      1. KU_DEPT_URLS env var (format: "라벨|URL,라벨|URL,...")
      2. Empty list if env var is not set

    Returns:
        List of dicts with "label" and "url" keys.
    """
    env_val = os.environ.get("KU_DEPT_URLS", "").strip()
    if not env_val:
        return []

    sites: list[dict[str, str]] = []
    for entry in env_val.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|", 1)
        if len(parts) == 2:
            label, url = parts[0].strip(), parts[1].strip()
            if label and url:
                sites.append({"label": label, "url": url})
        else:
            logger.warning(f"Invalid KU_DEPT_URLS entry (missing '|'): {entry}")

    return sites


def resolve_site(site_name: str) -> dict[str, str] | None:
    """Resolve a site name to its label + URL.

    Searches in order:
      1. Configured sites (env var) — match by label (case-insensitive, partial)
      2. Default registry — match by key or label

    Returns:
        Dict with "label" and "url", or None if not found.
    """
    name_lower = site_name.lower()

    # 1. Check configured sites
    for site in get_configured_sites():
        if name_lower in site["label"].lower() or site["label"].lower() in name_lower:
            return site

    # 2. Check default registry by key
    if name_lower in DEFAULT_SITES:
        entry = DEFAULT_SITES[name_lower]
        return {"label": entry["label"], "url": entry["url"]}

    # 3. Check default registry by label (partial match)
    for entry in DEFAULT_SITES.values():
        if name_lower in entry["label"].lower() or entry["label"].lower() in name_lower:
            return {"label": entry["label"], "url": entry["url"]}

    return None


def list_all_sites() -> list[dict[str, str]]:
    """Return all available sites (configured + defaults).

    Configured sites come first, then defaults not already present.
    """
    configured = get_configured_sites()
    configured_urls = {s["url"] for s in configured}

    result = list(configured)
    for entry in DEFAULT_SITES.values():
        if entry["url"] not in configured_urls:
            result.append({"label": entry["label"], "url": entry["url"]})

    return result
