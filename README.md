# ku-portal-mcp

고려대학교 KUPID 포털 MCP 서버 — Claude Code에서 대학 생활에 필요한 정보를 바로 조회

> "공지사항 보여줘", "도서관 빈자리 있어?", "이번 주 과제 뭐 있어?" 같은 자연어로 포털과 LMS를 사용할 수 있습니다.

## 이런 걸 할 수 있어요

### 1. 공지사항 / 학사일정 / 장학공지

KUPID 포털의 각종 게시판을 조회하고, 키워드로 검색할 수 있습니다.

```
> 최근 공지사항 보여줘
> "수강신청" 관련 공지 검색해줘
> 이번 달 학사일정 알려줘
> 장학금 관련 공지 있어?
> 공지사항 3번째 글 상세 내용 보여줘
```

- 공지사항, 학사일정, 장학공지 **목록 조회** + **상세 내용 열람**
- 제목 기준 **키워드 통합 검색** (공지/일정/장학 동시 검색 가능)
- 첨부파일 목록, 작성자, 작성일 등 메타 정보 포함

### 2. 도서관 좌석 현황 (로그인 불필요)

6개 도서관, 53개 열람실의 **실시간 좌석 현황**을 확인합니다. 로그인 없이 바로 조회 가능합니다.

```
> 중앙도서관 빈자리 몇 개야?
> 과학도서관 좌석 현황 보여줘
> 전체 도서관 좌석 현황 알려줘
> 노트북 사용 가능한 열람실 어디야?
```

- 대상 도서관: 중앙도서관, 중앙광장, 백주년기념 학술정보관, 과학도서관, 하나스퀘어, 법학도서관
- 열람실별 **총 좌석 / 사용 중 / 잔여 좌석** 실시간 표시
- 노트북 허용 여부, 운영시간 정보 포함
- 전체 도서관 합산 이용률(%) 제공

### 3. 수업시간표 + ICS 내보내기

포털에 등록된 개인 수업시간표를 조회하고, 구글 캘린더 등에 추가할 수 있는 ICS 파일로 내보냅니다.

```
> 이번 주 시간표 보여줘
> 월요일 수업 뭐 있어?
> 시간표를 ICS 파일로 만들어줘
> 오늘 수업 몇 시에 시작해?
```

- 월~금 **요일별 조회** 또는 **전체 주간 시간표** 한번에 보기
- 교시 → 실제 시간 자동 변환 (1교시=09:00~10:15, 2교시=10:30~11:45 ...)
- **ICS 캘린더 파일** 생성 → 구글 캘린더, Apple 캘린더에 바로 추가 가능
- 과목명, 강의실, 교시 정보 포함

### 4. 개설과목 검색 + 강의계획서

학과/단과대별 개설 과목을 검색하고, 강의계획서를 조회합니다.

```
> 정보대학 컴퓨터학과 개설과목 보여줘
> 이번 학기 경영대학에 어떤 학과가 있어?
> COSE101 강의계획서 보여줘
> 공과대학 개설과목 검색해줘
```

- **단과대 → 학과 → 과목** 단계적 검색 (코드를 몰라도 됩니다)
- 서울캠퍼스 14개 단과대 지원 (경영대학, 문과대학, 정보대학, 공과대학 등)
- 과목별 학수번호, 분반, 교수명, 학점, 시간표 정보
- 강의계획서 조회 (교내 리포트 서버 연동)

### 5. Canvas LMS — 수강과목 / 과제 / 강의자료

고려대학교 Canvas LMS(mylms.korea.ac.kr)에 접속하여 수강 정보를 조회합니다.

```
> LMS에 어떤 과목 듣고 있어?
> 딥러닝 과제 목록 보여줘
> 아직 안 낸 과제 있어?
> 자연어처리 강의자료 보여줘
> 이번 주 제출할 과제 뭐야?
> LMS 대시보드 보여줘
> 딥러닝 성적 어때?
> 과제 제출 현황 보여줘
> 퀴즈 일정 있어?
```

