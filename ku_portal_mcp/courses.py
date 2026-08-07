"""Course search and syllabus retrieval from KUPID/infodepot.

Accesses infodepot.korea.ac.kr via SSO token handoff.
Requires valid KUPID session.
"""

import asyncio
import re
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .academic import resolve_year_semester
from .auth import Session, PORTAL_BASE, _BROWSER_HEADERS

logger = logging.getLogger(__name__)

INFODEPOT_BASE = "https://infodepot.korea.ac.kr"

# Undergraduate college codes (Seoul campus)
COLLEGE_CODES = {
    "0140": "경영대학",
    "0143": "문과대학",
    "4652": "생명과학대학",
    "0197": "정경대학",
    "0209": "이과대학",
    "0217": "공과대학",
    "0226": "의과대학",
    "0234": "사범대학",
    "0231": "간호대학",
    "5720": "정보대학",
    "5338": "디자인조형학부",
    "7325": "미디어대학",
    "4669": "보건과학대학",
    "6726": "스마트보안학부",
    "3645": "학생군사교육단",
    "6458": "법학전문대학원(학부관)",
    "7094": "스마트모빌리티학부",
    "6564": "심리학부",
    "6909": "국제대학",
    "5959": "교직팀",
    "7349": "학부대학",
    "7157": "현장실습지원센터",
}

# Graduate college codes
GRAD_COLLEGE_CODES = {
    "0309": "대학원",
    "7334": "정부학연구소",
    "0380": "경영대학원",
    "0390": "교육대학원",
    "4027": "생명환경과학대학원",
    "0454": "정책대학원",
    "4259": "공학대학원",
    "6943": "창업경영대학원",
    "0527": "경영정보대학원",
    "0478": "국제대학원",
    "0491": "언론대학원",
    "0501": "노동대학원",
    "0508": "법무대학원",
    "4720": "컴퓨터정보통신대학원",
    "6382": "문화스포츠대학원",
    "0538": "인문정보대학원",
    "0544": "행정대학원",
    "3411": "보건대학원",
    "3412": "임상치의학대학원",
    "6951": "융합과학대학원",
    "3474": "의용과학대학원",
    "4877": "정보경영공학전문대학원",
    "5321": "정보보호대학원",
    "4745": "경영전문대학원",
    "5127": "법학전문대학원",
    "5078": "의학전문대학원",
    "5258": "융합소프트웨어전문대학원",
    "5263": "그린스쿨대학원",
    "5332": "기술경영전문대학원",
    "6608": "에너지환경대학원(그린스쿨)",
    "5534": "KU-KIST융합대학원",
    "6266": "행정전문대학원",
    "6572": "미디어대학원",
    "7150": "심리융합과학대학원",
    "7294": "융합데이터과학대학원",
    "7297": "개인정보보호대학원",
    "7298": "SW·AI융합대학원",
    "7406": "임상간호대학원",
}

# Period -> (start, end) HH:MM mapping (Korea University standard)
PERIOD_TIMES = {
    "1": ("09:00", "10:15"),
    "2": ("10:30", "11:45"),
    "3": ("12:00", "13:15"),
    "4": ("13:30", "14:45"),
    "5": ("15:00", "16:15"),
    "6": ("16:30", "17:45"),
    "7": ("18:00", "18:50"),
    "8": ("19:00", "19:50"),
    "9": ("20:00", "20:50"),
    "10": ("21:00", "21:50"),
    "11": ("22:00", "22:50"),
}

# Schedule string token: '월(7-8) 애기능생활관 301호' or concatenated '월(7-8) ...수(7-8) ...'.
# Captures (day, periods, location) up to the next day-token or end of string.
_SCHEDULE_TOKEN_RE = re.compile(
    r"([월화수목금토일])\((\d+(?:-\d+)?)\)\s*"
    r"([^월화수목금토일\s][^월화수목금토일]*?)"
    r"(?=[월화수목금토일]\(|\Z)"
)

TERM_CODES = {
    "1": "1R",
    "summer": "1S",
    "2": "2R",
    "winter": "2W",
}


@dataclass
class ScheduleSlot:
    """One day/period/location slot inside a course schedule string."""

    day: str  # 월/화/수/목/금/토/일
    periods: str  # "1" or "7-8"
    location: str  # "애기능생활관 301호"
    start_time: str  # "18:00"
    end_time: str  # "19:50"


