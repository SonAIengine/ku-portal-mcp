import asyncio
import json

import ku_portal_mcp.server as server_module
from ku_portal_mcp.courses import CourseInfo, EnrolledCourse
from ku_portal_mcp.dept_notices import DeptNotice
from ku_portal_mcp.grades import GradePage, GradeRecord, GradeSummary
from ku_portal_mcp.library import ReadingRoomStatus


def _call_tool(name: str, arguments: dict):
    return asyncio.run(server_module.server.call_tool(name, arguments))


def _list_tools():
    return asyncio.run(server_module.server.list_tools())


def _assert_text_block_matches_structured_output(result):
    blocks, structured = result

    assert isinstance(blocks, list)
    assert len(blocks) == 1
    assert blocks[0].type == "text"
    assert json.loads(blocks[0].text) == structured

    return structured


def test_list_tools_exposes_expected_mcp_tools():
    tools = _list_tools()
    tool_names = {tool.name for tool in tools}

    assert "kupid_get_library_seats" in tool_names
    assert "kupid_my_courses" in tool_names
    assert "kupid_lms_courses" in tool_names


def test_kupid_get_library_seats_returns_mcp_serialized_output(monkeypatch):
    async def fake_fetch_all_seats():
        return {
            "중앙도서관": [
                ReadingRoomStatus(
                    room_name="열람실 A",
                    room_name_eng="Room A",
                    total_seats=100,
                    available=40,
                    in_use=60,
                    disabled=0,
                    is_notebook_allowed=True,
                    operating_hours="24시간",
                )
            ]
        }

    monkeypatch.setattr(server_module, "fetch_all_seats", fake_fetch_all_seats)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_get_library_seats", {"library_name": ""})
    )

    assert structured["success"] is True
    assert structured["summary"] == {
        "total_seats": 100,
        "total_available": 40,
        "total_in_use": 60,
        "occupancy_rate": "60.0%",
    }
    assert structured["libraries"]["중앙도서관"][0]["room_name"] == "열람실 A"


def test_kupid_my_courses_returns_mcp_serialized_output(monkeypatch):
    async def fake_get_session():
        return object()

    async def fake_fetch_my_courses(session, year=None, semester=None):
        assert year == "2026"
        assert semester == "1"
        return (
            [
                EnrolledCourse(
                    course_code="COSE101",
                    section="01",
                    course_type="전공필수",
                    course_name="컴퓨터프로그래밍",
                    professor="홍길동",
                    credits="3(3)",
                    schedule="월(1-2) 우당교양관 101호",
                    retake=False,
                    status="신청",
                    grad_code="5720",
                    dept_code="5722",
                )
            ],
            "3",
        )

    monkeypatch.setattr(server_module, "_get_session", fake_get_session)
    monkeypatch.setattr(server_module, "fetch_my_courses", fake_fetch_my_courses)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_my_courses", {"year": "2026", "semester": "1"})
    )

    assert structured["success"] is True
    assert structured["year"] == "2026"
    assert structured["semester"] == "1"
    assert structured["total_credits"] == "3"
    assert structured["courses"] == [
        {
            "course_code": "COSE101",
            "section": "01",
            "course_type": "전공필수",
            "course_name": "컴퓨터프로그래밍",
            "professor": "홍길동",
            "credits": "3(3)",
            "schedule": "월(1-2) 우당교양관 101호",
            "retake": False,
            "status": "신청",
            "grad_code": "5720",
            "dept_code": "5722",
        }
    ]


def test_kupid_search_courses_returns_department_selection_output(monkeypatch):
    async def fake_get_session():
        return object()

    async def fake_fetch_departments(session, college_code, year=None, term=None):
        assert college_code == "5720"
        assert year == "2026"
        assert term == "1"
        return [{"code": "5722", "name": "컴퓨터학과"}]

    monkeypatch.setattr(server_module, "_get_session", fake_get_session)
    monkeypatch.setattr(server_module, "fetch_departments", fake_fetch_departments)

    structured = _assert_text_block_matches_structured_output(
        _call_tool(
            "kupid_search_courses",
            {"year": "2026", "semester": "1", "college": "5720", "department": "", "campus": "1"},
        )
    )

    assert structured["success"] is True
    assert structured["college"] == "정보대학"
    assert structured["departments"] == [{"code": "5722", "name": "컴퓨터학과"}]


def test_kupid_search_courses_returns_course_results(monkeypatch):
    async def fake_get_session():
        return object()

    async def fake_search_courses(session, year=None, semester=None, campus="1", college="", department=""):
        assert year == "2026"
        assert semester == "1"
        assert campus == "1"
        assert college == "5720"
        assert department == "5722"
        return [
            CourseInfo(
                campus="서울",
                course_code="COSE101",
                section="01",
                course_type="전공필수",
                course_name="컴퓨터프로그래밍",
                professor="홍길동",
                credits="3",
                schedule="월(1-2)",
            )
        ]

    monkeypatch.setattr(server_module, "_get_session", fake_get_session)
    monkeypatch.setattr(server_module, "search_courses", fake_search_courses)

    structured = _assert_text_block_matches_structured_output(
        _call_tool(
            "kupid_search_courses",
            {"year": "2026", "semester": "1", "college": "5720", "department": "5722", "campus": "1"},
        )
    )

    assert structured["success"] is True
    assert structured["count"] == 1
    assert structured["courses"] == [
        {
            "campus": "서울",
            "course_code": "COSE101",
            "section": "01",
            "course_type": "전공필수",
            "course_name": "컴퓨터프로그래밍",
            "professor": "홍길동",
            "credits": "3",
            "schedule": "월(1-2)",
        }
    ]


