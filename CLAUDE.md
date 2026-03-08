# ku-portal-mcp

고려대학교 KUPID 포털 + Canvas LMS 연동 MCP 서버 (PyPI 배포)

## 기술 스택
- Python 3.10+, FastMCP (mcp[cli])
- httpx + BeautifulSoup4 (스크래핑)
- hatchling (빌드), twine (배포)

## 주요 명령어
- 개발: `uv run python run.py`
- 빌드: `hatch build`
- 배포: `python3 -m twine upload dist/*`
- 린트: `ruff check . --fix && ruff format .`

## 프로젝트 구조
- `ku_portal_mcp/` — MCP 서버 코드 (tools 21개)
- `run.py` — 로컬 실행 진입점
- `pyproject.toml` — 패키지 메타데이터 (현재 v0.6.1)

## 배포 주의사항
- PyPI 토큰: `~/.pypirc`에 설정됨
- 버전 올릴 때 pyproject.toml의 version 수정
- dist/ 비우고 빌드 후 배포: `rm -rf dist && hatch build && twine upload dist/*`
- MCP 런타임 경로: `~/.claude/mcp-servers/ku-portal-mcp/` (git repo 아님)
