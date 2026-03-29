from ku_portal_mcp.courses import parse_syllabus_structured


SAMPLE_HTML = """
<html>
<body>
<span class="tit_redbullet">수업정보</span>
<table class="tbl_view">
  <tbody>
    <tr><th>시간/강의실</th><td colspan="3">화(7-8) 정보통신관 B101호</td></tr>
    <tr><th>학점</th><td>2</td><th>학수번호(분반)</th><td>BDC115 ( 00 )</td></tr>
    <tr><th>이수구분</th><td colspan="3">전공선택</td></tr>
  </tbody>
</table>

<span class="tit_redbullet">강의담당자 </span>
<div class="bottom_view">
  <table class="tbl_view">
    <tbody>
      <tr><th>성명</th><td>이창희</td><th>소속</th><td>인공지능학과</td></tr>
      <tr><th>E-mail</th><td>changheelee@korea.ac.kr</td><th>Homepage</th><td>https://aix.korea.ac.kr</td></tr>
      <tr><th>연구실호실</th><td>우정정보관 208A호</td><th>연락처</th><td>02-3290-4418</td></tr>
      <tr><th>면담시간</th><td colspan="3"></td></tr>
    </tbody>
  </table>
</div>

<span class="tit_redbullet">조교정보 </span>
<table class="tbl_view">
  <tbody>
    <tr><th>성명</th><td>김시현</td><th>소속</th><td>인공지능학과</td></tr>
    <tr><th>E-mail</th><td colspan="3">sihyunkim@korea.ac.kr</td></tr>
    <tr><th>연구실</th><td></td><th>연락처</th><td>010-1234-5678</td></tr>
  </tbody>
</table>

<span class="tit_redbullet">평가방법</span>
<table class="tbl_view">
  <tbody>
    <tr><th>수시과제</th><td colspan="3">30 점</td></tr>
    <tr><th>중간과제</th><td colspan="3">35 점</td></tr>
    <tr><th>기말과제</th><td colspan="3">35 점</td></tr>
    <tr><th>합계</th><td colspan="3">100 점</td></tr>
  </tbody>
</table>

<span class="tit_redbullet">학습계획</span>
<table>
  <thead><tr><th>과목개요</th></tr></thead>
  <tbody><tr><td class="aleft">기계 학습의 핵심 원리를 탐구한다.</td></tr></tbody>
</table>
<table>
  <thead><tr><th>학습목표</th></tr></thead>
  <tbody><tr><td class="aleft">ML 기법에 대한 이해와 문제 해결 능력 배양</td></tr></tbody>
</table>
<table>
  <thead><tr><th>추천 선수과목 및 수강요건</th></tr></thead>
  <tbody><tr><td class="aleft">미적분학, 선형대수학, 확률과 통계</td></tr></tbody>
</table>
<table>
  <thead><tr><th>수업자료(교재)</th></tr></thead>
  <tbody><tr><td class="aleft">Deep Learning (Goodfellow)<br>Elements of Statistical Learning</td></tr></tbody>
</table>
<table>
  <thead><tr><th>과제물</th></tr></thead>
  <tbody><tr><td class="aleft">5 Assignments</td></tr></tbody>
</table>

<span class="tit_redbullet">주별학습내용</span>
<table>
  <thead>
    <tr><th>주</th><th>기간</th><th>회차</th><th>학습내용</th><th>교재</th><th>활동 및<br/> 설계내용</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>03.03 - 03.09</td><td>1</td><td>Introduction</td><td></td><td></td></tr>
    <tr><td>2</td><td>03.10 - 03.16</td><td>1</td><td>Supervised Learning</td><td>Ch.1</td><td></td></tr>
    <tr><td>8</td><td>04.21 - 04.27</td><td>1</td><td>Midterm Exam</td><td></td><td>중간고사</td></tr>
    <tr><td>16</td><td>06.16 - 06.22</td><td>1</td><td>Final Exam</td><td></td><td>기말고사</td></tr>
  </tbody>
</table>
</body>
</html>
"""


def test_course_info():
    result = parse_syllabus_structured(SAMPLE_HTML)
    info = result["course_info"]
    assert info["시간/강의실"] == "화(7-8) 정보통신관 B101호"
    assert info["학점"] == "2"
    assert info["학수번호(분반)"] == "BDC115 ( 00 )"
    assert info["이수구분"] == "전공선택"


def test_professor():
    result = parse_syllabus_structured(SAMPLE_HTML)
    prof = result["professor"]
    assert prof["성명"] == "이창희"
    assert prof["소속"] == "인공지능학과"
    assert prof["E-mail"] == "changheelee@korea.ac.kr"
    assert prof["연락처"] == "02-3290-4418"


def test_assistant():
    result = parse_syllabus_structured(SAMPLE_HTML)
    ta = result["assistant"]
    assert ta["성명"] == "김시현"
    assert ta["E-mail"] == "sihyunkim@korea.ac.kr"
    assert ta["연락처"] == "010-1234-5678"


def test_grading():
    result = parse_syllabus_structured(SAMPLE_HTML)
    grading = result["grading"]
    assert grading["수시과제"] == "30 점"
    assert grading["중간과제"] == "35 점"
    assert grading["기말과제"] == "35 점"
    assert grading["합계"] == "100 점"


def test_learning_plan():
    result = parse_syllabus_structured(SAMPLE_HTML)
    plan = result["learning_plan"]
    assert plan["과목개요"] == "기계 학습의 핵심 원리를 탐구한다."
    assert plan["학습목표"] == "ML 기법에 대한 이해와 문제 해결 능력 배양"
    assert plan["추천 선수과목 및 수강요건"] == "미적분학, 선형대수학, 확률과 통계"
    assert "Deep Learning" in plan["수업자료(교재)"]
    assert plan["과제물"] == "5 Assignments"


def test_weekly_schedule():
    result = parse_syllabus_structured(SAMPLE_HTML)
    weeks = result["weekly_schedule"]
    assert len(weeks) == 4

    assert weeks[0]["week"] == "1"
    assert weeks[0]["period"] == "03.03 - 03.09"
    assert weeks[0]["topic"] == "Introduction"
    assert "textbook" not in weeks[0]
    assert "note" not in weeks[0]

    # week 2 has textbook
    assert weeks[1]["textbook"] == "Ch.1"

    # week 8 has note (중간고사)
    assert weeks[2]["week"] == "8"
    assert weeks[2]["topic"] == "Midterm Exam"
    assert weeks[2]["note"] == "중간고사"

    # week 16
    assert weeks[3]["week"] == "16"
    assert weeks[3]["note"] == "기말고사"


def test_empty_html_returns_empty_dict():
    result = parse_syllabus_structured("<html><body></body></html>")
    assert result == {}
