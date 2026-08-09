<p align="center">
  <img alt="Korea University" src="https://upload.wikimedia.org/wikipedia/commons/thumb/7/74/Korea_University_logotype_%28English_version%29.svg/320px-Korea_University_logotype_%28English_version%29.svg.png" width="320" />
</p>

# ku-portal-mcp

[![PyPI version](https://img.shields.io/pypi/v/ku-portal-mcp.svg)](https://pypi.org/project/ku-portal-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/ku-portal-mcp.svg)](https://pypi.org/project/ku-portal-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

고려대학교 KUPID 포털 MCP 서버 — Claude Code에서 대학 생활에 필요한 정보를 바로 조회

> "공지사항 보여줘", "도서관 빈자리 있어?", "이번 주 과제 뭐 있어?" 같은 자연어로 포털과 LMS를 사용할 수 있습니다.

<table>
  <tr>
    <td align="center" valign="top">
      <img alt="Claude Code에서 LMS 수강과목을 조회하는 모습" src="https://github.com/user-attachments/assets/23cb2b8d-78dc-4cd5-bc93-282ad6f54290" />
      <br>
      <em>"수업 뭐가 있나?" — LMS 수강과목 조회</em>
    </td>
    <td align="center" valign="top">
      <img alt="Claude Code에서 공지사항을 조회하는 모습" src="https://github.com/user-attachments/assets/1bde4127-9ff8-44ac-870d-c4d391407da5" />
      <br>
      <em>"공지사항 보여줘" — 전체 + 학과 공지 조회</em>
    </td>
  </tr>
</table>

## 2026 차세대 포털 전환 대응 (v0.13.0 → v0.17.0)

고려대학교가 2026년 포털·학사·LMS를 차세대 시스템으로 교체하면서
**기존 tool 31개 중 28개가 동작을 멈췄습니다.** v0.13.0~v0.17.0에 걸쳐 전부 복구했습니다.

### 무엇이 바뀌었나

| 영역 | 이전 | 이후 |
|---|---|---|
| 포털 | `*.kpd` 경로 | `index.jsp` + SSO (레거시 경로는 `301` 폐지) |
| 통합 로그인 | `ksso.korea.ac.kr` (`*.do`) | **`sso.korea.ac.kr` (`*.eps`)** — 비밀번호 AES 암호화 전송 |
| 공지·장학 | `grw.korea.ac.kr` HTML 스크래핑 | **포털 공개 JSON API** (`/ctt/svc/bulletin`) |
| 학사 | `infodepot.korea.ac.kr` | **`ams.korea.ac.kr`** + 2차 보안인증 필수 |
| LMS 진입 | `/exsignon/` | `/exsignon_new/` |
| 학사일정 | 포털 게시판 | 교무처 학사일정표 |

`infodepot` · `grw` · `ksso` 세 도메인은 **서비스가 종료**되어 TLS 협상조차 되지 않습니다.

### 무엇이 좋아졌나

- **공지·학사일정·장학·검색이 로그인 없이 동작합니다.** 스크래핑 대신 포털이 쓰는
  공개 JSON API로 옮겨, 더 빠르고 조회수·부서·첨부 수 같은 정보도 함께 옵니다.
- **공지/장학 상세가 본문 전문과 첨부파일**(파일명·크기·다운로드 링크)을 반환합니다.
- **LMS 14개 전부 복구.** Canvas API는 멀쩡했고 로그인 경로만 바뀐 것이었습니다.
- **학사 조회는 2차 인증 한 번으로 50분간** 유지됩니다. 매 호출마다 인증하지 않습니다.

### 무엇이 달라져 주의가 필요한가

- `kupid_get_schedules` — 파라미터가 `page`/`count` → **`year`/`semester`/`month`**
  (학사일정이 게시판에서 표 형태로 바뀌었습니다)
- `kupid_get_notice_detail` / `kupid_get_scholarship_detail` — 식별자가 **`post_seq`** 하나로
- `kupid_search_courses` / `kupid_room_schedule` — **교과목명 키워드**로 검색
  (학사 시스템이 단과대/학과 단위 목록 조회를 더 이상 제공하지 않습니다)
- `kupid_get_schedule_detail` 제거 — 학사일정에 상세 개념이 사라졌습니다
- `kupid_get_syllabus` 제거 — 학사 시스템에서 메뉴가 사라졌습니다.
  `kupid_lms_syllabus`를 사용하세요
- 무인증 게시판 조회는 **최신 500건**까지입니다
  (포털이 그 이후 페이징을 로그인 세션에 묶어두었습니다)

자세한 변경 이력은 [CHANGELOG.md](CHANGELOG.md)를 참고하세요.

## 이런 걸 할 수 있어요

### 1. 공지사항 / 학사일정 / 장학공지 (로그인 불필요)

KUPID 포털 게시판과 교무처 학사일정을 **로그인 없이** 조회하고 검색할 수 있습니다.

```
> 최근 공지사항 보여줘
> "수강신청" 관련 공지 검색해줘
> 이번 학기 학사일정 알려줘
> 9월 학사일정만 보여줘
> 장학금 관련 공지 있어?
```

- 공지사항(`b=6`), 장학공지(`b=10`) **목록 조회** — 작성자·부서·조회수·첨부 수·요약 포함
- **학사일정** — 교무처 학사일정표에서 학기별 조회, 월 단위 필터 지원
- 제목·요약 기준 **키워드 통합 검색**
- 게시글 **본문 전문과 첨부파일**은 포털 로그인 시 제공됩니다 (로그인 없으면 요약 약 200자 + 원문 링크)
- 무인증 목록 조회는 **최신 500건**까지 지원합니다 (포털이 그 이후 페이징을 로그인 세션에 묶어둠)

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

### 3. 학사 정보 조회 — 2차 보안인증 한 번이면 됩니다

수강신청내역·시간표·성적·개설과목·강의실은 **학사 시스템(AMS)** 에 있고,
학교 정책상 **2차 보안인증**을 거쳐야 합니다. 처음 한 번만 인증하면
약 50분간 세션이 유지되어 그동안은 그냥 물어보면 됩니다.

```
> 학사 인증 시작해줘          ← 포털에 등록된 메일로 6자리 코드가 옵니다
> 코드 123456                ← 인증 완료, 이후 50분간 자유롭게 조회
```

추가 설치나 브라우저는 필요 없습니다.
코드는 **KUPID 포털에 등록된 이메일**로 오며, 따로 등록할 것은 없습니다
(자세한 내용은 [설치 > 학사 조회를 쓰려면](#학사-조회를-쓰려면) 참고).
공지·LMS·도서관 등 나머지 기능은 이 인증과 무관합니다.

### 4. 수업시간표 + ICS 내보내기

```
> 이번 주 시간표 보여줘
> 월요일 수업 뭐 있어?
> 시간표를 ICS 파일로 만들어줘
```

- 월~토 **요일별 조회** 또는 **전체 주간 시간표**
- 교시 → 실제 시간 자동 변환 (1교시=09:00~10:15 … 야간 11교시까지)
- **ICS 캘린더 파일** 생성 → 구글/Apple 캘린더에 바로 추가
- 과목명, 강의실, 교시 포함

### 5. 내 수강신청 내역

```
> 내 수강과목 보여줘
> 이번 학기 뭐 듣고 있어?
> 총 몇 학점 신청했어?
```

- 학수번호·분반·이수구분·교과목명·담당교수·학점
- 강의시간/강의실 (예: `월(7-8) 애기능생활관 301호`)
- 신청 상태와 등록금 수납 상태
- 총 신청 학점 합산
- 학기를 지정하지 않으면 현재 학기, 지정하면 해당 학기 (`year`, `semester`)

### 6. 전체 성적 / 누적 GPA / 취득학점

```
> 전체 성적 보여줘
> 누적 GPA 얼마야?
> 2026학년도 1학기 성적만 보여줘
```

- 과목별 **등급(A+/B+…)과 평점**, 이수구분, 학점
- **누적 GPA · 취득학점 · 총평점 · 환산점수 · 전공학점**
- `year_term`(예: `20261R`)으로 학기 필터링

### 7. 개설과목 검색 · 강의실 조회

```
> "자연어처리" 개설과목 검색해줘
> 딥러닝 수업 어느 강의실이야?
> 정보통신관에서 하는 딥러닝 수업 있어?
```

- **교과목명 키워드**로 검색 → 학수번호·분반·강의실·건물·캠퍼스
- 건물명·캠퍼스로 결과 필터링
- ℹ️ 학사 시스템이 제공하는 검색 조건이 교과목명뿐이라,
  예전처럼 단과대/학과 단위로 목록을 훑는 방식은 더 이상 지원하지 않습니다.
- ℹ️ 강의계획서는 `kupid_lms_syllabus`(LMS)를 사용하세요.

### 8. Canvas LMS — 수강과목 / 과제 / 강의자료

고려대학교 Canvas LMS(mylms.korea.ac.kr)에 접속하여 수강 정보를 조회합니다.

```
> LMS에 어떤 과목 듣고 있어?
> 딥러닝 과제 목록 보여줘
> 아직 안 낸 과제 있어?
> 자연어처리 강의자료 보여줘
> 텍스트마이닝 1주차 PDF 다운로드해줘
> 이번 주 제출할 과제 뭐야?
> LMS 대시보드 보여줘
> 딥러닝 성적 어때?
> 과제 제출 현황 보여줘
> 퀴즈 일정 있어?
```

- **수강과목 목록**: 현재 학기 수강 중인 과목과 학기 정보
- **과제 목록**: 과목별 과제, 제출 기한, 배점, 제출 방식 확인
- **강의자료(모듈)**: 주차별 강의 모듈과 포함된 자료(강의 영상, PDF, 퀴즈 등)
- **파일 다운로드**: 강의자료 PDF 등을 지정한 로컬 디렉토리에 직접 저장
- **게시판 조회**: Q&A 게시판 / 강의자료실 등 교수님이 직접 올리는 자료까지 탐색
- **할 일 목록**: 마감이 다가오는 과제와 이벤트를 한눈에
- **대시보드**: 수강 과목 카드 + 과목별 공지사항 모아보기
- **성적/점수 조회**: 과목별 현재 점수, 최종 점수, 학점 확인
- **과제 제출 현황**: 제출 여부, 채점 점수, 지각/미제출 상태 확인
- **퀴즈/시험 목록**: 퀴즈 일정, 시간제한, 문항 수 확인

> 더 많은 사용 예시는 [EXAMPLES.md](EXAMPLES.md)를 참고하세요.

---

## 전체 Tool 목록

| # | Tool | 설명 | 인증 |
|---|------|------|------|
| 1 | `kupid_login` | 포털 로그인 / 세션 확인 | SSO |
| 2 | `kupid_get_notices` | 공지사항 목록 | **불필요** |
| 3 | `kupid_get_notice_detail` | 공지사항 상세 (로그인 시 **본문 전문 + 첨부**) | 선택 |
| 4 | `kupid_get_schedules` | 학사일정 (학기별, 월 필터) | **불필요** |
| 5 | `kupid_get_scholarships` | 장학공지 목록 | **불필요** |
| 6 | `kupid_get_scholarship_detail` | 장학공지 상세 (로그인 시 **본문 전문 + 첨부**) | 선택 |
| 7 | `kupid_search` | 공지/장학 통합 검색 | **불필요** |
| 8 | `kupid_get_library_seats` | 도서관 열람실 좌석 현황 | **불필요** |
| 9 | `kupid_ams_auth_start` | 학사(AMS) 2차 인증 시작 — 메일로 코드 발송 | SSO |
| 10 | `kupid_ams_auth_verify` | 학사(AMS) 2차 인증 완료 (6자리 코드) | SSO |
| 11 | `kupid_my_courses` | 내 수강신청 내역 (학수번호/시간/강의실) | **AMS 2차** |
| 12 | `kupid_get_timetable` | 개인 수업시간표 + ICS 내보내기 | **AMS 2차** |
| 13 | `kupid_get_all_grades` | 전체 성적 / 누적 GPA / 취득학점 | **AMS 2차** |
| 14 | `kupid_search_courses` | 개설과목 검색 (교과목명) | **AMS 2차** |
| 15 | `kupid_room_schedule` | 교과목의 강의실·건물 조회 | **AMS 2차** |
| 16 | `kupid_lms_courses` | LMS 수강과목 목록 | SSO |
| 17 | `kupid_lms_assignments` | LMS 과제 목록 (과목별) | SSO |
| 18 | `kupid_lms_modules` | LMS 강의자료 (주차별 모듈) | SSO |
| 19 | `kupid_lms_todo` | LMS 할 일 / 다가오는 이벤트 | SSO |
| 20 | `kupid_lms_dashboard` | LMS 대시보드 + 공지사항 | SSO |
| 21 | `kupid_lms_grades` | LMS 성적/점수 조회 | SSO |
| 22 | `kupid_lms_submissions` | LMS 과제 제출 현황 | SSO |
| 23 | `kupid_lms_quizzes` | LMS 퀴즈/시험 목록 | SSO |
| 24 | `kupid_lms_download_file` | LMS 강의자료 파일 다운로드 (PDF 등) | SSO |
| 25 | `kupid_lms_list_boards` | LMS 과목 게시판 목록 (Q&A, 강의자료실 등) | SSO |
| 26 | `kupid_lms_list_board_posts` | 게시판 게시글 목록 | SSO |
| 27 | `kupid_lms_get_board_post` | 게시글 상세 + 첨부파일 + **댓글(첨부 포함)** | SSO |
| 28 | `kupid_lms_announcements` | LMS 공지 전문 조회 (과목별 또는 전체, 본문 비절단) | SSO |
| 29 | `kupid_lms_syllabus` | LMS 강의계획서 조회 | SSO |
| 30 | `kupid_dept_notices` | 학과/대학원 홈페이지 공지 목록 | **불필요** |
| 31 | `kupid_dept_notice_detail` | 학과/대학원 공지 상세 | **불필요** |

> **인증 안내**: SSO = 고려대 통합 로그인(`sso.korea.ac.kr`). 포털과 LMS 모두 같은 ID/PW를 사용하며, 환경변수만 설정하면 자동으로 로그인됩니다.
>
> **선택** = 로그인 없이도 동작하지만, 로그인하면 더 많은 정보를 반환합니다.
>
> **AMS 2차** = 학사 시스템은 학교 정책상 2차 보안인증이 필수입니다.
> `kupid_ams_auth_start()` → **포털에 등록된 메일**로 온 6자리 코드로
> `kupid_ams_auth_verify(code)` 하면 약 50분간 세션이 유지되며,
> 그동안은 재인증 없이 조회됩니다. v0.18.0부터 별도 설치 없이 동작합니다.

## 설치

### 방법 1: uvx (권장)

설치 없이 항상 최신 버전을 실행합니다. Claude Code와의 호환성이 가장 좋습니다.

```bash
uvx ku-portal-mcp
```

### 방법 2: pip

```bash
pip install ku-portal-mcp
```

### 방법 3: 소스에서 설치

```bash
git clone https://github.com/SonAIengine/ku-portal-mcp.git
cd ku-portal-mcp
pip install -e .
```

### 학사 조회를 쓰려면

수강신청내역·시간표·성적·개설과목·강의실은 학사 시스템의 **2차 보안인증**을 통과해야 합니다.
**추가 설치는 필요 없습니다.** 위 설치만으로 31개 tool 전부가 동작합니다.

```
> 학사 인증 시작해줘          ← 메일로 6자리 코드가 옵니다
> 코드 123456                ← 인증 완료, 이후 50분간 자유롭게 조회
```

> v0.17.x까지는 이 인증에 `playwright`와 Chromium(수백 MB) 설치가 필요했지만,
> v0.18.0에서 순수 HTTP로 재구현해 의존성을 없앴습니다.

#### 인증 코드는 어디로 오나요

**KUPID 포털에 등록된 이메일 주소**로 옵니다. 따로 등록할 것은 없습니다 —
포털 가입 때 넣은 주소가 그대로 쓰입니다.

| 궁금한 것 | 답 |
|---|---|
| 주소를 바꾸려면 | [포털](https://portal.korea.ac.kr) > **My Page > 개인정보 수정** |
| MCP에 이메일을 등록하나요 | **아니요.** 환경변수는 `KU_PORTAL_ID` / `KU_PORTAL_PW` 둘뿐입니다 |
| 메일이 안 와요 | **스팸함**을 확인하세요. 학교 안내에도 명시된 흔한 경우입니다 |
| 코드 유효시간 | 5분. 지나면 인증을 다시 시작하면 됩니다 |

> **이 MCP는 메일을 보내지 않습니다.** 학교 SSO 서버에 "발송해 달라"고 요청할
> 뿐이고(요청 바디에 주소를 싣지 않습니다), 서버가 세션으로 사용자를 식별해
> 등록된 주소로 직접 보냅니다. 응답으로는 마스킹된 형태(`son****@gmail.com`)만
> 돌아옵니다. 따라서 이 도구가 임의의 주소로 코드를 보내는 것은 구조적으로
> 불가능하며, 코드는 언제나 계정 주인의 메일함으로만 갑니다.

## 업데이트

학교가 시스템을 바꾸면 tool이 동작을 멈출 수 있습니다. 그럴 때 최신 버전으로 올리세요.

### uvx로 쓰는 경우

uvx는 **캐시된 버전을 재사용**하기 때문에 그냥 재시작해도 옛 버전이 뜹니다.
캐시를 지우고 다시 받아야 합니다.

```bash
uv cache clean ku-portal-mcp
```

이후 Claude Code를 재시작하면 최신 버전이 설치됩니다.
특정 버전을 고정하려면 MCP 설정의 `args`에 `ku-portal-mcp@0.17.0` 처럼 적으면 됩니다.

### pip으로 쓰는 경우

```bash
pip install --upgrade ku-portal-mcp
```

### 소스로 쓰는 경우

```bash
cd ku-portal-mcp
git pull
pip install -e .
```

### 업데이트 후 확인

**Claude Code를 반드시 재시작**해야 새 버전이 적용됩니다 (MCP 서버는 시작 시 한 번 로드됩니다).

```bash
claude mcp list          # 연결 상태 확인
uvx ku-portal-mcp --version
```

Claude Code 안에서는 이렇게 확인할 수 있습니다.

```
> 공지사항 3개만 보여줘        ← 무인증 기능이 되는지
> 학사 인증 시작해줘           ← 학사 기능이 되는지
```

> **환경변수를 바꿨을 때도 재시작이 필요합니다.** MCP 서버는 시작 시점의 환경변수를 읽습니다.
> `~/.zshrc`에서 비밀번호를 설정한다면 **작은따옴표**를 쓰세요 —
> 큰따옴표 안의 `\!` 같은 이스케이프는 백슬래시가 값에 그대로 남아 로그인이 실패합니다.
> ```bash
> export KU_PORTAL_PW='p@ssw0rd!'   # O
> export KU_PORTAL_PW="p@ssw0rd\!"  # X — 값이 `p@ssw0rd\!` 가 됩니다
> ```

## Claude Code에서 사용하기

### 1. MCP 서버 등록

`claude mcp add` CLI 명령으로 등록합니다:

**uvx 사용 (권장):**
```bash
claude mcp add -s user \
  -e KU_PORTAL_ID=your-kupid-id \
  -e KU_PORTAL_PW=your-kupid-password \
  ku-portal \
  uvx ku-portal-mcp@latest
```

**pip으로 설치한 경우:**
```bash
claude mcp add -s user \
  -e KU_PORTAL_ID=your-kupid-id \
  -e KU_PORTAL_PW=your-kupid-password \
  ku-portal \
  ku-portal-mcp
```

> - `KU_PORTAL_ID`와 `KU_PORTAL_PW`는 KUPID 포털 로그인에 사용하는 학번과 비밀번호입니다.
> - `-s user`는 글로벌(모든 프로젝트) 등록입니다. 특정 프로젝트에서만 사용하려면 `-s project`로 변경하세요.

### 2. 설정 적용

MCP 서버 설정은 Claude Code **시작 시점에 1회** 로드됩니다.

- **방법 A**: Claude Code를 재시작
- **방법 B**: 세션 내에서 `/mcp` 명령어 실행 → MCP 서버 추가/재시작을 재시작 없이 바로 적용

### 3. 동작 확인

Claude Code에서 아래와 같이 자연어로 물어보세요:

```
> 도서관 좌석 현황 보여줘
```

로그인 없이 바로 결과가 나오면 정상적으로 설치된 것입니다.

```
> 최근 공지사항 보여줘
> 이번 주 과제 뭐 있어?
> 내 시간표 보여줘
```

### 4. `/ku` 슬래시 커맨드 활용

[`examples/commands/ku.md`](examples/commands/ku.md)를 Claude Code의 커스텀 슬래시 커맨드로 등록하면, `/ku` 한 줄로 포털 조회를 더 빠르게 할 수 있습니다.

**설치:** `examples/commands/ku.md` 파일을 프로젝트의 `.claude/commands/` 또는 `~/.claude/commands/`에 복사합니다.

```bash
# 글로벌 커맨드로 등록 (모든 프로젝트에서 사용)
mkdir -p ~/.claude/commands
cp examples/commands/ku.md ~/.claude/commands/ku.md
```

**사용 예시:**
```
> /ku 도서관
> /ku 공지 수강신청
> /ku 과제
> /ku 시간표
> /ku 성적
> /ku 검색 장학금
```

> 슬래시 커맨드는 필요한 MCP tool만 자동으로 허용하므로, 자연어 질의보다 빠르고 정확하게 동작합니다. 자세한 키워드 목록은 [`examples/commands/ku.md`](examples/commands/ku.md)를 참고하세요.

## 프로젝트 구조

```
ku_portal_mcp/
├── server.py       # MCP 서버 + 31개 tool 등록
├── sso.py          # 고려대 통합 로그인 (sso.korea.ac.kr) — 비밀번호 AES 암호화
├── auth.py         # 포털 세션 확립, 세션 캐싱 (30분 TTL)
├── portal_api.py   # 포털 게시판 JSON API + 교무처 학사일정 (무인증)
├── ams.py          # 학사 시스템 (ams.korea.ac.kr) 조회 API
├── _ams_auth.py    # 학사 2차 보안인증 헬퍼 (브라우저 자동화, 선택 의존성)
├── _storage.py     # 세션 캐시 보안 저장 (0600, atomic write)
├── library.py      # 도서관 좌석 현황 (librsv.korea.ac.kr)
├── timetable.py    # 교시↔시간 변환 + ICS export
├── dept_notices.py # 학과/대학원 홈페이지 공지
└── lms.py          # Canvas LMS 연동 (mylms.korea.ac.kr)
```

## 기술 스택

| 영역 | 기술 | 설명 |
|------|------|------|
| MCP | FastMCP (mcp[cli]) | Claude Code 연동 프로토콜 |
| HTTP | httpx (async) | 비동기 HTTP 클라이언트 |
| 파싱 | BeautifulSoup4 + lxml | HTML 스크래핑 |
| 통합 인증 | sso.korea.ac.kr | AES-128-CBC 비밀번호 암호화 + 자동 제출 폼 체인 추적 |
| 학사 인증 | IOP 2차 보안인증 | 이메일 OTP, 브라우저 컨텍스트 검증 |
| LMS 인증 | Canvas 인계 | RSA 복호화한 임시 비밀번호 + Rails CSRF |
| 암호화 | cryptography | AES(로그인) / RSA(Canvas) |
| 공지·장학 | 포털 JSON API | `/ctt/svc/bulletin` (인증 불필요) |
| 학사 조회 | AMS DataSet API | 넥사크로 규약 (`@d1#<필드>`) |
| 도서관 | HODI REST API | librsv.korea.ac.kr (인증 불필요) |
| LMS API | Canvas REST API | mylms.korea.ac.kr 세션 쿠키 인증 |
| 브라우저 | Playwright (선택) | 학사 2차 인증 전용 |

## 트러블슈팅

### MCP 서버가 연결되지 않을 때

1. 서버가 정상 동작하는지 확인:
   ```bash
   ku-portal-mcp --version
   ```

2. 서버가 등록되어 있는지 확인:
   ```bash
   claude mcp list
   ```
   목록에 `ku-portal`이 없으면 [설치 > 1. MCP 서버 등록](#1-mcp-서버-등록)을 참고하세요.

3. Claude Code 재시작 후 `/mcp` 명령으로 서버 상태 확인

### MCP 서버가 목록에 보이지 않을 때

Claude Code는 MCP 서버 설정을 `~/.claude.json`에서 읽습니다. `~/.claude/settings.json`의 `mcpServers`에 넣으면 **인식되지 않습니다.**

반드시 `claude mcp add` 명령으로 등록하세요:
```bash
claude mcp add -s user \
  -e KU_PORTAL_ID=your-id \
  -e KU_PORTAL_PW=your-pw \
  ku-portal \
  uvx ku-portal-mcp@latest
```

### 서버 시작 시 타임아웃이 발생할 때

서버 초기화에 수 초가 걸릴 수 있습니다. 기본 타임아웃이 짧아 연결 실패가 발생하면, `~/.claude/settings.json`의 `env`에 타임아웃을 늘려주세요:

```json
{
  "env": {
    "MCP_TIMEOUT": "30000"
  }
}
```

### 환경변수 관련

- `claude mcp add` 시 `-e` 옵션으로 환경변수를 설정합니다
- 이미 등록된 서버의 환경변수를 변경하려면 `claude mcp remove ku-portal` 후 다시 추가하세요

## 라이선스

MIT
