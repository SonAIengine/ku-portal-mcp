# Claude Code Custom Commands 예시

[Claude Code](https://claude.com/claude-code)의 커스텀 슬래시 커맨드(`.claude/commands/*.md`) 예시 모음입니다.

## 사용법

1. 원하는 커맨드 파일을 `~/.claude/commands/` (글로벌) 또는 프로젝트의 `.claude/commands/` (프로젝트별)에 복사
2. Claude Code에서 `/커맨드명`으로 실행

```bash
# 글로벌 커맨드로 설치
cp examples/commands/ku.md ~/.claude/commands/

# 프로젝트 커맨드로 설치
cp examples/commands/ku.md .claude/commands/
```

## 커맨드 목록

| 파일 | 설명 | 필요한 MCP 서버 |
|------|------|----------------|
| [ku.md](ku.md) | KUPID 포털 통합 조회 (도서관/공지/LMS/시간표/장학) | `ku-portal` |
| [calendar.md](calendar.md) | 캘린더 일정 조회/생성/관리 | `ms365` |
| [mail.md](mail.md) | Outlook 메일 조회/발송/관리 | `ms365` |
| [morning.md](morning.md) | 아침 브리핑 (메일 + 일정 + Teams) | `ms365` |
| [teams.md](teams.md) | Teams 메시지 조회/발송 | `ms365` |
| [tasks.md](tasks.md) | To Do / Planner 작업 관리 | `ms365` |
| [search365.md](search365.md) | Microsoft 365 통합 검색 | `ms365` |

## 커맨드 구조 설명

각 `.md` 파일은 YAML frontmatter + Markdown 본문으로 구성됩니다:

```yaml
---
description: 커맨드 설명 (슬래시 메뉴에 표시됨)
argument-hint: [인자1|인자2] [상세]     # 선택사항
allowed-tools: mcp__서버__도구1, ...    # 이 커맨드에서 사용할 MCP 도구
---
```

### 핵심 패턴

- **`$ARGUMENTS`**: 사용자가 `/커맨드명 뒤에 입력한 텍스트`가 치환됨
- **`allowed-tools`**: 명시된 도구만 허용하여 불필요한 도구 검색 방지
- **동작 모드 분기**: 인자 키워드에 따라 다른 동작 수행
- **출력 형식 지정**: 테이블, 요약 등 원하는 형식을 명시

## 커스터마이징

자신의 환경에 맞게 수정하여 사용하세요:

- MCP 서버 이름이 다르면 `allowed-tools`의 접두사를 변경 (예: `mcp__ku-portal__` → `mcp__my-server__`)
- 동작 모드나 출력 형식을 자유롭게 추가/수정
- 한국어/영어 등 원하는 언어로 변경