def parse_schedule(schedule: str) -> list[ScheduleSlot]:
    """Parse a course schedule string into structured slots.

    Examples:
        "월(7-8) 애기능생활관 301호" -> 1 slot
        "월(2) 정보통신관 604호수(2) 정보통신관 604호" -> 2 slots
        "" -> []
    """
    slots: list[ScheduleSlot] = []
    if not schedule:
        return slots
    for m in _SCHEDULE_TOKEN_RE.finditer(schedule):
        day, periods, location = m.group(1), m.group(2), m.group(3).strip()
        parts = re.split(r"[-~]", periods)
        start = PERIOD_TIMES.get(parts[0], ("", ""))[0]
        end = PERIOD_TIMES.get(parts[-1], ("", ""))[1]
        slots.append(
            ScheduleSlot(
                day=day,
                periods=periods,
                location=location,
                start_time=start,
                end_time=end,
            )
        )
    return slots


@dataclass
class RoomScheduleEntry:
    """One scheduled course occupying a room at a specific time."""

    course_code: str
    section: str
    course_name: str
    professor: str
    department: str
    college: str
    source: str  # "학부" or "대학원"
    day: str
    periods: str
    location: str
    start_time: str
    end_time: str


@dataclass
class CourseInfo:
    campus: str
    course_code: str
    section: str
    course_type: str
    course_name: str
    professor: str
    credits: str
    schedule: str


@dataclass
class EnrolledCourse:
    course_code: str  # e.g. AAI110
    section: str  # e.g. 00
    course_type: str  # e.g. 전공선택
    course_name: str  # e.g. 딥러닝
    professor: str  # e.g. 석흥일
    credits: str  # e.g. 2(2)
    schedule: str  # e.g. 월(7-8) 애기능생활관 301호
    retake: bool  # 재수강여부
    status: str  # e.g. 신청
    grad_code: str  # e.g. 7298 (for syllabus link)
    dept_code: str  # e.g. 7313 (for syllabus link)


async def _establish_infodepot_session(
    client: httpx.AsyncClient, session: Session
) -> None:
    """Establish session on infodepot via SSO token handoff."""
    await client.get(
        f"{INFODEPOT_BASE}/session.jsp",
        params={"token": session.ssotoken, "orgtoken": session.ssotoken},
        headers={**_BROWSER_HEADERS, "referer": f"{PORTAL_BASE}/front/Component.kpd"},
        follow_redirects=True,
    )


async def _fetch_dept_popup(
    client: httpx.AsyncClient,
    college_code: str,
    year: str,
    term_code: str,
    *,
    is_grad: bool,
) -> list[dict]:
    """Fetch department list popup (학부=frm_ms / 대학원=frm_gms)."""
    frm = "frm_gms" if is_grad else "frm_ms"
    referer_jsp = "LecGradMajorSub.jsp" if is_grad else "LecMajorSub.jsp"

    resp = await client.get(
        f"{INFODEPOT_BASE}/lecture/LecDeptPopup.jsp",
        params={
            "frm": frm,
            "colcd": college_code,
            "deptcd": "",
            "dept": "dept",
            "year": year,
            "term": term_code,
            "languageDiv": "ko",
        },
        headers={
            **_BROWSER_HEADERS,
            "referer": f"{INFODEPOT_BASE}/lecture/{referer_jsp}",
        },
    )
    html = resp.content.decode("euc-kr", errors="replace")
    values = re.findall(r'el\.value\s*=\s*"(\w+)"', html)
    texts = re.findall(r'el\.text\s*=\s*"([^"]+)"', html)
    return [{"code": v, "name": t.strip()} for v, t in zip(values, texts)]


async def fetch_departments(
    session: Session,
    college_code: str,
    year: str | None = None,
    term: str | None = None,
    *,
    is_grad: bool = False,
) -> list[dict]:
    """Fetch department list for a college (undergraduate by default)."""
    year, term = resolve_year_semester(year, term)
    term_code = TERM_CODES.get(term, term)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)
        return await _fetch_dept_popup(
            client, college_code, year, term_code, is_grad=is_grad
        )


