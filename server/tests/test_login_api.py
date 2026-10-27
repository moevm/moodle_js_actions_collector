import asyncio
from pathlib import Path
import runpy
import socket
from threading import Event, Lock
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import uvicorn

from src.core.login_limits import LoginLimits
from tests.test_security_api import ADMIN, PAGE, bearer, secured_api


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["admin@example.com", "missing@example.com"])
async def test_five_bad_passwords_block_even_a_correct_password_until_window_expires(secured_api, monkeypatch, email):
    state = secured_api
    now = [0.0]
    state.limiter.clock = lambda: now[0]
    # Exercise the real service/hash implementation for both existing and missing users.
    for _ in range(5):
        response = await state.client.post("/api/auth/sign-in", json={"email": email, "password": "wrong"})
        assert response.status_code == 401, response.text
    response = await state.client.post("/api/auth/sign-in", json={"email": email, "password": "admin-password"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.headers["cache-control"] == "no-store"
    now[0] += 60
    response = await state.client.post("/api/auth/sign-in", json={"email": email, "password": "admin-password"})
    assert response.status_code == (200 if email == "admin@example.com" else 401), response.text


@pytest.mark.asyncio
async def test_forwarding_headers_cannot_reset_the_source_budget(secured_api, monkeypatch):
    state = secured_api
    state.limiter.limits = LoginLimits(source_attempts=2)
    verifier = AsyncMock(return_value=None)
    monkeypatch.setattr(state.auth, "sign_in", verifier)
    for index in range(3):
        response = await state.client.post("/api/auth/sign-in", json={
            "email": f"rotated-{index}@example.com", "password": "wrong",
        }, headers={"X-Forwarded-For": f"203.0.113.{index}", "X-Real-IP": f"192.0.2.{index}",
                    "Forwarded": f"for=198.51.100.{index}"})
        assert response.status_code == (401 if index < 2 else 429), response.text
    assert verifier.await_count == 2


@pytest.mark.asyncio
async def test_actual_uvicorn_startup_does_not_trust_spoofed_forwarding_headers(secured_api, monkeypatch):
    import main

    state = secured_api
    state.limiter.limits = LoginLimits(source_attempts=2)
    monkeypatch.setattr(state.auth, "sign_in", AsyncMock(return_value=None))
    startup = Mock()
    monkeypatch.setattr(uvicorn, "run", startup)
    runpy.run_path(str(Path(main.__file__).resolve()), run_name="__main__")
    startup.assert_called_once()
    options = startup.call_args.kwargs
    server = uvicorn.Server(uvicorn.Config(main.app, lifespan="off", log_config=None,
        access_log=False, proxy_headers=options.get("proxy_headers", True), forwarded_allow_ips="127.0.0.1"))
    monkeypatch.setattr(server, "install_signal_handlers", lambda: None)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.bind(("127.0.0.1", 0))
    connection.listen()
    connection.setblocking(False)
    port = connection.getsockname()[1]
    task = asyncio.create_task(server.serve(sockets=[connection]))
    try:
        async with asyncio.timeout(3):
            while not server.started:
                if task.done():
                    await task
                    pytest.fail("HTTP server did not start")
                await asyncio.sleep(0.005)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            for index in range(3):
                response = await client.post("/api/auth/sign-in", json={
                    "email": f"peer-probe-{index}@example.com", "password": "wrong",
                }, headers={"X-Forwarded-For": f"203.0.113.{index}"})
                assert response.status_code == (401 if index < 2 else 429), response.text
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 3)
        connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["admin@example.com", "missing@example.com"])
async def test_known_and_missing_accounts_both_execute_one_real_password_kdf(secured_api, monkeypatch, email):
    from src.core import passwords

    state = secured_api
    state.users.records[ADMIN]["password"] = passwords.hash_password("admin-password")
    original = passwords.hashlib.pbkdf2_hmac
    iterations = []

    def calculate(*args, **kwargs):
        iterations.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(passwords.hashlib, "pbkdf2_hmac", calculate)
    response = await state.client.post("/api/auth/sign-in", json={"email": email, "password": "wrong"})
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Invalid credentials"}
    assert iterations == [600000]


@pytest.mark.asyncio
async def test_repeated_successful_logins_do_not_trigger_account_failure_lockout(secured_api, monkeypatch):
    state = secured_api
    monkeypatch.setattr(state.auth, "sign_in", AsyncMock(return_value=state.users.records[ADMIN]))
    for _ in range(8):
        response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
        assert response.status_code == 200, response.text
    assert not state.limiter._accounts


@pytest.mark.asyncio
async def test_database_errors_do_not_consume_the_account_failure_budget(secured_api, monkeypatch):
    state = secured_api
    state.limiter.limits = LoginLimits(account_failures=1)
    monkeypatch.setattr(state.auth, "sign_in", AsyncMock(side_effect=RuntimeError("private database detail")))
    response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
    assert response.status_code == 503
    assert "private database detail" not in response.text
    assert state.limiter.active_checks == 0
    monkeypatch.setattr(state.auth, "sign_in", AsyncMock(return_value=state.users.records[ADMIN]))
    response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_two_busy_password_threads_reject_more_logins_but_keep_ingestion_available(secured_api, monkeypatch):
    from src.core.modules.service import authorization

    state = secured_api
    release, lock = Event(), Lock()
    started = [0]
    original = authorization.verify_login_password

    def expensive_check(password, stored):
        with lock:
            started[0] += 1
            index = started[0]
        if index <= 2:
            assert release.wait(5)
            return False
        return original(password, stored)

    monkeypatch.setattr(authorization, "verify_login_password", expensive_check)
    credentials = {"email": "admin@example.com", "password": "wrong"}
    tasks = [asyncio.create_task(state.client.post("/api/auth/sign-in", json=credentials)) for _ in range(2)]
    try:
        async with asyncio.timeout(2):
            while started[0] < 2:
                await asyncio.sleep(0.005)
        response = await asyncio.wait_for(state.client.post("/api/auth/sign-in", json=credentials), 1)
        assert response.status_code == 429
        assert started[0] == 2
        assert (await asyncio.wait_for(state.client.get("/api/healthcheck/"), 1)).status_code == 200
        response = await asyncio.wait_for(state.client.post("/api/statistics/page", json=PAGE,
            headers=bearer(state.tokens.settings.ingestion_key)), 1)
        assert response.status_code == 201, response.text
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(not isinstance(result, BaseException) and result.status_code == 401 for result in results)
    assert state.limiter.active_checks == 0
    response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
    assert response.status_code == 200, response.text
