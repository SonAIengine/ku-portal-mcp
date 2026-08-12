import asyncio
import json

import ku_portal_mcp.server as server_module
from ku_portal_mcp.dept_notices import DeptNotice
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
    async def fake_get_ams_session():
        return object()

    async def fake_fetch_terms(session):
        return [{"code": "20261R", "fullNm": "2026학년도 1학기"}]

    async def fake_fetch_enrollment(session, term):
        assert term == "20261R"
        return [
            {
                "sbjtnb": "COSE101",
                "dvcno": "01",
                "subjtNm": "컴퓨터프로그래밍",
                "cgprfNmLisup": "홍길동",
                "cdtTime": "3.0(3)",
                "cmpsjNm": "전공필수 ",
                "lctreTimePlaceLisup": "월(1-2) 우당교양관 101호",
                "sttusNm": "신청",
                "payDt": "미수납",
                "estblDeprtCd": "5722",
            }
        ]

    monkeypatch.setattr(server_module, "_get_ams_session", fake_get_ams_session)
    monkeypatch.setattr(server_module.ams, "fetch_terms", fake_fetch_terms)
    monkeypatch.setattr(server_module.ams, "fetch_enrollment", fake_fetch_enrollment)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_my_courses", {"year": "2026", "semester": "1"})
    )

    assert structured["success"] is True
    assert structured["term"] == "20261R"
    assert structured["total_credits"] == 3.0
    assert structured["count"] == 1
    course = structured["courses"][0]
    assert course["course_code"] == "COSE101"
    assert course["course_name"] == "컴퓨터프로그래밍"
    assert course["professor"] == "홍길동"
    assert course["course_type"] == "전공필수"
    assert course["schedule"] == "월(1-2) 우당교양관 101호"


def test_kupid_search_courses_returns_course_results(monkeypatch):
    async def fake_get_ams_session():
        return object()

    async def fake_fetch_room_guide(session, keyword):
        assert keyword == "딥러닝"
        return [
            {
                "sbjtnb": "AAI110",
                "dvcno": "00",
                "subjtNm": "딥러닝",
                "lecrmNm": "301호(노트북용 실습실)",
                "buldDivNm": "애기능생활관",
                "buldCampsDivNm": "자연계",
                "estblDeprtCd": "7313",
            },
            {
                "sbjtnb": "STA618",
                "dvcno": "00",
                "subjtNm": "고급통계적딥러닝",
                "lecrmNm": "SK미래관 522",
                "buldDivNm": "SK미래관",
                "buldCampsDivNm": "인문사회계",
                "estblDeprtCd": "0301",
            },
        ]

    monkeypatch.setattr(server_module, "_get_ams_session", fake_get_ams_session)
    monkeypatch.setattr(server_module.ams, "fetch_room_guide", fake_fetch_room_guide)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_search_courses", {"subject": "딥러닝"})
    )

    assert structured["success"] is True
    assert structured["count"] == 2
    assert structured["courses"][0]["course_code"] == "AAI110"
    assert structured["courses"][0]["classroom"] == "301호(노트북용 실습실)"


def test_kupid_search_courses_filters_by_campus(monkeypatch):
    async def fake_get_ams_session():
        return object()

    async def fake_fetch_room_guide(session, keyword):
        return [
            {"sbjtnb": "AAI110", "subjtNm": "딥러닝", "buldCampsDivNm": "자연계"},
            {
                "sbjtnb": "STA618",
                "subjtNm": "고급통계적딥러닝",
                "buldCampsDivNm": "인문사회계",
            },
        ]

    monkeypatch.setattr(server_module, "_get_ams_session", fake_get_ams_session)
    monkeypatch.setattr(server_module.ams, "fetch_room_guide", fake_fetch_room_guide)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_search_courses", {"subject": "딥러닝", "campus": "자연계"})
    )

    assert structured["success"] is True
    assert structured["count"] == 1
    assert structured["courses"][0]["course_code"] == "AAI110"


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
        lambda site_name: {
            "label": "테스트학과",
            "url": "https://dept.example.com/notice.do",
        },
    )
    monkeypatch.setattr(
        server_module, "fetch_dept_notice_list", fake_fetch_dept_notice_list
    )

    structured = _assert_text_block_matches_structured_output(
        _call_tool(
            "kupid_dept_notices", {"site_name": "테스트학과", "page": 2, "count": 20}
        )
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
    async def fake_get_ams_session():
        return object()

    async def fake_fetch_grades(session):
        rows = [
            {
                "syy": "2026",
                "smtDivcd": "1R",
                "sbjtnb": "COSE101",
                "dvcno": "01",
                "subjtNm": "컴퓨터프로그래밍",
                "cmpsjDivNm": "전공필수",
                "cdt": 3,
                "gradeGrdDivcd": "A+",
                "cmpsjGp": 4.5,
                "ratlcSyySmtNm": None,
            }
        ]
        summary = [
            {
                "gpa": 4.2,
                "aplyCdt": 18,
                "tgp": 54.0,
                "covsnSco": 98.0,
                "cmpsjCdt": 15,
            }
        ]
        return rows, summary

    monkeypatch.setattr(server_module, "_get_ams_session", fake_get_ams_session)
    monkeypatch.setattr(server_module.ams, "fetch_grades", fake_fetch_grades)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_get_all_grades", {})
    )

    assert structured["success"] is True
    assert structured["count"] == 1
    grade = structured["grades"][0]
    assert grade["course_code"] == "COSE101"
    assert grade["grade"] == "A+"
    assert grade["grade_point"] == 4.5
    assert structured["summary"]["gpa"] == 4.2
    assert structured["summary"]["earned_credits"] == 18