async def search_courses(
    session: Session,
    year: str | None = None,
    semester: str | None = None,
    campus: str = "1",
    college: str = "",
    department: str = "",
) -> list[CourseInfo]:
    """Search courses by college/department.

    Args:
        session: Valid KUPID session.
        year: Academic year (e.g., "2027").
        semester: "1", "2", "summer", "winter".
        campus: "1" (Seoul) or "2" (Sejong).
        college: College code (e.g., "5720" for 정보대학).
        department: Department code (e.g., "5722" for 컴퓨터학과).

    Returns:
        List of CourseInfo objects.
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            params={
                "yy": year,
                "tm": term_code,
                "sCampus": campus,
                "col": college,
                "dept": department,
                "listSub": "Y",
                "es": "",
            },
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_course_table(html)


def _parse_course_table(html: str) -> list[CourseInfo]:
    """Parse course search results HTML table."""
    soup = BeautifulSoup(html, "lxml")
    courses = []

    # Find the results table (the one with >2 rows)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        # Skip header row
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            courses.append(
                CourseInfo(
                    campus=cells[0],
                    course_code=cells[1],
                    section=cells[2],
                    course_type=cells[3],
                    course_name=cells[4],
                    professor=cells[5],
                    credits=cells[6],
                    schedule=cells[7],
                )
            )

    return courses


async def search_grad_courses(
    session: Session,
    year: str | None = None,
    semester: str | None = None,
    campus: str = "1",
    college: str = "",
    department: str = "",
) -> list[CourseInfo]:
    """Search graduate courses (대학원 개설과목).

    Same params as `search_courses` but hits LecGradMajorSub.jsp,
    which has a different column layout (no campus column).
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/LecGradMajorSub.jsp",
            params={
                "yy": year,
                "tm": term_code,
                "sCampus": campus,
                "col": college,
                "dept": department,
                "listSub": "Y",
                "es": "",
            },
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecGradMajorSub.jsp",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_grad_course_table(
        html, default_campus="서울" if campus == "1" else "세종"
    )


def _parse_grad_course_table(
    html: str, default_campus: str = "서울"
) -> list[CourseInfo]:
    """Parse graduate course HTML table.

    Column layout (no campus column):
      [0]학수번호 [1]분반 [2]이수구분 [3]교과목명 [4]담당교수
      [5]학점(시간) [6]강의시간 [7]교환학생 [8]유연학기
    """
    soup = BeautifulSoup(html, "lxml")
    courses: list[CourseInfo] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 7:
                continue
            if not cells[0]:  # blank spacer rows
                continue
            courses.append(
                CourseInfo(
                    campus=default_campus,
                    course_code=cells[0],
                    section=cells[1],
                    course_type=cells[2],
                    course_name=cells[3],
                    professor=cells[4],
                    credits=cells[5],
                    schedule=cells[6],
                )
            )
    return courses


def _normalize_label(s: str) -> str:
    """Strip whitespace for forgiving substring matching ('애기능 301' vs '애기능생활관301호')."""
    return re.sub(r"\s+", "", s)


