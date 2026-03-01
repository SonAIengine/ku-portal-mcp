---
description: Teams 메시지 조회/발송
argument-hint: [조회|발송|채널명] [내용]
allowed-tools: mcp__ms365__list-joined-teams, mcp__ms365__get-team, mcp__ms365__list-team-channels, mcp__ms365__get-team-channel, mcp__ms365__list-channel-messages, mcp__ms365__get-channel-message, mcp__ms365__send-channel-message, mcp__ms365__list-chats, mcp__ms365__get-chat, mcp__ms365__list-chat-messages, mcp__ms365__send-chat-message, mcp__ms365__list-team-members
---

# Teams 메시지 관리

사용자 요청: $ARGUMENTS

## 동작 모드

### "조회" 또는 인자 없음
- 참여 중인 팀 목록 표시
- 최근 채팅/채널 메시지 요약

### 채널명 지정
- 해당 채널의 최근 메시지를 요약

### "발송" + 내용
- 지정된 채널/채팅에 메시지 발송
- 발송 전 반드시 사용자 확인

## 규칙
- 메시지 발송 전에는 반드시 사용자 확인을 받아
- 긴 대화는 핵심만 요약
- 한글로 응답
