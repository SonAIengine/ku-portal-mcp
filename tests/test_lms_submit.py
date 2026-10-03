import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx

import ku_portal_mcp.lms as lms
import ku_portal_mcp.server as server_module

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _assignment(**over):
    base = {
        "id": 7,
        "name": "Assignment #1",
        "submission_types": ["online_upload"],
        "due_at": "2026-10-04T14:59:59Z",
        "lock_at": "2026-10-05T14:59:59Z",
        "unlock_at": None,
        "locked_for_user": False,
        "allowed_extensions": [],
        "allowed_attempts": -1,
        "submission": {"workflow_state": "unsubmitted", "attempt": None},
    }
    base.update(over)
    return base


def _session():
    return lms.LMSSession(
        cookies={"_csrf_token": "tok%2Bvalue%3D", "_normandy_session": "secret"},
        user_id="u",
        user_name="n",
        canvas_user_id=1,
        created_at=time.time(),
    )


# ---- check_submission_plan ------------------------------------------------


def test_plan_ok_for_open_pdf_assignment():
    plan = lms.check_submission_plan(_assignment(), Path("/x/sol.pdf"), NOW)
    assert plan == {"ok": True, "problems": [], "warnings": []}


def test_plan_blocks_wrong_submission_type_and_extension():
    plan = lms.check_submission_plan(
        _assignment(submission_types=["online_text_entry"]), Path("/x/sol.exe"), NOW
    )
    assert not plan["ok"]
    assert len(plan["problems"]) == 2


def test_plan_respects_allowed_extensions():
    a = _assignment(allowed_extensions=["pdf"])
    assert lms.check_submission_plan(a, Path("/x/a.PDF"), NOW)["ok"]
    assert not lms.check_submission_plan(a, Path("/x/a.docx"), NOW)["ok"]


def test_plan_blocks_when_locked_or_not_yet_open():
    late = datetime(2026, 10, 6, tzinfo=timezone.utc)
    assert not lms.check_submission_plan(_assignment(), Path("/x/a.pdf"), late)["ok"]
    early = _assignment(unlock_at="2026-10-10T00:00:00Z")
    assert not lms.check_submission_plan(early, Path("/x/a.pdf"), NOW)["ok"]


def test_plan_warns_when_past_due_but_not_locked():
    after_due = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
    plan = lms.check_submission_plan(_assignment(), Path("/x/a.pdf"), after_due)
    assert plan["ok"]
    assert len(plan["warnings"]) == 1


def test_plan_warns_on_resubmission_and_blocks_exhausted_attempts():
    a = _assignment(submission={"workflow_state": "submitted", "attempt": 1})
    plan = lms.check_submission_plan(a, Path("/x/a.pdf"), NOW)
    assert plan["ok"] and plan["warnings"]
    a = _assignment(
        allowed_attempts=1, submission={"workflow_state": "submitted", "attempt": 1}
    )
    assert not lms.check_submission_plan(a, Path("/x/a.pdf"), NOW)["ok"]


# ---- submit_lms_assignment (HTTP mocked) --------------------------------


def _patch_http(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(lms.httpx, "AsyncClient", factory)


def _pdf(tmp_path):
    f = tmp_path / "solution.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    return f


def test_submit_flow_sends_csrf_and_keeps_session_cookie_off_upload_host(
    monkeypatch, tmp_path
):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/submissions/self/files"):
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://upload.example.com/up",
                    "upload_params": {"token": "abc"},
                },
            )
        if request.url.host == "upload.example.com":
            return httpx.Response(201, json={"id": 555})
        if request.url.path.endswith("/submissions"):
            return httpx.Response(
                201,
                json={
                    "workflow_state": "submitted",
                    "submitted_at": "2026-10-03T12:00:00Z",
                    "attempt": 1,
                    "late": False,
                    "attachments": [
                        {"id": 555, "display_name": "solution.pdf", "size": 13}
                    ],
                },
            )
        return httpx.Response(404)

    _patch_http(monkeypatch, handler)
    result = asyncio.run(lms.submit_lms_assignment(_session(), 100, 7, _pdf(tmp_path)))

    assert result["file_id"] == 555
    assert result["workflow_state"] == "submitted"
    assert result["attempt"] == 1

    slot_req, up_req, submit_req = seen
    # CSRF token is URL-decoded and sent on both Canvas writes
    assert slot_req.headers["x-csrf-token"] == "tok+value="
    assert submit_req.headers["x-csrf-token"] == "tok+value="
    # the third-party upload host must never see the Canvas session
    assert "cookie" not in up_req.headers
    assert "x-csrf-token" not in up_req.headers
    assert b"solution.pdf" in up_req.content
    # final call submits exactly that file id as online_upload
    form = parse_qs(submit_req.content.decode())
    assert form["submission[submission_type]"] == ["online_upload"]
    assert form["submission[file_ids][]"] == ["555"]


