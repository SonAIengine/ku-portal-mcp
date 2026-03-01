# ku-portal-mcp

> 고려대학교 SW.AI 융합대학원 61기 인공지능학과 손성준

고려대학교 KUPID 포털을 [Claude Code](https://claude.ai/claude-code)에서 바로 사용할 수 있는 MCP (Model Context Protocol) 서버입니다.

## 기능

| Tool | 설명 |
|------|------|
| `kupid_login` | KUPID 포털 로그인 / 세션 확인 |
| `kupid_get_notices` | 공지사항 목록 조회 |
| `kupid_get_notice_detail` | 공지사항 상세 조회 (본문 + 첨부파일) |
| `kupid_get_schedules` | 학사일정 목록 조회 |
| `kupid_get_schedule_detail` | 학사일정 상세 조회 |
| `kupid_get_scholarships` | 장학공지 목록 조회 |
| `kupid_get_scholarship_detail` | 장학공지 상세 조회 |
| `kupid_search` | 키워드 검색 (공지/학사일정/장학 통합) |

## 설치

### Claude Code (권장)

```bash
claude mcp add ku-portal \
  -- python3 -m ku_portal_mcp.server \
  -e KU_PORTAL_ID=학번 \
  -e KU_PORTAL_PW=비밀번호
```

### 수동 설치

```bash
# 1. 클론
git clone https://github.com/SonAIengine/ku-portal-mcp.git
cd ku-portal-mcp

# 2. 의존성 설치
pip install -e .

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 학번/비밀번호 입력

# 4. Claude Code에 등록
claude mcp add ku-portal -- python3 /path/to/ku-portal-mcp/run.py
```

### settings.json 직접 편집

`~/.claude/settings.json`의 `mcpServers`에 추가:

```json
{
  "ku-portal": {
    "command": "python3",
    "args": ["/path/to/ku-portal-mcp/run.py"],
    "env": {
      "KU_PORTAL_ID": "학번",
      "KU_PORTAL_PW": "비밀번호"
    }
  }
}
```

## 환경변수

| 변수 | 설명 |
|------|------|
| `KU_PORTAL_ID` | KUPID 포털 아이디 (학번) |
| `KU_PORTAL_PW` | KUPID 포털 비밀번호 |

`.env` 파일 또는 환경변수로 설정할 수 있습니다.

## 사용 예시

Claude Code에서:

```
> 고려대 공지사항 보여줘
> 학사일정 조회해줘
> 첫 번째 공지사항 상세 내용 알려줘
> 장학공지 목록 보여줘
> "장학" 키워드로 검색해줘
```

## 동작 방식

1. KUPID 포털 (`portal.korea.ac.kr`)에 로그인하여 SSO 토큰 획득
2. GroupWare (`grw.korea.ac.kr`)에 접근하여 GRW 세션 획득
3. 공지사항/학사일정/장학공지 HTML을 EUC-KR 디코딩 후 파싱
4. 세션은 `~/.cache/ku-portal-mcp/session.json`에 30분간 캐시
5. 세션 만료 시 자동 재로그인 (retry 로직 내장)

## 참고

- 인증 플로우는 [kukit](https://github.com/DevKor-github/kukit) 라이브러리를 참고했습니다.
- Python 3.10 이상이 필요합니다.

## License

MIT
