from ku_portal_mcp.courses import _parse_enrolled_courses


def test_parse_enrolled_courses_maps_grad_and_dept_by_course_code_and_section():
    html = """
    <html>
      <body>
        신청하신 총 학점수는 6학점 입니다.
        <a href="javascript:f_go('2026','1R','7298','7313','AAI110','00','딥러닝')">딥러닝 00</a>
        <a href="javascript:f_go('2026','1R','9999','8888','AAI110','01','딥러닝')">딥러닝 01</a>
        <table>
          <tr>
            <th>순번</th><th>학수번호</th><th>분반</th><th>이수구분</th><th>교과목명</th>
            <th>담당교수</th><th>학점</th><th>강의시간</th><th>재수강</th><th>상태</th>
          </tr>
          <tr>
            <td>1</td><td>AAI110</td><td>00</td><td>전공선택</td><td>딥러닝</td>
            <td>교수A</td><td>3</td><td>월(1-2)</td><td>N</td><td>신청</td>
          </tr>
          <tr>
            <td>2</td><td>AAI110</td><td>01</td><td>전공선택</td><td>딥러닝</td>
            <td>교수B</td><td>3</td><td>화(1-2)</td><td>Y</td><td>신청</td>
          </tr>
        </table>
      </body>
    </html>
    """

    courses, total_credits = _parse_enrolled_courses(html)

    assert total_credits == "6"
    assert len(courses) == 2
    assert courses[0].grad_code == "7298"
    assert courses[0].dept_code == "7313"
    assert courses[0].section == "00"
    assert courses[1].grad_code == "9999"
    assert courses[1].dept_code == "8888"
    assert courses[1].section == "01"
    assert courses[1].retake is True
