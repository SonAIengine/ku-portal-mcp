# Changelog

이 프로젝트의 주요 변경사항을 기록합니다.
[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식을 따르며 [Semantic Versioning](https://semver.org/lang/ko/)을 사용합니다.

## [0.14.0] - 2026-08-07

차세대 포털 대응 2단계. **포털 로그인을 복구**하고 공지·장학 본문/첨부 조회를 되살렸습니다.

### 추가
- `ku_portal_mcp/sso.py` — 고려대 통합 로그인(`sso.korea.ac.kr`) 클라이언트.
  새 로그인 폼이 비밀번호를 AES-128-CBC로 암호화해 보내는 것을 그대로 재현한다
  (`base64(AES-CBC(key, iv, "<pw>|<salt>")) + "|" + base64(iv)`).
  CryptoJS 레퍼런스 구현과 ASCII/한글/경계길이 3개 케이스에서 바이트 단위 일치를 검증했다.
  salt와 `l_token`은 로그인 페이지마다 서버가 새로 발급하므로 매번 파싱한다.
- `sso.follow_auto_forms` — SSO 구간이 302가 아니라 자동 제출 폼과 JS `location` 이동으로
  이어져 `follow_redirects`만으로는 흐름이 끊긴다. 폼 체인과 JS 이동을 함께 추적한다.
- `portal_api.fetch_post_detail` / `parse_post_detail` — 게시글 본문·첨부 파싱.

### 변경
- **`auth.py` 전면 재작성** — 레거시 `.kpd` 로그인 + GRW 세션 → SSO 기반으로 전환.
  SSO 로그인만으로는 포털 앱 세션이 서지 않아
  `index.jsp` → `sso_loginuser.jsp` → `POST /proc/Login.eps` 체인까지 완주하고
  학생 포털(`/p/ST/`) 도달을 확인해야 세션으로 인정한다.
- `Session` — `ssotoken`/`PORTAL_SESSIONID`/`GRW_SESSIONID` → 쿠키 전체 보관.
  포털과 SSO가 같은 이름(`JSESSIONID`)의 다른 쿠키를 쓰므로 도메인·경로까지 저장한다.
- **`kupid_get_notice_detail` / `kupid_get_scholarship_detail` — 로그인 시 본문 전문과
  첨부파일(파일명/크기/다운로드 URL)을 반환.** 로그인이 안 되면 기존 요약으로 폴백한다.
- 본문 텍스트화 — 포털 본문은 `<span>2</span>차` 처럼 인라인으로 잘게 쪼개져 있어
  구분자를 넣은 `get_text`는 단어 중간을 끊는다. 블록 요소와 `<br>`에서만 줄을 나눈다.

### 제거
- `ku_portal_mcp/scraper.py` — GRW(`grw.korea.ac.kr`) 전용이며 서비스가 종료됐고 참조도 없다.

### 확인된 학교 시스템 변경
- 통합 로그인이 `ksso.korea.ac.kr`(`*.do`) → `sso.korea.ac.kr`(`*.eps`)로 이전.
- LMS IdP 진입점이 `/exsignon/` → `/exsignon_new/sso/sso_idp_login.php`로 변경.
- LMS가 Canvas(`mylms`)에서 `lms.korea.ac.kr`(Laravel) 체계로 이전 중. Canvas API는 401/404.
- 학사 기능이 `infodepot` → `ams.korea.ac.kr`로 이전.
  포털 메뉴 API(`/sp/main/allMenu/list`)에서 메뉴 코드를 확인했다 —
  수강신청조회 `M111422`, 시간표조회 `M111423`, 전체성적조회 `M112493`, 강의실안내 `M112596`.
- 이 계정 기준으로 2차 보안인증(OTP/푸시)은 로그인 시 요구되지 않았다.

### 알려진 이슈
- LMS 14개와 수강·성적·시간표 6개는 여전히 동작하지 않는다. 학교가 백엔드를 교체해
  호스트 치환이 아니라 API 재작성이 필요하다.
- 무인증 게시판 조회는 최신 500건까지만 가능하다(암호화된 `encQS` 페이징이 세션에 묶여 있음).

## [0.13.0] - 2026-08-07

2026년 고려대 **차세대 포털 전환** 대응 1단계. 레거시 백엔드가 서비스를 종료하면서
공지·학사일정·장학 계열을 무인증 공개 API로 전환했습니다.

### 배경 — 확인된 학교 시스템 변경
- 레거시 포털 경로(`/front/Intro.kpd`, `/common/Login.kpd`, `/front/Main.kpd`)가 전부 `301 → /index.jsp`로 폐지.
  새 인증은 `sso.korea.ac.kr/svc/tk/Auth.eps` 기반 SSO.
- `infodepot.korea.ac.kr`, `grw.korea.ac.kr`, `ksso.korea.ac.kr` **서비스 종료** (TCP 443만 열려 있고 TLS 협상 실패).
- 통합 로그인이 `ksso` → `sso.korea.ac.kr`로 이전, 엔드포인트 확장자도 `.do` → `.eps`로 변경.
- **2026-07-20 13:00부터 학사·행정·연구·전자결재·LMS·통계에 2차 보안인증(OTP/푸시) 적용.**

### 추가
- `ku_portal_mcp/portal_api.py` — 차세대 포털 게시판 JSON API(`/ctt/svc/bulletin`) + 교무처 학사일정 클라이언트.
  **인증 불필요.** 게시판 ID 매핑(공지 6, 장학 10, 부고 1, 행사 3, 세종 13 등) 포함.
- `kupid_get_schedules`에 `month` 필터 — 특정 월 학사일정만 조회 (예: `month="9월"`).

### 변경
- **`kupid_get_notices` / `kupid_get_scholarships` / `kupid_search` — 로그인 불필요로 전환.**
  GRW HTML 스크래핑 → 포털 공개 JSON API. 응답에 `department`, `views`, `is_notice`,
  `attachments`, `comments`, `summary`, `total` 필드 추가.
- **`kupid_get_schedules` — 게시판 목록에서 학사일정표로 소스 변경** (`registrar.korea.ac.kr`).
  파라미터가 `page`/`count` → `year`/`semester`/`month`로 바뀌었습니다. 계절학기는 인접 정규학기로 매핑됩니다.
- **`kupid_get_notice_detail` / `kupid_get_scholarship_detail` — 파라미터가 `notice_id`+`message_id` → `post_seq`로 변경.**
  차세대 포털이 본문 전문·첨부에 로그인을 요구하므로 요약(약 200자)과 원문 링크를 반환합니다.
- `kupid_search`의 `board` 옵션에서 `schedule` 제거 (학사일정은 게시판이 아님) → `all`/`notice`/`scholarship`.

### 제거
- **`kupid_get_schedule_detail`** — 학사일정이 게시판에서 표 형태로 바뀌어 상세 개념이 사라졌습니다. (tool 31개 → 30개)

### 알려진 이슈
- 로그인이 필요한 tool 22개(`kupid_login`, 수강/성적/시간표 6개, LMS 14개)는 SSO 이전과
  2차 보안인증 대응이 끝날 때까지 동작하지 않습니다. 후속 단계에서 복구 예정입니다.
- 무인증 게시판 조회는 최신 500건까지만 가능합니다. 포털이 그 이후 페이징을
  암호화된 `encQS` URL + 로그인 세션에 묶어두었습니다.

## [0.12.0] - 2026-06-07

### 추가
- **`kupid_lms_announcements`** — 과목 공지(announcement)를 본문 절단 없이 전문(HTML)으로 조회. `course_id` 생략 시 활성 과목 전체. (기존엔 `kupid_lms_dashboard`에서 300자로 잘려서만 볼 수 있었음)
- `ku_portal_mcp/_storage.py` — 세션 캐시 파일을 0600 권한 + atomic write(temp→`os.replace`)로 안전하게 저장하는 공용 유틸.

### 변경
- **`kupid_lms_get_board_post`** — 게시글 **댓글(`comments`)을 본문/첨부와 함께 반환**. 댓글 첨부의 직접 다운로드 `url` 포함. (텀프로젝트 발표 동영상처럼 댓글로 제출되는 자료를 조회 가능. 이전엔 LearningX 응답에 댓글이 있는데도 버려졌음)
- **`kupid_lms_assignments`** — 본인 제출 상태(`submission`: workflow_state/제출시각/점수/지각/미제출), `lock_at`/`unlock_at` 추가. `description` 절단 500→2000자. fetch에 `include[]=submission`.
- **`kupid_lms_submissions`** — 교수 피드백 `comments`(작성자/내용/시각), 제출 `attachments`(파일 url), `preview_url`, `attempt` 추가. (이전엔 코멘트 개수만 반환)
- **`kupid_lms_todo`** — 과목명(`context_name`)과 `points_possible` 추가. (어느 과목 과제인지 식별 가능)
- **`kupid_lms_grades`** — 중간 성적 구간 점수(`current_period_score`/`grade`), `html_url`, `last_activity_at` 추가.
- `save_session`/`_save_lms_session` — 평문 0644 저장 → 0600 권한 + atomic write로 토큰 노출 위험 차단.
- LMS 목록 fetch의 `per_page` 50/30 → 100 상향 (과제/공지/제출/모듈/퀴즈 잘림 완화).

### 수정
- **세션 재시도 로직 안정화** — `_RETRIABLE`에서 `KeyError`/`IndexError`/`AttributeError` 제거. 응답 스키마/파싱 버그를 "세션 만료"로 오인해 매 호출마다 전체 SSO 재로그인하던 문제 해결 (반복 재인증으로 인한 계정 잠금 위험 제거).
- **board JWT 캐시 무효화** — `_clear_lms_session()` 시 `_board_jwt_cache.clear()`. 세션 재발급 후에도 stale JWT(최대 90분)를 반환해 게시판 호출이 실패하던 문제 해결.
- `scraper.py` 미사용 변수(`rows`, `title_match`) 제거.

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
