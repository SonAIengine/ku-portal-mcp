"""All-grade retrieval from KUPID / infodepot.

Fetches finalized historical grades, cumulative GPA, and earned credits
from the KUPID "전체성적조회" page.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .auth import Session, PORTAL_BASE, _BROWSER_HEADERS

logger = logging.getLogger(__name__)

INFODEPOT_BASE = "https://infodepot.korea.ac.kr"
MAIN_URL = f"{PORTAL_BASE}/front/Main.kpd"
LOCK_MENU_URL = f"{PORTAL_BASE}/common/User/LockMenu.kpd"
COMPONENT_URL = f"{INFODEPOT_BASE}/portal_layout/component.jsp"
ALL_GRADES_PATH = "/grade/SearchGradeAll.jsp"


@dataclass
class GradeRecord:
    year: str
    term: str
    course_code: str
    course_name: str
    completion_type: str
    course_type: str
    credits: str
    score: str
    grade: str
    gpa: str
    retake_year: str
    retake_term: str
    retake_course: str
    deletion_type: str


@dataclass
class GradeSummary:
    year: str
    term: str
    major_registered_credits: str
    major_earned_credits: str
    prerequisite_earned_credits: str
    research_earned_credits: str
    total_grade_points: str
    official_gpa: str
    overall_gpa: str
    official_converted_score: str
    rank_for_certificate: str


@dataclass
class GradePage:
    available_year_terms: list[dict[str, str]]
    records: list[GradeRecord]
    summaries: list[GradeSummary]


def _portal_cookie(session: Session) -> str:
    return f"ssotoken={session.ssotoken}; PORTAL_SESSIONID={session.portal_session_id};"


def _lock_password() -> str:
    password = os.environ.get("KU_PORTAL_LOCK_PW") or os.environ.get("KU_PORTAL_PW")
    if not password:
        raise RuntimeError("KU_PORTAL_PW 또는 KU_PORTAL_LOCK_PW 환경변수가 필요합니다.")
    return password


async def _establish_grade_session(client: httpx.AsyncClient, session: Session) -> None:
    """Open the protected all-grades page by replaying the KUPID menu flow."""
    portal_cookie = _portal_cookie(session)

    main_resp = await client.get(
        MAIN_URL,
        headers={**_BROWSER_HEADERS, "cookie": portal_cookie},
    )
    main_resp.raise_for_status()
    soup = BeautifulSoup(main_resp.text, "lxml")

    lock_form = soup.find("form", {"id": "_lockMenuForm"})
    gnb_form = soup.find("form", {"id": "gnbForm"})
    if not lock_form or not gnb_form:
        raise RuntimeError("전체성적조회 메뉴 폼을 찾을 수 없습니다.")

    lock_data = {
        inp.get("name"): inp.get("value", "")
        for inp in lock_form.find_all("input")
        if inp.get("name")
    }
    lock_data.update({
        "url": INFODEPOT_BASE,
        "path": ALL_GRADES_PATH,
        "compId": "84",
        "menuCd": "280",
        "_target": "S",
        "compDiv": "S",
        "moveDiv": "moveComp",
        "pw": _lock_password(),
    })

    lock_resp = await client.post(
        LOCK_MENU_URL,
        data=lock_data,
        headers={
            **_BROWSER_HEADERS,
            "cookie": portal_cookie,
            "referer": MAIN_URL,
            "content-type": "application/x-www-form-urlencoded",
        },
    )
    lock_resp.raise_for_status()

    if "var data = 'true'" not in lock_resp.text:
        raise RuntimeError("KUPID 잠금 비밀번호 확인에 실패했습니다.")

    gnb_data = {
        inp.get("name"): inp.get("value", "")
        for inp in gnb_form.find_all("input")
        if inp.get("name")
    }
    gnb_data.update({
        "url": INFODEPOT_BASE,
        "path": ALL_GRADES_PATH,
        "compId": "84",
        "menuCd": "280",
        "_target": "S",
        "language": "ko",
    })

    comp_resp = await client.post(
        COMPONENT_URL,
        data=gnb_data,
        headers={
            **_BROWSER_HEADERS,
            "referer": MAIN_URL,
            "content-type": "application/x-www-form-urlencoded",
        },
        follow_redirects=False,
    )
    if comp_resp.status_code not in (200, 302):
        comp_resp.raise_for_status()

    # component.jsp issues INTR_SESSIONID/intrtoken cookies required for infodepot access.
    if not any(cookie.name == "INTR_SESSIONID" for cookie in client.cookies.jar):
        raise RuntimeError("전체성적조회용 infodepot 세션 생성에 실패했습니다.")


async def fetch_all_grades(session: Session, year_term: str = "") -> GradePage:
    """Fetch finalized all-grade records and cumulative summaries.

    Args:
        session: Valid KUPID session.
        year_term: Optional filter value from the page's `yt` select.
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_grade_session(client, session)

        if year_term:
            resp = await client.post(
                f"{INFODEPOT_BASE}{ALL_GRADES_PATH}",
                data={
                    "yt": year_term,
                    "usertype": "",
                    "languageDiv": "ko",
                },
                headers={
                    **_BROWSER_HEADERS,
                    "referer": f"{INFODEPOT_BASE}{ALL_GRADES_PATH}",
                    "content-type": "application/x-www-form-urlencoded",
                },
            )
        else:
            resp = await client.get(
                f"{INFODEPOT_BASE}{ALL_GRADES_PATH}",
                headers={
                    **_BROWSER_HEADERS,
                    "referer": f"{INFODEPOT_BASE}/portal_layout/main.jsp",
                },
            )

        resp.raise_for_status()

    html = resp.content.decode("euc-kr", errors="replace")
    if "LoginDeny.jsp" in html or "NotValidUser.jsp" in html:
        raise RuntimeError("전체성적조회 페이지 접근에 실패했습니다.")

    return parse_all_grades_html(html)


