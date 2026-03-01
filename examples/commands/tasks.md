---
description: To Do / Planner 작업 관리
argument-hint: [목록|추가|완료] [내용]
allowed-tools: mcp__ms365__list-todo-task-lists, mcp__ms365__list-todo-tasks, mcp__ms365__get-todo-task, mcp__ms365__create-todo-task, mcp__ms365__update-todo-task, mcp__ms365__delete-todo-task, mcp__ms365__list-planner-tasks, mcp__ms365__get-planner-plan, mcp__ms365__list-plan-tasks, mcp__ms365__get-planner-task, mcp__ms365__create-planner-task
---

# 작업 관리 (To Do + Planner)

사용자 요청: $ARGUMENTS

## 동작 모드

### "목록" 또는 인자 없음
- To Do 할 일 목록 표시
- Planner 내 할당된 태스크 표시
- 완료/미완료 구분

### "추가" + 내용
- To Do에 새 할 일 추가
- 또는 Planner에 태스크 생성 (플랜 지정 필요)

### "완료" + 태스크명
- 해당 태스크를 완료 처리

## 규칙
- 삭제 전에는 반드시 사용자 확인
- 한글로 응답
