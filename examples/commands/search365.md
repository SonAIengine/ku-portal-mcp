---
description: Microsoft 365 통합 검색
argument-hint: <검색어>
allowed-tools: mcp__ms365__search-query, mcp__ms365__list-mail-messages, mcp__ms365__get-mail-message, mcp__ms365__search-sharepoint-sites
---

# Microsoft 365 통합 검색

검색어: $ARGUMENTS

## 동작
1. search-query를 사용해 메일, 파일, SharePoint 등에서 통합 검색
2. 결과를 카테고리별로 정리:
   - 메일 결과
   - 파일/문서 결과
   - SharePoint 결과
3. 각 결과의 핵심 내용을 요약

## 규칙
- 결과가 많으면 상위 10개만 보여주고 "더 보기" 안내
- 관련도 순으로 정렬
- 한글로 응답
