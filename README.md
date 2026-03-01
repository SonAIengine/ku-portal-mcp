# ku-portal-mcp

고려대학교 KUPID 포털 MCP 서버 — Claude Code에서 포털 기능에 직접 접근

## 기능

| # | Tool | 설명 | 인증 |
|---|------|------|------|
| 1 | `kupid_login` | 포털 로그인 / 세션 확인 | SSO |
| 2 | `kupid_get_notices` | 공지사항 목록 | SSO |
| 3 | `kupid_get_notice_detail` | 공지사항 상세 | SSO |
| 4 | `kupid_get_schedules` | 학사일정 목록 | SSO |
| 5 | `kupid_get_schedule_detail` | 학사일정 상세 | SSO |
| 6 | `kupid_get_scholarships` | 장학공지 목록 | SSO |
| 7 | `kupid_get_scholarship_detail` | 장학공지 상세 | SSO |
| 8 | `kupid_search` | 공지/일정/장학 통합 검색 | SSO |
| 9 | `kupid_get_library_seats` | 도서관 열람실 좌석 현황 | **불필요** |
| 10 | `kupid_get_timetable` | 개인 수업시간표 + ICS 내보내기 | SSO |
| 11 | `kupid_search_courses` | 개설과목 검색 (학과별) | SSO |
| 12 | `kupid_get_syllabus` | 강의계획서 조회 | SSO |

## 설치

### 1. Claude Code MCP 서버 설정

`~/.claude/settings.json`의 `mcpServers`에 추가:

```json
{
  "ku-portal": {
    "command": "python3",
    "args": ["/path/to/ku-portal-mcp/run.py"],
    "env": {
      "KU_PORTAL_ID": "your-kupid-id",
      "KU_PORTAL_PW": "your-kupid-password"
    }
  }
}
```

### 2. 의존성 설치

```bash
cd /path/to/ku-portal-mcp
pip install -e .
```

## 사용 예시

### 도서관 좌석 현황 (인증 불필요)
```
> 중앙도서관 좌석 현황 알려줘
> 도서관 전체 좌석 현황 보여줘
```

### 수업시간표
```
> 이번 주 시간표 조회해줘
> 시간표를 ICS 파일로 내보내줘
```

### 개설과목 검색
```
> 정보대학 컴퓨터학과 개설과목 검색해줘
> COSE101 강의계획서 보여줘
```

### 공지사항/학사일정
```
> 최근 공지사항 보여줘
> "수강신청" 관련 공지 검색해줘
> 학사일정 조회해줘
```

## 프로젝트 구조

```
ku_portal_mcp/
├── server.py      # MCP 서버 + 12개 tool 등록
├── auth.py        # SSO 로그인, 세션 캐싱
├── scraper.py     # GRW 공지/일정/장학 파싱
├── library.py     # 도서관 좌석 현황 (librsv.korea.ac.kr)
├── timetable.py   # 수업시간표 + ICS export
└── courses.py     # 개설과목 검색, 강의계획서
```

## 기술 스택

- **MCP**: FastMCP (mcp[cli])
- **HTTP**: httpx (async)
- **파싱**: BeautifulSoup4 + lxml
- **인증**: KUPID SSO token + 세션 캐싱 (30분 TTL)
- **도서관**: HODI API (librsv.korea.ac.kr, 인증 불필요)
- **개설과목**: infodepot.korea.ac.kr (SSO token handoff)

## 라이선스

MIT