- **수강과목 목록**: 현재 학기 수강 중인 과목과 학기 정보
- **과제 목록**: 과목별 과제, 제출 기한, 배점, 제출 방식 확인
- **강의자료(모듈)**: 주차별 강의 모듈과 포함된 자료(강의 영상, PDF, 퀴즈 등)
- **할 일 목록**: 마감이 다가오는 과제와 이벤트를 한눈에
- **대시보드**: 수강 과목 카드 + 과목별 공지사항 모아보기
- **성적/점수 조회**: 과목별 현재 점수, 최종 점수, 학점 확인
- **과제 제출 현황**: 제출 여부, 채점 점수, 지각/미제출 상태 확인
- **퀴즈/시험 목록**: 퀴즈 일정, 시간제한, 문항 수 확인

---

## 전체 Tool 목록

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
| 11 | `kupid_search_courses` | 개설과목 검색 (단과대/학과별) | SSO |
| 12 | `kupid_get_syllabus` | 강의계획서 조회 | SSO |
| 13 | `kupid_lms_courses` | LMS 수강과목 목록 | KSSO |
| 14 | `kupid_lms_assignments` | LMS 과제 목록 (과목별) | KSSO |
| 15 | `kupid_lms_modules` | LMS 강의자료 (주차별 모듈) | KSSO |
| 16 | `kupid_lms_todo` | LMS 할 일 / 다가오는 이벤트 | KSSO |
| 17 | `kupid_lms_dashboard` | LMS 대시보드 + 공지사항 | KSSO |
| 18 | `kupid_lms_grades` | LMS 성적/점수 조회 | KSSO |
| 19 | `kupid_lms_submissions` | LMS 과제 제출 현황 | KSSO |
| 20 | `kupid_lms_quizzes` | LMS 퀴즈/시험 목록 | KSSO |

> **인증 안내**: SSO = KUPID 포털 인증, KSSO = 고려대 통합 SSO (Canvas LMS용). 모두 같은 ID/PW를 사용하며, 환경변수만 설정하면 자동으로 로그인됩니다.

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

### 3. 동작 확인

Claude Code에서 아래 명령을 입력해보세요:

```
> 도서관 좌석 현황 보여줘
```

로그인 없이 바로 결과가 나오면 정상적으로 설치된 것입니다.

## 프로젝트 구조

```
ku_portal_mcp/
├── server.py      # MCP 서버 + 17개 tool 등록
├── auth.py        # KUPID SSO 로그인, 세션 캐싱 (30분 TTL)
├── scraper.py     # GRW 공지/일정/장학 파싱
├── library.py     # 도서관 좌석 현황 (librsv.korea.ac.kr)
├── timetable.py   # 수업시간표 + ICS export
├── courses.py     # 개설과목 검색, 강의계획서 (infodepot.korea.ac.kr)
└── lms.py         # Canvas LMS 연동 (mylms.korea.ac.kr, KSSO SAML)
```

## 기술 스택

| 영역 | 기술 | 설명 |
|------|------|------|
| MCP | FastMCP (mcp[cli]) | Claude Code 연동 프로토콜 |
| HTTP | httpx (async) | 비동기 HTTP 클라이언트 |
| 파싱 | BeautifulSoup4 + lxml | HTML 스크래핑 |
| 포털 인증 | KUPID SSO | 동적 폼 필드 + ssotoken 추출 |
| LMS 인증 | KSSO SAML SSO | SAML IdP 로그인 + RSA 복호화 |
| 암호화 | cryptography | Canvas 임시 비밀번호 RSA 복호화 |
| 도서관 | HODI REST API | librsv.korea.ac.kr (인증 불필요) |
| 개설과목 | infodepot | SSO token handoff 방식 세션 연동 |
| LMS API | Canvas REST API | mylms.korea.ac.kr 세션 쿠키 인증 |

## 라이선스

MIT
