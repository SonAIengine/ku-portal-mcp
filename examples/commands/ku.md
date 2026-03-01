---
description: "고려대 포털(KUPID) 통합 조회 — 도서관/공지/LMS/시간표/장학"
argument-hint: "[도서관|공지|과제|성적|시간표|장학|검색] [상세 키워드]"
allowed-tools: mcp__ku-portal__kupid_login, mcp__ku-portal__kupid_get_library_seats, mcp__ku-portal__kupid_get_notices, mcp__ku-portal__kupid_get_notice_detail, mcp__ku-portal__kupid_get_schedules, mcp__ku-portal__kupid_get_schedule_detail, mcp__ku-portal__kupid_get_scholarships, mcp__ku-portal__kupid_get_scholarship_detail, mcp__ku-portal__kupid_get_syllabus, mcp__ku-portal__kupid_get_timetable, mcp__ku-portal__kupid_my_courses, mcp__ku-portal__kupid_lms_assignments, mcp__ku-portal__kupid_lms_courses, mcp__ku-portal__kupid_lms_dashboard, mcp__ku-portal__kupid_lms_grades, mcp__ku-portal__kupid_lms_modules, mcp__ku-portal__kupid_lms_quizzes, mcp__ku-portal__kupid_lms_submissions, mcp__ku-portal__kupid_lms_todo, mcp__ku-portal__kupid_search, mcp__ku-portal__kupid_search_courses
---

# 고려대 포털 (KUPID)

사용자 요청: $ARGUMENTS

## 공통 규칙
- 모든 호출 전에 kupid_login으로 먼저 로그인 (세션 내 1회)
- 결과는 한국어 테이블 형식으로 간결하게 정리
- 날짜/시간은 KST 기준

## 동작 모드

### "도서관" 또는 인자 없음
- kupid_get_library_seats로 도서관 좌석 현황 조회
- 층별 잔여석 테이블로 보여줘

### "공지" [키워드]
- kupid_get_notices로 최근 공지사항 목록 조회
- 키워드가 있으면 해당 키워드로 필터링
- 상세 보기 요청 시 kupid_get_notice_detail 사용

### "과제" 또는 "할일"
- kupid_lms_todo로 마감 임박한 할일 조회
- kupid_lms_assignments로 과목별 과제 목록 조회
- 마감일 기준 정렬, D-day 표시

### "성적"
- kupid_lms_grades로 성적 조회
- 과목별 성적 테이블로 정리

### "시간표"
- kupid_my_courses로 수강신청 내역 조회 (학수번호, 교수, 강의실, 시간 등 상세 정보)
- kupid_get_timetable은 위젯 기반이라 대학원 과목 누락 가능 → 보조용으로만 사용
- 요일별 테이블로 보기 좋게 정리

### "수업" 또는 "강의"
- kupid_my_courses로 수강신청 내역 조회 (학수번호, 교수, 강의실, 학점, 이수구분 포함)
- kupid_lms_courses + kupid_lms_dashboard로 LMS 대시보드 보조 조회

### "장학"
- kupid_get_scholarships로 장학금 목록 조회
- 상세 보기 요청 시 kupid_get_scholarship_detail 사용

### "일정" 또는 "학사일정"
- kupid_get_schedules로 학사 일정 조회

### "검색" + 키워드
- kupid_search로 포털 통합 검색
- kupid_search_courses로 개설 강좌 검색

### "퀴즈" 또는 "시험"
- kupid_lms_quizzes로 퀴즈/시험 목록 조회

### "강의자료" 또는 "모듈"
- kupid_lms_modules로 강의 자료/모듈 조회

### "제출" 또는 "제출현황"
- kupid_lms_submissions로 과제 제출 현황 조회

### 기타
- 위 키워드에 해당하지 않으면 kupid_search로 통합 검색 시도
