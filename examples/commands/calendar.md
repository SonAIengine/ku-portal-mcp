---
description: 캘린더 일정 조회/생성/관리
argument-hint: [오늘|이번주|생성|날짜] [상세 내용]
allowed-tools: mcp__ms365__list-calendars, mcp__ms365__list-calendar-events, mcp__ms365__get-calendar-event, mcp__ms365__get-calendar-view, mcp__ms365__create-calendar-event, mcp__ms365__update-calendar-event, mcp__ms365__delete-calendar-event
---

# 캘린더 관리

사용자 요청: $ARGUMENTS

## 동작 모드

### "오늘" 또는 인자 없음
- 오늘 일정을 시간순으로 보여줘
- 빈 시간대도 함께 표시

### "이번주"
- 이번 주 월~금 일정 요약

### "생성" + 내용
- 사용자가 지정한 내용으로 일정 생성
- 제목, 시간, 참석자를 확인한 후 생성 여부를 물어봐

### 날짜 지정 (예: "3/5", "다음주 수요일")
- 해당 날짜의 일정 조회

## 규칙
- 시간은 KST 기준으로 표시
- 일정 생성/수정/삭제 전에 반드시 사용자 확인
- 회의 충돌이 있으면 경고