async def find_room_schedule(
    session: Session,
    building: str,
    room: str = "",
    day: str = "",
    year: str | None = None,
    semester: str | None = None,
    campus: str = "1",
    include_grad: bool = True,
    concurrency: int = 10,
) -> list[RoomScheduleEntry]:
    """Find all scheduled courses for a given building/room/day.

    Strategy: fetch every (college, department) course list (학부 + 대학원),
    parse each course's schedule string into slots, and filter by building/room/day.

    Args:
        session: Valid KUPID session.
        building: Building name partial match, e.g. "애기능" matches "애기능생활관".
        room: Room number partial match, e.g. "301" matches "301호" or "B301".
        day: Day filter — "월"/"화"/.../"일", or "" for all weekdays.
        year, semester: Defaults to current academic term.
        campus: "1" Seoul, "2" Sejong.
        include_grad: Also search graduate courses.
        concurrency: Parallel HTTP fan-out cap.

    Returns:
        Time-sorted, deduped list of RoomScheduleEntry.
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)

    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        async def _depts(col: str, is_grad: bool) -> tuple[str, bool, list[dict]]:
            async with sem:
                try:
                    deps = await _fetch_dept_popup(
                        client, col, year, term_code, is_grad=is_grad
                    )
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning(f"dept popup failed col={col}: {e}")
                    deps = []
                return col, is_grad, deps

        dept_jobs = [_depts(col, False) for col in COLLEGE_CODES]
        if include_grad:
            dept_jobs += [_depts(col, True) for col in GRAD_COLLEGE_CODES]
        dept_results = await asyncio.gather(*dept_jobs)

        async def _list(
            jsp: str, col: str, dept: str, dept_name: str, college_name: str, src: str
        ) -> list[tuple[CourseInfo, str, str, str]]:
            async with sem:
                try:
                    resp = await client.get(
                        f"{INFODEPOT_BASE}/lecture/{jsp}",
                        params={
                            "yy": year,
                            "tm": term_code,
                            "sCampus": campus,
                            "col": col,
                            "dept": dept,
                            "listSub": "Y",
                            "es": "",
                        },
                        headers={
                            **_BROWSER_HEADERS,
                            "referer": f"{INFODEPOT_BASE}/lecture/{jsp}",
                        },
                    )
                    html = resp.content.decode("euc-kr", errors="replace")
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning(f"course list failed {jsp} {col}/{dept}: {e}")
                    return []
                if jsp == "LecGradMajorSub.jsp":
                    parsed = _parse_grad_course_table(html)
                else:
                    parsed = _parse_course_table(html)
                return [(c, dept_name, college_name, src) for c in parsed]

        list_jobs = []
        for col, is_grad, deps in dept_results:
            jsp = "LecGradMajorSub.jsp" if is_grad else "LecMajorSub.jsp"
            college_name = (
                GRAD_COLLEGE_CODES.get(col) if is_grad else COLLEGE_CODES.get(col)
            ) or col
            src = "대학원" if is_grad else "학부"
            for d in deps:
                list_jobs.append(
                    _list(jsp, col, d["code"], d["name"], college_name, src)
                )

        chunks = await asyncio.gather(*list_jobs)

    nb = _normalize_label(building)
    nr = _normalize_label(room) if room else ""
    day_filter = day.strip() or ""

    entries: list[RoomScheduleEntry] = []
    seen: set[tuple[str, str, str, str]] = set()
    for chunk in chunks:
        for course, dept_name, college_name, src in chunk:
            for slot in parse_schedule(course.schedule):
                if day_filter and slot.day != day_filter:
                    continue
                loc = _normalize_label(slot.location)
                if nb not in loc:
                    continue
                if nr and nr not in loc:
                    continue
                key = (course.course_code, course.section, slot.day, slot.periods)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    RoomScheduleEntry(
                        course_code=course.course_code,
                        section=course.section,
                        course_name=course.course_name,
                        professor=course.professor,
                        department=dept_name,
                        college=college_name,
                        source=src,
                        day=slot.day,
                        periods=slot.periods,
                        location=slot.location,
                        start_time=slot.start_time,
                        end_time=slot.end_time,
                    )
                )

    _DAY_ORDER = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
    entries.sort(key=lambda e: (_DAY_ORDER.get(e.day, 9), e.start_time or "99:99"))
    return entries


async def fetch_syllabus(
    session: Session,
    course_code: str,
    section: str = "00",
    year: str | None = None,
    semester: str | None = None,
    grad_code: str = "",
) -> str:
    """Fetch syllabus (강의계획서) for a course.

    Strategy:
    1. Try AllgenNoX.jsp -> extract Allgen report URL
    2. If Allgen redirect found, try direct report server access
    3. Fallback: search course listing pages for course info

    Args:
        session: Valid KUPID session.
        course_code: Course code (e.g., "COSE101").
        section: Section/class number (e.g., "02").
        year: Academic year.
        semester: "1", "2", "summer", "winter".
        grad_code: Graduate code (usually empty for undergrad).

    Returns:
        Syllabus text content.
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        # Step 1: Try AllgenNoX.jsp
        resp = await client.get(
            f"{INFODEPOT_BASE}/common/AllgenNoX.jsp",
            params={
                "flag": "LecPlan",
                "courcd": course_code,
                "courcls": section,
                "year": year,
                "term": term_code,
                "gradcd": grad_code,
            },
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

        # Step 2: If Allgen redirect, try direct report server access
        report_match = re.search(r"PrintObj\('(.+?)','(http[^']+)'\)", html)
        if report_match:
            report_content = await _try_allgen_report(client, report_match)
            if report_content:
                return report_content

            # Step 3: Fallback to course listing search
            course_info = await _search_course_info(
                client,
                course_code,
                section,
                year,
                term_code,
            )
            if course_info:
                return course_info

            # Final fallback: return extracted params
            return _format_allgen_params(report_match.group(1))

    return _parse_syllabus_html(html)


async def _try_allgen_report(
    client: httpx.AsyncClient,
    report_match: re.Match,
) -> str | None:
    """Try to directly fetch from Allgen report server (campus network only)."""
    params_str = report_match.group(1)
    report_url = report_match.group(2)

    pairs = re.findall(r"\[:(\w+)\]=([^\[]*)", params_str)
    form_data = {key: val for key, val in pairs}

    try:
        resp = await client.post(
            report_url,
            data=form_data,
            headers={
                **_BROWSER_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
            },
            timeout=10.0,
        )
        if resp.status_code == 200 and len(resp.content) > 200:
            content_type = resp.headers.get("content-type", "")
            if "euc-kr" in content_type.lower():
                text = resp.content.decode("euc-kr", errors="replace")
            else:
                try:
                    text = resp.content.decode("utf-8")
                except UnicodeDecodeError:
                    text = resp.content.decode("euc-kr", errors="replace")
            return _parse_report_html(text)
    except (httpx.HTTPError, httpx.ConnectError, OSError) as e:
        logger.debug(f"Allgen report server not accessible: {e}")

    return None


# Course code prefix -> (college_code, department_code, is_grad)
_PREFIX_TO_DEPT: dict[str, tuple[str, str, bool]] = {
    # 경영대학
    "BUSS": ("0140", "0142", False),
    "HMB": ("0140", "0142", False),
    # 문과대학
    "COLA": ("0143", "4067", False),
    "KORE": ("0143", "0145", False),
    "ENGL": ("0143", "0146", False),
    "PHIL": ("0143", "0147", False),
    "HOKA": ("0143", "0148", False),
    "HOEW": ("0143", "0803", False),
    "SOCI": ("0143", "0152", False),
    "GERM": ("0143", "0153", False),
    "FRAN": ("0143", "0154", False),
    "CHIN": ("0143", "0155", False),
    "RUSS": ("0143", "0156", False),
    "JAPN": ("0143", "0157", False),
    "SPAN": ("0143", "0158", False),
    "HANM": ("0143", "0159", False),
    "LING": ("0143", "4391", False),
    "LALW": ("0143", "5539", False),
    "MHUM": ("0143", "6342", False),
    "EMLA": ("0143", "5672", False),
    "LBNC": ("0143", "6093", False),
    "HMCI": ("0143", "6094", False),
    "GLEA": ("0143", "6095", False),
    "UNIP": ("0143", "6463", False),
    "HUSS": ("0143", "7284", False),
    # 생명과학대학
    "LIBS": ("4652", "4653", False),
    "LIBT": ("4652", "4654", False),
    "LIET": ("4652", "4656", False),
    "LESE": ("4652", "4657", False),
    "LESF": ("4652", "4425", False),
    "LIST": ("4652", "4719", False),
    "CCST": ("4652", "5186", False),
    "LIFS": ("4652", "5564", False),
    # 정경대학
    "POLI": ("0197", "0199", False),
    "ECON": ("0197", "0200", False),
    "STAT": ("0197", "0201", False),
    "PAPP": ("0197", "0203", False),
    "FNEG": ("0197", "5046", False),
    # 이과대학
    "MATH": ("0209", "0211", False),
    "PHYS": ("0209", "0212", False),
    "CHEM": ("0209", "0213", False),
    "EAES": ("0209", "0215", False),
    # 공과대학
    "EGRN": ("0217", "4065", False),
    "KECE": ("0217", "5597", False),
    "CHBE": ("0217", "4084", False),
    "SEMI": ("0217", "6723", False),
    "KMSE": ("0217", "4630", False),
    "IMEN": ("0217", "5320", False),
    "MECH": ("0217", "4952", False),
    "ARCH": ("0217", "4887", False),
    "ACEE": ("0217", "5204", False),
    "ENGY": ("0217", "6724", False),
    "COMM": ("0217", "7076", False),
    "NEIK": ("0217", "7055", False),
    "TEEN": ("0217", "6544", False),
    "ECOC": ("0217", "7282", False),
    "KISE": ("0217", "7414", False),
    # 의과대학
    "PMED": ("0226", "0228", False),
    "MEDI": ("0226", "0229", False),
    # 사범대학
    "EDUC": ("0234", "0236", False),
    "PHEK": ("0234", "0237", False),
    "SAEK": ("0234", "0237", False),
    "HEED": ("0234", "0238", False),
    "MATE": ("0234", "0239", False),
    "KLLE": ("0234", "0240", False),
    "ELED": ("0234", "0241", False),
    "GEOG": ("0234", "0242", False),
    "HISE": ("0234", "0243", False),
    "FADM": ("0234", "4638", False),
    "MUKE": ("0234", "5753", False),
    # 간호대학
    "NRSG": ("0231", "0233", False),
    # 정보대학
    "COSE": ("5720", "5722", False),
    "DATA": ("5720", "6725", False),
    "CSAI": ("5720", "7343", False),
    "BNCS": ("5720", "6666", False),
    "ISEC": ("5720", "5944", False),
    "STEP": ("5720", "5965", False),
    # 디자인조형학부
    "ARDE": ("5338", "5339", False),
    # 미디어대학
    "JMCO": ("7325", "7326", False),
    "GMES": ("7325", "7327", False),
    # 보건과학대학
    "BMED": ("4669", "5693", False),
    "BSMS": ("4669", "5694", False),
    "KHES": ("4669", "5695", False),
    "KHPM": ("4669", "5696", False),
    # 스마트보안학부
    "SMRT": ("6726", "6727", False),
    "CYDF": ("6726", "6880", False),
    "DTPR": ("6726", "7283", False),
    # 대학원 — SW·AI융합대학원
    "AAI": ("7298", "7313", True),
}


async def _search_course_info(
    client: httpx.AsyncClient,
    course_code: str,
    section: str,
    year: str,
    term_code: str,
) -> str | None:
    """Search course listing pages to find course details as syllabus fallback.

    Uses course code prefix to directly look up the correct college/department.
    """
    prefix = re.match(r"[A-Z]+", course_code)
    if not prefix:
        return None

    dept_info = _PREFIX_TO_DEPT.get(prefix.group())
    if not dept_info:
        return None

    col_code, dept_code, is_grad = dept_info
    jsp = "LecGradMajorSub.jsp" if is_grad else "LecMajorSub.jsp"

    try:
        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/{jsp}",
            params={
                "yy": year,
                "tm": term_code,
                "sCampus": "1",
                "col": col_code,
                "dept": dept_code,
                "listSub": "Y",
            },
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/lecture/{jsp}"},
            timeout=15.0,
        )
        html = resp.content.decode("euc-kr", errors="replace")
        if course_code in html:
            return _extract_course_detail(html, course_code, section)
    except httpx.HTTPError:
        pass

    return None


