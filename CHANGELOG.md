# Changelog

이 프로젝트의 주요 변경사항을 기록합니다.
[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식을 따르며 [Semantic Versioning](https://semver.org/lang/ko/)을 사용합니다.

## [0.11.0] - 2026-05-11

### 추가
- **`kupid_room_schedule`** — 건물/호실의 정규 수업 시간표 조회 (학부 + 대학원 통합).
  "이 강의실 오늘 비어있나?" 확인용.
- `kupid_search_courses`에 `is_grad` 옵션 — `LecGradMajorSub.jsp` 호출로 대학원 38개 단과대 검색.
- `GRAD_COLLEGE_CODES` 상수 (대학원 단과대 38개), `search_grad_courses`, `_parse_grad_course_table`.
- `parse_schedule()` — 강의 schedule 문자열을 `day`/`periods`/`location`/`start_time`/`end_time`으로 구조화.

### 변경
- 학부 검색(`LecMajorSub.jsp`)과 대학원 검색(`LecGradMajorSub.jsp`)의 컬럼 매핑 차이 처리.
- README: 섹션 7 "강의실 시간표" 신설, Tool 표에 14번 추가.

## [0.10.1] - 2026-04-05

### 수정
- sdist에 디버그 중 생성된 `.playwright-mcp/` 디렉토리(5MB PDF 포함)가 포함되어 배포되던 문제 수정.
  `[tool.hatch.build.targets.sdist]` exclude 설정 추가 + `.gitignore` 등록.

## [0.10.0] - 2026-04-05

### 추가
- **LearningX Board 3 tools** — Canvas 네이티브 모듈 밖에 있는 LTI tool(id=5)의 게시판 조회.
  교수님이 강의자료를 Canvas 모듈이 아닌 게시판(Q&A, 강의자료실 등)에 올리는 과목 대응.
  - `kupid_lms_list_boards` — 게시판 목록.
  - `kupid_lms_list_board_posts` — 게시글 목록 (페이지/키워드 검색).
  - `kupid_lms_get_board_post` — 게시글 상세 + 첨부파일 (`canvas_file_id`).
- LTI 1.1 launch로 board JWT 획득, course_id별 in-memory 캐싱(90분 TTL).

### 변경
- 첨부파일 다운로드는 `canvas_file_id`로 기존 `kupid_lms_download_file` 재사용.

## [0.9.0] - 2026-04-05

### 추가
- **`kupid_lms_download_file`** — Canvas 파일 스트리밍 다운로드 (세션 쿠키 + 리다이렉트 follow).
- `kupid_lms_modules` items에 `content_id`/`url` 필드 노출 (file_id 획득 경로).

### 보안
- 다운로드 경로 검증: 절대경로 강제, `~` 확장, `..` 차단, 동명파일 자동 suffix.

## [0.8.0] - 2026-03-29

### 추가
- **`kupid_lms_syllabus`** — Canvas LMS 수업 계획서를 구조화 JSON으로 조회 (#2, @mskim8717).
  - infodepot iframe을 직접 fetch하여 `course_info`/`professor`/`grading`/`learning_plan`/`weekly_schedule` 반환.
  - 학수번호(예: `BDC115`) → infodepot 수강과목 매칭 fallback.
  - 과목명 / 학수번호 / `course_id` 세 가지 방식으로 조회 가능.

### 보안
- iframe `src` URL 도메인 화이트리스트 검증 추가 (SSRF 방지).

## [0.7.0] - 2026-03-14

### 추가
- **`kupid_get_all_grades`** — 전체 성적, 누적 GPA, 취득학점 조회 (KUPID 학적/졸업 > 성적사항).

### 변경
- 테스트 커버리지 추가.

## [0.6.3] - 2026-03-09

### 수정
- `__version__` 표시 수정.

## [0.6.2] - 2026-03-09

### 변경
- **강의계획서 조회 — Allgen 우회**: 교내 전용 ActiveX 리포트 서버에 접근 불가 시,
  개설과목 목록 페이지에서 교수/학점/시간표 등 기본 정보를 추출하여 반환.
- 3단계 전략: Allgen 직접 접근 → 개설과목 목록 검색 → 파라미터 fallback.
- 학과 prefix → (단과대학, 학과) 매핑 90+ 학과 추가.
- 분반 정확 매칭 지원.

## [0.6.1] - 2026-03-02

### 수정
- `--version` / `--help` CLI flag 추가 — Claude Code의 시작 probe에서 binary가 hang하던 문제 해결.

### 변경
- `uvx`를 권장 설치 방법으로 README 변경.
- 트러블슈팅 섹션 추가 (연결 이슈).

## [0.6.0] - 2026-03-02

### 추가
- **`kupid_dept_notices` / `kupid_dept_notice_detail`** — 학과/대학원 공지 게시판 스크레이퍼 (인증 불필요).
  공통 CMS 구조를 사용하는 KU 학과 사이트(gscit, cs, edu, info 등) 대응.
- `KU_DEPT_URLS` 환경변수로 사이트 추가 설정 가능.

## [0.5.1] - 2026-03-01

### 추가
- **`kupid_my_courses`** — infodepot CourseListSearch에서 본인 수강신청 내역 조회.
  학수번호, 강의시간, 강의실, 교수 등 상세 정보. **대학원 과목 포함** (기존 tool로는 누락).

## [0.5.0] - 2026-03-01

### 추가
- **`kupid_lms_grades`** — Canvas LMS 성적/점수 (현재/최종 점수, 학점).
- **`kupid_lms_submissions`** — 과제 제출 현황 (점수, 채점, 지각/미제출).
- **`kupid_lms_quizzes`** — 퀴즈/시험 목록 (New Quizzes 404 fallback 포함).
- 총 20 tools.

### 변경
- **세션 회복력 개선**:
  - TTL 80% 시점 proactive refresh (KUPID: 마지막 6분/30분, LMS: 마지막 5분/25분).
  - 만료 임박 세션은 재사용 전 server-side verify (`verify_session`/`verify_lms_session`).
- 네트워크 호출 전 자격증명 사전 검증 — 한국어 에러 메시지로 변경.
- KSSO 에러 코드 한국어 번역 (`pwd_chk_fail` → "비밀번호가 틀렸습니다", `id_chk_fail`, `lock`).

## [0.4.1] - 2026-03-01

### 변경
- **SSO 세션 최적화**:
  - `_get_session()` / `_get_lms_session()`에 `asyncio.Lock` 추가 — 동시 중복 로그인 race condition 수정.
  - 재시도 예외 범위를 `_RETRIABLE` 튜플(`httpx.HTTPError`, `ValueError`, `RuntimeError` 등)로 좁힘 — 버그 마스킹 방지.
  - `kupid_lms_todo()` double `_lms_with_retry` 호출 수정 — todo와 events를 단일 retry scope에서 fetch.
  - 시간표(월~금) `asyncio.gather()` 병렬화 (~5배 빠름).
- 세션 만료 로깅 추가 (KUPID + LMS).

## [0.4.0] - 2026-03-01

### 추가
- **Canvas LMS 통합 5 tools** (mylms.korea.ac.kr):
  - `kupid_lms_courses` — 수강과목 목록.
  - `kupid_lms_assignments` — 과제 목록.
  - `kupid_lms_modules` — 주차별 강의자료(모듈).
  - `kupid_lms_todo` — 마감 임박 할일.
  - `kupid_lms_dashboard` — 대시보드 + 공지.
- KSSO SAML SSO 인증 + RSA로 복호화한 Canvas 비밀번호 사용.
- 총 17 tools (12 portal + 5 LMS).

### 변경
- `courses.py`의 Allgen 강의계획서 파싱 개선.

## [0.3.0] - 2026-03-01

### 추가
- **`kupid_get_library_seats`** — 도서관 열람실 좌석 실시간 현황 (HODI API, **인증 불필요**).
- **`kupid_get_timetable`** — 개인 수업시간표 + ICS 캘린더 export.
- **`kupid_search_courses`** — 단과대/학과별 개설과목 검색 (infodepot SSO 핸드오프).
- **`kupid_get_syllabus`** — 강의계획서 조회.
- 신규 모듈: `library.py`, `timetable.py`, `courses.py`.
- 총 12 tools.

## [0.2.0] - 2026-03-01

### 추가
- **`kupid_get_scholarships` / `kupid_get_scholarship_detail`** — 장학공지 (kind=88).
- **`kupid_search`** — 공지/일정/장학 통합 키워드 검색.
- `_with_retry()` 래퍼로 세션 만료 시 자동 재로그인.
- `CONTRIBUTING.md`, GitHub issue/PR 템플릿.

### 변경
- PyPI 메타데이터 정비 (homepage/repository/issues URL, Python 분류, education topic).
- 공통 포맷팅 로직을 `_format_items()`로 리팩터.

## [0.1.0] - 2026-03-01

### 추가
- 첫 릴리즈 — KUPID 포털 MCP 서버.
  - SSO 토큰 인증 로그인.
  - 공지사항 목록/상세 (kind=11).
  - 학사일정 목록/상세 (kind=89).
  - 세션 캐싱 (30분 TTL).
  - EUC-KR HTML 파싱 (BeautifulSoup).

[0.11.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.6.3...v0.7.0
[0.6.3]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SonAIengine/ku-portal-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SonAIengine/ku-portal-mcp/releases/tag/v0.1.0