def _syllabus_payload(evaluation=None, weekly=None, references=None):
    return {
        "base": {
            "sbjtnb": "BDC108",
            "subjtNm": "통계적학습개론",
            "dvcno": "00",
            "cdt": 2,
            "cmpsjNm": "전공선택 ",
            "estblDeprtNm": "빅데이터융합학과",
            "lctreTimePlaceLisup": "화(7-8) 정보통신관 604호",
            "per001KorNm": "이창희",
            "per001EmailAddr": "changheelee@korea.ac.kr",
            "cnslgPosblTimeDesc": "화요일 20:00 ~ 20:30",
            "gradeEvlMthdNm": "절대평가",
            "atnlcRqistCtnt": "미적분학, 선형대수학 기초 지식이 필수적이다.",
        },
        "evaluation": evaluation or [],
        "weekly": weekly or [],
        "references": references or [],
    }


def test_kupid_syllabus_returns_evaluation_and_weekly(monkeypatch):
    async def fake_fetch_syllabus(course_code, year, term, section="00", grad_dept=""):
        assert (course_code, year, term) == ("BDC108", "2026", "2R")
        return _syllabus_payload(
            evaluation=[
                {"evlItemCtnt": "수시과제", "evlSco": 30, "seqno": 1},
                {"evlItemCtnt": "중간고사", "evlSco": 30, "seqno": 2},
                {"evlItemCtnt": "기말고사", "evlSco": 30, "seqno": 3},
                {"evlItemCtnt": "참여도", "evlSco": 10, "seqno": 4},
            ],
            weekly=[
                {"lessnWkOdr": 8, "lctreCtnt": "중간고사", "mdtexOprtYn": "1"},
                {"lessnWkOdr": 16, "lctreCtnt": "기말고사", "fnlexOprtYn": "1"},
            ],
            references=[
                {"referBookNm": "ISLP", "pblcmNm": "Springer", "isbnVal": None}
            ],
        )

    monkeypatch.setattr(server_module.ams, "fetch_syllabus", fake_fetch_syllabus)

    structured = _assert_text_block_matches_structured_output(
        _call_tool(
            "kupid_syllabus", {"course_code": "bdc108", "year": "2026", "semester": "2"}
        )
    )

    assert structured["success"] is True
    assert structured["course_name"] == "통계적학습개론"
    assert structured["category"] == "전공선택"
    assert structured["evaluation_total"] == 100
    assert structured["evaluation"][0] == {"item": "수시과제", "percent": 30}
    assert structured["professor"]["office_hours"] == "화요일 20:00 ~ 20:30"
    assert [w["week"] for w in structured["weekly"] if w["midterm"]] == [8]
    assert [w["week"] for w in structured["weekly"] if w["final"]] == [16]
    assert structured["references"][0]["title"] == "ISLP"
    assert structured["note"] == ""


def test_kupid_syllabus_notes_unwritten_evaluation(monkeypatch):
    """계획서가 아직 비어 있어도 조회 자체는 성공해야 한다."""

    async def fake_fetch_syllabus(course_code, year, term, section="00", grad_dept=""):
        return _syllabus_payload()

    monkeypatch.setattr(server_module.ams, "fetch_syllabus", fake_fetch_syllabus)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_syllabus", {"course_code": "AAI104"})
    )

    assert structured["success"] is True
    assert structured["evaluation"] == []
    assert structured["evaluation_total"] == 0
    assert "등록하지 않았" in structured["note"]


def test_kupid_syllabus_reports_missing_course(monkeypatch):
    async def fake_fetch_syllabus(course_code, year, term, section="00", grad_dept=""):
        return None

    monkeypatch.setattr(server_module.ams, "fetch_syllabus", fake_fetch_syllabus)

    structured = _assert_text_block_matches_structured_output(
        _call_tool("kupid_syllabus", {"course_code": "AAI999"})
    )

    assert structured["success"] is False
    assert "찾을 수 없습니다" in structured["message"]


def test_resolve_syllabus_term_maps_break_periods_to_regular_terms():
    from datetime import date

    resolve = server_module._resolve_syllabus_term

    # 학기 중에는 그 학기를 그대로 본다.
    assert resolve("2026", "1") == ("2026", "1R")
    assert resolve("2026", "2") == ("2026", "2R")
    # 이미 AMS 코드를 준 경우 손대지 않는다.
    assert resolve("2026", "2R") == ("2026", "2R")

    # 방학 중이면 다가오는 정규학기로 넘긴다.
    assert resolve("", "", today=date(2026, 5, 1)) == ("2026", "1R")
    assert resolve("", "", today=date(2026, 8, 12)) == ("2026", "2R")
    assert resolve("", "", today=date(2026, 10, 1)) == ("2026", "2R")
    # 1~2월은 직전 학년도 겨울학기 → 다가오는 학년도 1학기
    assert resolve("", "", today=date(2027, 1, 15)) == ("2027", "1R")
