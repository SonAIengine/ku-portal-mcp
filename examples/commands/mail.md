---
description: 메일 조회/발송/관리
argument-hint: <조회|발송|검색> [상세 내용]
allowed-tools: mcp__ms365__list-mail-messages, mcp__ms365__list-mail-folders, mcp__ms365__list-mail-folder-messages, mcp__ms365__get-mail-message, mcp__ms365__send-mail, mcp__ms365__create-draft-email, mcp__ms365__move-mail-message, mcp__ms365__delete-mail-message, mcp__ms365__search-query
---

# Outlook 메일 관리

사용자 요청: $ARGUMENTS

## MCP 도구 로드
- allowed-tools에 명시된 도구는 `select:` 로 직접 로드 (키워드 검색 금지)
- 예: `select:mcp__ms365__list-mail-messages`
- 한번 로드한 도구는 재검색하지 않음

## 동작 모드

### "조회" 또는 인자 없음
- 최근 메일을 가져와서 발신자, 제목, 핵심 내용 요약
- 안 읽은 메일 우선 표시

### "발송" + 내용
- 사용자가 지정한 내용으로 메일 초안 작성
- 수신자, 제목, 본문을 확인한 후 발송 여부를 물어봐
- 확인 없이 바로 발송하지 마

### "검색" + 키워드
- search-query로 메일 검색
- 결과를 요약해서 보여줘

## 출력 형식

### 메일 목록은 테이블로 출력
```
| # | 발신자 | 제목 | 수신일 | 상태 |
|---|--------|------|--------|------|
```
- 상태: 회신필요 / 액션필요 / 참고 / 알림

### 회신/액션 필요 메일만 별도 요약
각 항목을 1~2줄로:
```
1. **제목** (발신자) — 핵심 내용 한줄. [필요한 액션]
```

### 알림/뉴스레터는 묶어서 한줄로
```
알림 5건: Confluence 다이제스트(2), 시프티, 급여, Intel 계정
```

## 규칙
- 메일 본문이 길면 핵심만 요약
- 발송 전에는 반드시 사용자 확인을 받아
- 한글로 응답