def test_submit_flow_follows_canvas_redirect_confirmation(monkeypatch, tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/submissions/self/files"):
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://upload.example.com/up",
                    "upload_params": {},
                },
            )
        if request.url.host == "upload.example.com":
            return httpx.Response(
                303,
                headers={
                    "location": "https://mylms.korea.ac.kr/api/v1/files/9/confirm"
                },
            )
        if request.url.path == "/api/v1/files/9/confirm":
            assert "cookie" in request.headers  # confirmation is a Canvas call
            return httpx.Response(200, json={"id": 9})
        if request.url.path.endswith("/submissions"):
            return httpx.Response(
                201, json={"workflow_state": "submitted", "attempt": 1}
            )
        return httpx.Response(404)

    _patch_http(monkeypatch, handler)
    result = asyncio.run(lms.submit_lms_assignment(_session(), 100, 7, _pdf(tmp_path)))
    assert result["file_id"] == 9
    assert ("GET", "/api/v1/files/9/confirm") in calls


# ---- server tool: dry-run by default --------------------------------------


def _wire_server(monkeypatch, assignment, submit_calls):
    async def fake_with_retry(fn, *a, **kw):
        return await fn(None, *a, **kw)

    async def fake_fetch(session, cid, aid):
        return assignment

    async def fake_submit(session, cid, aid, path):
        submit_calls.append((cid, aid, path))
        return {"file_id": 1, "workflow_state": "submitted"}

    monkeypatch.setattr(server_module, "_lms_with_retry", fake_with_retry)
    monkeypatch.setattr(server_module, "fetch_lms_assignment", fake_fetch)
    monkeypatch.setattr(server_module, "submit_lms_assignment", fake_submit)


def _call(**args):
    base = {"course_id": 100, "assignment_id": 7}
    base.update(args)
    # FastMCP returns (content_blocks, structured) for dict results
    result = asyncio.run(
        server_module.server.call_tool("kupid_lms_submit_assignment", base)
    )
    return result[1] if isinstance(result, tuple) else result


def test_tool_is_registered():
    tools = asyncio.run(server_module.server.list_tools())
    assert "kupid_lms_submit_assignment" in {t.name for t in tools}


def test_tool_dry_run_never_submits(monkeypatch, tmp_path):
    calls = []
    _wire_server(
        monkeypatch, _assignment(due_at="2099-01-01T00:00:00Z", lock_at=None), calls
    )
    out = _call(file_path=str(_pdf(tmp_path)))
    assert out["success"] is True
    assert out["submitted"] is False and out["dry_run"] is True
    assert calls == []


def test_tool_confirm_submits_once(monkeypatch, tmp_path):
    calls = []
    _wire_server(
        monkeypatch, _assignment(due_at="2099-01-01T00:00:00Z", lock_at=None), calls
    )
    out = _call(file_path=str(_pdf(tmp_path)), confirm=True)
    assert out["submitted"] is True
    assert len(calls) == 1


def test_tool_blocks_locked_assignment_even_with_confirm(monkeypatch, tmp_path):
    calls = []
    _wire_server(monkeypatch, _assignment(lock_at="2020-01-01T00:00:00Z"), calls)
    out = _call(file_path=str(_pdf(tmp_path)), confirm=True)
    assert out["success"] is False and out["submitted"] is False
    assert calls == []


def test_tool_rejects_hidden_dirs_relative_and_missing_paths(monkeypatch, tmp_path):
    calls = []
    _wire_server(monkeypatch, _assignment(), calls)
    hidden = tmp_path / ".ssh"
    hidden.mkdir()
    (hidden / "id.pdf").write_bytes(b"x")
    for bad in (
        str(hidden / "id.pdf"),
        "relative.pdf",
        str(tmp_path / "nope.pdf"),
        "/a/../b.pdf",
    ):
        out = _call(file_path=bad, confirm=True)
        assert out["success"] is False, bad
    assert calls == []
