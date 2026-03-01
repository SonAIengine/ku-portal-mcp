# Contributing to ku-portal-mcp

고려대학교 KUPID 포털 MCP 서버에 기여해 주셔서 감사합니다!

## 시작하기

### 개발 환경 설정

```bash
# 1. Fork & Clone
git clone https://github.com/<your-username>/ku-portal-mcp.git
cd ku-portal-mcp

# 2. 가상환경 생성 (권장)
python3 -m venv .venv
source .venv/bin/activate

# 3. 개발 모드 설치
pip install -e .

# 4. 환경변수 설정 (테스트 시 필요)
cp .env.example .env
# .env 파일에 KUPID 계정 정보 입력
```

### 요구사항

- Python 3.10 이상
- KUPID 포털 계정 (실제 API 테스트 시)

## 기여 방법

### Issue

- 버그 리포트, 기능 제안, 질문 모두 환영합니다.
- 이미 동일한 Issue가 있는지 먼저 확인해 주세요.

### Pull Request

1. **Fork** → 본인 저장소에서 작업
2. **Branch** 생성: `feature/기능명`, `fix/버그명`, `docs/문서명`
3. **Commit** 메시지는 변경 내용을 명확하게
4. **PR** 제출 시 변경 사항과 테스트 방법을 설명

### 커밋 메시지 형식

```
<type>: <description>

# 예시
feat: add library notice board (kind=90)
fix: handle session timeout on detail page
docs: add pip install instructions
refactor: extract common HTML parser
```

| Type | 설명 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 변경 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, CI 등 기타 |

## 코드 가이드라인

### 구조

```
ku_portal_mcp/
├── server.py    # FastMCP tool 정의 (진입점)
├── auth.py      # 로그인/세션 관리
└── scraper.py   # HTML 파싱 (EUC-KR)
```

### 스타일

- Python 표준 스타일 (PEP 8)
- Type hint 사용 권장
- 독스트링은 한국어 (사용자에게 노출되는 tool 설명)
- 변수명/함수명은 영문

### 새로운 게시판 (kind) 추가 시

KUPID 포털의 게시판은 `kind` 파라미터로 구분됩니다:

| kind | 게시판 |
|------|--------|
| 11 | 공지사항 |
| 89 | 학사일정 |
| 88 | 장학공지 |

새 게시판을 추가하려면:

1. `server.py`에 `kupid_get_<board>` / `kupid_get_<board>_detail` tool 추가
2. `scraper.py`에 해당 게시판의 파싱 로직이 기존과 다르면 파서 추가
3. README.md 기능 표 업데이트

### 주의사항

- `.env` 파일이나 인증 정보를 절대 commit하지 마세요
- KUPID 포털의 인증 플로우가 변경되면 `auth.py`를 우선 확인하세요
- HTML 파싱은 EUC-KR 인코딩을 고려해야 합니다

## 보안

보안 취약점을 발견하셨다면 Issue 대신 sonsj97@korea.ac.kr로 직접 연락해 주세요.

## License

기여하신 코드는 [MIT License](LICENSE)로 배포됩니다.
