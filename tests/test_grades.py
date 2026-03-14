from ku_portal_mcp.grades import parse_all_grades_html


def test_parse_all_grades_html_extracts_records_and_summaries():
    html = """
    <html>
      <body>
        <form>
          <select name="yt">
            <option value="">전체</option>
            <option value="20242R">2024학년도 2학기</option>
            <option value="20251R">2025학년도 1학기</option>
          </select>
        </form>

        <span class="tit_redbullet">성적확정자료</span>
        <table>
          <thead>
            <tr>
              <th>년도</th><th>학기</th><th>학수번호</th><th>과목명</th><th>이수구분</th>
              <th>과목유형</th><th>학점</th><th>점수</th><th>등급</th><th>평점</th>
              <th>재수강년도</th><th>재수강학기</th><th>재수강과목</th><th>삭제구분</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>2024</td><td>2학기</td><td>COSE101</td><td>컴퓨터프로그래밍</td><td>전공필수</td>
              <td>전공</td><td>3</td><td>95</td><td>A+</td><td>4.5</td>
              <td></td><td></td><td></td><td></td>
            </tr>
          </tbody>
        </table>

        <span class="tit_redbullet">누계성적</span>
        <table>
          <thead>
            <tr>
              <th>년도</th><th>학기</th><th>전공신청학점</th><th>전공취득학점</th><th>선수취득학점</th>
              <th>연구취득학점</th><th>총평점(증명용)</th><th>평점평균(증명용)</th><th>평점평균(전체)</th>
              <th>환산점수(증명용)</th><th>석차증명용</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>2025</td><td>1학기</td><td>21</td><td>18</td><td>0</td>
              <td>0</td><td>54.0</td><td>4.20</td><td>4.10</td><td>98.0</td><td>1 / 30</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    page = parse_all_grades_html(html)

    assert page.available_year_terms == [
        {"value": "20242R", "label": "2024학년도 2학기"},
        {"value": "20251R", "label": "2025학년도 1학기"},
    ]
    assert len(page.records) == 1
    assert page.records[0].course_code == "COSE101"
    assert page.records[0].course_name == "컴퓨터프로그래밍"
    assert page.records[0].grade == "A+"
    assert page.records[0].gpa == "4.5"
    assert len(page.summaries) == 1
    assert page.summaries[0].overall_gpa == "4.10"
    assert page.summaries[0].major_earned_credits == "18"


def test_parse_all_grades_html_handles_empty_tables():
    html = """
    <html>
      <body>
        <span class="tit_redbullet">성적확정자료</span>
        <table><tbody></tbody></table>
        <span class="tit_redbullet">누계성적</span>
        <table><tbody></tbody></table>
      </body>
    </html>
    """

    page = parse_all_grades_html(html)

    assert page.available_year_terms == []
    assert page.records == []
    assert page.summaries == []