def parse_all_grades_html(html: str) -> GradePage:
    """Parse the all-grades page HTML into structured records."""
    soup = BeautifulSoup(html, "lxml")

    options = []
    for option in soup.select("select[name='yt'] option"):
        value = (option.get("value") or "").strip()
        label = option.get_text(strip=True)
        if not value:
            continue
        options.append({"value": value, "label": label})

    record_table = _find_table_after_label(soup, "성적확정자료")
    summary_table = _find_table_after_label(soup, "누계성적")

    records = _parse_record_table(record_table)
    summaries = _parse_summary_table(summary_table)

    return GradePage(
        available_year_terms=options,
        records=records,
        summaries=summaries,
    )


def _find_table_after_label(soup: BeautifulSoup, label: str):
    label_el = soup.find(
        lambda tag: tag.name in {"span", "h3", "h4", "th", "strong"}
        and label in tag.get_text(strip=True)
    )
    return label_el.find_next("table") if label_el else None


def _clean_cells(row) -> list[str]:
    return [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]


def _parse_record_table(table) -> list[GradeRecord]:
    if table is None:
        return []

    records: list[GradeRecord] = []
    for row in table.select("tbody tr"):
        cells = _clean_cells(row)
        if len(cells) < 14:
            continue
        records.append(
            GradeRecord(
                year=cells[0],
                term=cells[1],
                course_code=cells[2],
                course_name=cells[3],
                completion_type=cells[4],
                course_type=cells[5],
                credits=cells[6],
                score=cells[7],
                grade=cells[8],
                gpa=cells[9],
                retake_year=cells[10],
                retake_term=cells[11],
                retake_course=cells[12],
                deletion_type=cells[13],
            )
        )
    return records


def _parse_summary_table(table) -> list[GradeSummary]:
    if table is None:
        return []

    summaries: list[GradeSummary] = []
    for row in table.select("tbody tr"):
        cells = _clean_cells(row)
        if len(cells) < 11:
            continue
        summaries.append(
            GradeSummary(
                year=cells[0],
                term=cells[1],
                major_registered_credits=cells[2],
                major_earned_credits=cells[3],
                prerequisite_earned_credits=cells[4],
                research_earned_credits=cells[5],
                total_grade_points=cells[6],
                official_gpa=cells[7],
                overall_gpa=cells[8],
                official_converted_score=cells[9],
                rank_for_certificate=cells[10],
            )
        )
    return summaries