def _extract_course_detail(html: str, course_code: str, section: str) -> str | None:
    """Extract course details from a course listing page for the target course."""
    soup = BeautifulSoup(html, "lxml")

    # Collect all matching rows, pick the best section match
    matches: list[tuple[int, list[str]]] = []  # (code_idx, cells)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            code_idx = -1
            for i, cell in enumerate(cells[:3]):
                if (
                    course_code == cell
                ):  # Exact match to avoid COSE101 matching COSE1011
                    code_idx = i
                    break

            if code_idx >= 0:
                matches.append((code_idx, cells))

    if not matches:
        return None

    # Find exact section match, or fall back to first match
    best = matches[0]
    for code_idx, cells in matches:
        sect_idx = code_idx + 1
        if sect_idx < len(cells) and cells[sect_idx] == section:
            best = (code_idx, cells)
            break

    code_idx, cells = best
    return _format_course_detail(cells, code_idx)


def _format_course_detail(cells: list[str], code_idx: int) -> str:
    """Format course detail cells into readable text."""
    # Columns: (campus), 학수번호, 분반, 이수구분, 교과목명, 담당교수, 학점(시간), 강의시간, ...
    parts = ["[강의계획서 — 개설과목 정보]"]
    labels = [
        "학수번호",
        "분반",
        "이수구분",
        "교과목명",
        "담당교수",
        "학점(시간)",
        "강의시간",
    ]

    for j, label in enumerate(labels):
        idx = code_idx + j
        if idx < len(cells) and cells[idx]:
            parts.append(f"{label}: {cells[idx]}")

    parts.append("")
    parts.append("※ 상세 강의계획서(주차별 계획, 교재, 평가방법 등)는")
    parts.append("  KUPID 포털 > 수업 > 개설과목에서 학수번호 클릭 시 확인 가능합니다.")

    return "\n".join(parts)