def test_kupid_get_syllabus_returns_mcp_serialized_output(monkeypatch):
    async def fake_get_session():
        return object()

    async def fake_fetch_syllabus(session, course_code, section="00", year=None, semester=None):
        assert course_code == "COSE101"
        assert section == "01"
        assert year == "2026"
        assert semester == "1"
        return "담당교수: 홍길동\n수업개요: 테스트"

    monkeypatch.setattr(server_module, "_get_session", fake_get_session)
    monkeypatch.setattr(server_module, "fetch_syllabus", fake_fetch_syllabus)

    structured = _assert_text_block_matches_structured_output(
        _call_tool(
            "kupid_get_syllabus",
            {"course_code": "COSE101", "section": "01", "year": "2026", "semester": "1"},
        )
    )

    assert structured == {
        "success": True,
        "course_code": "COSE101",
        "section": "01",
        "year": "2026",
        "semester": "1",
        "content": "담당교수: 홍길동\n수업개요: 테스트",
    }


def test_kupid_dept_notices_returns_mcp_serialized_output(monkeypatch):
    async def fake_fetch_dept_notice_list(url, offset=0, limit=20):
        assert url == "https://dept.example.com/notice.do"
        assert offset == 20
        assert limit == 20
        return [
            DeptNotice(
                article_no="101",
                title="수강신청 안내",
                writer="학과사무실",
                date="2026-03-01",
                views="123",
                is_pinned=True,
                has_attachment=True,
            )
        ]

    monkeypatch.setattr(
        server_module,
        "resolve_site",
        lambda site_name: {"label": "테스트학과", "url": "https://dept.example.com/notice.do"},
    )
    monkeypatch.setattr(server_module, "fetch_dept_notice_list", fake_fetch_dept_notice_list)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_dept_notices", {"site_name": "테스트학과", "page": 2, "count": 20})
    )

    assert structured["success"] is True
    assert structured["site"] == "테스트학과"
    assert structured["page"] == 2
    assert structured["notices"] == [
        {
            "article_no": "101",
            "title": "수강신청 안내",
            "writer": "학과사무실",
            "date": "2026-03-01",
            "views": "123",
            "is_pinned": True,
            "has_attachment": True,
        }
    ]


def test_kupid_lms_courses_returns_mcp_serialized_output(monkeypatch):
    async def fake_get_lms_session():
        return object()

    async def fake_fetch_lms_courses(session):
        return [
            {
                "id": 101,
                "name": "딥러닝",
                "course_code": "AAI110-01",
                "term": {"name": "2026-1학기"},
                "workflow_state": "available",
            }
        ]

    monkeypatch.setattr(server_module, "_get_lms_session", fake_get_lms_session)
    monkeypatch.setattr(server_module, "fetch_lms_courses", fake_fetch_lms_courses)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_lms_courses", {})
    )

    assert structured == {
        "success": True,
        "count": 1,
        "courses": [
            {
                "id": 101,
                "name": "딥러닝",
                "course_code": "AAI110-01",
                "term": "2026-1학기",
                "workflow_state": "available",
            }
        ],
    }


def test_kupid_get_all_grades_returns_mcp_serialized_output(monkeypatch):
    async def fake_get_session():
        return object()

    async def fake_fetch_all_grades(session, year_term=""):
        assert year_term == "20242R"
        return GradePage(
            available_year_terms=[{"value": "20242R", "label": "2024학년도 2학기"}],
            records=[
                GradeRecord(
                    year="2024",
                    term="2학기",
                    course_code="COSE101",
                    course_name="컴퓨터프로그래밍",
                    completion_type="전공필수",
                    course_type="전공",
                    credits="3",
                    score="95",
                    grade="A+",
                    gpa="4.5",
                    retake_year="",
                    retake_term="",
                    retake_course="",
                    deletion_type="",
                )
            ],
            summaries=[
                GradeSummary(
                    year="2024",
                    term="2학기",
                    major_registered_credits="21",
                    major_earned_credits="18",
                    prerequisite_earned_credits="0",
                    research_earned_credits="0",
                    total_grade_points="54.0",
                    official_gpa="4.20",
                    overall_gpa="4.10",
                    official_converted_score="98.0",
                    rank_for_certificate="1 / 30",
                )
            ],
        )

    monkeypatch.setattr(server_module, "_get_session", fake_get_session)
    monkeypatch.setattr(server_module, "fetch_all_grades", fake_fetch_all_grades)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_get_all_grades", {"year_term": "20242R"})
    )

    assert structured["success"] is True
    assert structured["year_term"] == "20242R"
    assert structured["record_count"] == 1
    assert structured["summary_count"] == 1
    assert structured["available_year_terms"] == [
        {"value": "20242R", "label": "2024학년도 2학기"}
    ]
    assert structured["latest_summary"]["overall_gpa"] == "4.10"
    assert structured["records"][0]["course_code"] == "COSE101"
