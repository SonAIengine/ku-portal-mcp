---
description: 아침 브리핑 (메일 + 일정 + Teams)
allowed-tools: mcp__ms365__list-mail-messages, mcp__ms365__list-calendar-events, mcp__ms365__get-calendar-view, mcp__ms365__list-chats, mcp__ms365__list-chat-messages, mcp__ms365__list-joined-teams, mcp__ms365__list-team-channels, mcp__ms365__list-channel-messages
---

# 아침 브리핑

하루를 시작하는 모닝 브리핑을 만들어줘.

## 순서

1. **안 읽은 메일 요약**
   - 최근 안 읽은 메일을 가져와서 발신자, 제목, 핵심 내용을 요약
   - 중요도/긴급도 순으로 정렬

2. **오늘 일정**
   - 오늘 날짜의 캘린더 이벤트를 조회
   - 시간순으로 정리하고, 회의 사이 빈 시간대도 알려줘

3. **Teams 최근 메시지**
   - 최근 채팅 메시지 중 중요한 것 요약
   - 멘션된 것 우선

## 출력 형식

```
## 모닝 브리핑 (날짜)

### 메일 (N건)
- [긴급] 발신자: 제목 — 요약
- 발신자: 제목 — 요약

### 오늘 일정 (N건)
- 09:00-10:00 회의명 (참석자)
- 14:00-15:00 회의명

### Teams 알림 (N건)
- 채널/채팅명: 누가 뭐라고 했는지 요약

### 오늘 할 일 제안
- 위 내용 기반으로 우선순위 제안
```