def _format_allgen_params(params_str: str) -> str:
    """Format Allgen parameters as a readable fallback message."""
    pairs = re.findall(r"\[:(\w+)\]=([^\[]*)", params_str)
    info_parts = []
    for key, val in pairs:
        if val:
            label = {
                "p_year": "학년도",
                "p_term": "학기",
                "p_cour_cd": "학수번호",
                "p_cour_cls": "분반",
                "p_grad_cd": "대학원코드",
            }.get(key, key)
            info_parts.append(f"{label}: {val}")

    return (
        "강의계획서 리포트 서버(Allgen) 접속 불가 (교내 네트워크 전용).\n"
        "KUPID 포털에서 직접 열람해주세요.\n\n" + "\n".join(info_parts)
    )


def _parse_report_html(html: str) -> str:
    """Parse Allgen report server response into readable syllabus text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "head"]):
        tag.decompose()

    sections: list[str] = []
    tables = soup.find_all("table")
    if tables:
        for table in tables:
            for row in table.find_all("tr"):
                cells = [
                    td.get_text(strip=True)
                    for td in row.find_all(["td", "th"])
                    if td.get_text(strip=True)
                ]
                if cells:
                    if len(cells) == 2:
                        sections.append(f"{cells[0]}: {cells[1]}")
                    else:
                        sections.append(" | ".join(cells))

    if sections:
        result = "\n".join(sections)
    else:
        result = soup.get_text(separator="\n", strip=True)

    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() if result.strip() else ""


async def fetch_my_courses(
    session: Session,
    year: str | None = None,
    semester: str | None = None,
) -> tuple[list[EnrolledCourse], str]:
    """Fetch enrolled courses from infodepot CourseListSearch.

    Args:
        session: Valid KUPID session.
        year: Academic year (e.g., "2027").
        semester: "1", "2", "summer", "winter".

    Returns:
        Tuple of (list of EnrolledCourse, total_credits string).
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)
    yt = f"{year}{term_code}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        # Initial GET to establish page
        await client.get(
            f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
            params={"compId": "82", "menuCd": "247", "language": "ko"},
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/"},
        )

        # POST to set year/term
        resp = await client.post(
            f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
            data={"yt": yt},
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_enrolled_courses(html)


def _parse_enrolled_courses(html: str) -> tuple[list[EnrolledCourse], str]:
    """Parse enrolled courses HTML table and total credits."""
    soup = BeautifulSoup(html, "lxml")
    courses: list[EnrolledCourse] = []

    # Extract total credits: "신청하신 총 학점수는 X.X학점 입니다."
    total_credits = "0"
    credits_match = re.search(r"신청하신\s*총\s*학점수는\s*(\d+\.?\d*)\s*학점", html)
    if credits_match:
        total_credits = credits_match.group(1)

    # Build a map of (course_code, section) -> (grad_code, dept_code) from f_go() links
    fgo_map: dict[tuple[str, str], tuple[str, str]] = {}
    for a_tag in soup.find_all("a", href=re.compile(r"javascript:f_go")):
        onclick = a_tag.get("href", "")
        # f_go('YYYY','1R','7298','7313','AAI110','00','딥러닝')
        m = re.search(
            r"f_go\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*'(\w+)'",
            onclick,
        )
        if m:
            fgo_map[(m.group(3), m.group(4))] = (m.group(1), m.group(2))

    # Find the main data table (11-column course table)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue

            cell_texts = [td.get_text(strip=True) for td in cells]

            # Column 0: No (순번) — should be a digit
            if not cell_texts[0].isdigit():
                continue

            course_code = cell_texts[1]
            section = cell_texts[2] if len(cell_texts) > 2 else ""
            grad_code, dept_code = fgo_map.get((course_code, section), ("", ""))

            retake_text = cell_texts[8] if len(cells) > 8 else ""
            retake = retake_text in ("Y", "재수강")

            courses.append(
                EnrolledCourse(
                    course_code=course_code,
                    section=section,
                    course_type=cell_texts[3],
                    course_name=cell_texts[4],
                    professor=cell_texts[5],
                    credits=cell_texts[6],
                    schedule=cell_texts[7],
                    retake=retake,
                    status=cell_texts[9] if len(cells) > 9 else "",
                    grad_code=grad_code,
                    dept_code=dept_code,
                )
            )

    return courses, total_credits


def _parse_syllabus_html(html: str) -> str:
    """Parse syllabus page HTML into readable text (non-Allgen responses)."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_syllabus_structured(html: str) -> dict:
    """Parse infodepot syllabus HTML into structured dict.

    Returns dict with keys: course_info, professor, assistant, grading,
    learning_plan, weekly_schedule.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    result: dict = {}

    # --- 수업정보 ---
    course_info: dict[str, str] = {}
    info_span = soup.find("span", string=re.compile(r"수업정보"))
    if info_span:
        table = info_span.find_next("table")
        if table:
            for row in table.find_all("tr"):
                ths = row.find_all("th")
                tds = row.find_all("td")
                for th, td in zip(ths, tds):
                    key = th.get_text(strip=True)
                    val = td.get_text(strip=True)
                    if key and val:
                        course_info[key] = val
    if course_info:
        result["course_info"] = course_info

    # --- 강의담당자 ---
    def _parse_person_table(label: str) -> dict[str, str]:
        span = soup.find("span", string=re.compile(label))
        if not span:
            return {}
        table = span.find_next("table")
        if not table:
            return {}
        person: dict[str, str] = {}
        for row in table.find_all("tr"):
            ths = row.find_all("th")
            tds = row.find_all("td")
            for th, td in zip(ths, tds):
                key = th.get_text(strip=True)
                val = td.get_text(strip=True)
                if key and val:
                    person[key] = val
        return person

    professor = _parse_person_table("강의담당자")
    if professor:
        result["professor"] = professor

    assistant = _parse_person_table("조교정보")
    if assistant:
        result["assistant"] = assistant

    # --- 평가방법 ---
    grading: dict[str, str] = {}
    grade_span = soup.find("span", string=re.compile(r"평가방법"))
    if grade_span:
        table = grade_span.find_next("table")
        if table:
            for row in table.find_all("tr"):
                th = row.find("th")
                td = row.find("td")
                if th and td:
                    key = th.get_text(strip=True)
                    val = td.get_text(strip=True)
                    if key and val:
                        grading[key] = val
    if grading:
        result["grading"] = grading

    # --- 학습계획 (과목개요, 학습목표, 선수과목, 교재, 과제물) ---
    learning_plan: dict[str, str] = {}
    plan_fields = [
        "과목개요",
        "학습목표",
        "추천 선수과목 및 수강요건",
        "수업자료(교재)",
        "과제물",
    ]
    for field in plan_fields:
        th = soup.find("th", string=re.compile(re.escape(field)))
        if not th:
            continue
        # th가 thead 안에 있으면 tbody에서 td를 찾음
        thead = th.find_parent("thead")
        if thead:
            tbody = thead.find_next_sibling("tbody")
            td = tbody.find("td") if tbody else None
        else:
            row = th.find_parent("tr")
            td = (
                row.find_next_sibling("tr").find("td")
                if row and row.find_next_sibling("tr")
                else None
            )
        if td:
            for br in td.find_all("br"):
                br.replace_with("\n")
            text = td.get_text(strip=True)
            if text:
                learning_plan[field] = text
    if learning_plan:
        result["learning_plan"] = learning_plan

    # --- 주별학습내용 ---
    weekly: list[dict[str, str]] = []
    week_span = soup.find("span", string=re.compile(r"주별학습내용"))
    if week_span:
        table = week_span.find_next("table")
        if table:
            tbody = table.find("tbody")
            for row in tbody.find_all("tr") if tbody else []:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 4 and cells[0].isdigit():
                    entry: dict[str, str] = {
                        "week": cells[0],
                        "period": cells[1],
                        "topic": cells[3],
                    }
                    if len(cells) > 4 and cells[4]:
                        entry["textbook"] = cells[4]
                    if len(cells) > 5 and cells[5]:
                        entry["note"] = cells[5]
                    weekly.append(entry)
    if weekly:
        result["weekly_schedule"] = weekly

    return result
