#!/usr/bin/env python3
"""Disposable Moodle 5.0.2 for manual plugin installation (Linux/WSL, stdlib only)."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
MARKER = "io.moodle-actions.manual-rehearsal"
TMP = Path("/tmp")


class RehearsalError(Exception):
    pass


class Runner:
    def __init__(self) -> None:
        self.secrets: set[str] = set()

    def redact(self, text: str) -> str:
        for value in sorted(self.secrets, key=len, reverse=True):
            if value:
                text = text.replace(value, "[hidden]")
        return text

    def run(self, args: Sequence[str], *, timeout: int = 60) -> str:
        child_env = os.environ.copy()
        if list(args[:2]) == ["docker", "compose"]:
            # Backend-only snapshots deliberately omit the other main services.
            # An inherited COMPOSE_REMOVE_ORPHANS=true must never remove them.
            child_env["COMPOSE_REMOVE_ORPHANS"] = "false"
        try:
            result = subprocess.run(args, cwd=ROOT, env=child_env, text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RehearsalError(f"Не удалось выполнить {args[0]}: {type(error).__name__}") from error
        if result.returncode:
            detail = self.redact((result.stderr or result.stdout)[-4000:]).strip()
            raise RehearsalError(f"Команда {args[0]} завершилась с кодом {result.returncode}.\n{detail}")
        return result.stdout.strip()

    def inspect(self, reference: str) -> dict[str, Any]:
        return json.loads(self.run(["docker", "inspect", reference]))[0]

    def service(self, project: str, service: str) -> dict[str, Any] | None:
        ids = self.run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}",
                        "--filter", f"label=com.docker.compose.service={service}"]).split()
        if len(ids) > 1:
            raise RehearsalError(f"Для {service} найдено несколько контейнеров; репетиция рассчитана на один экземпляр.")
        return self.inspect(ids[0]) if ids else None


def environment(container: dict[str, Any]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in container["Config"].get("Env", []) if "=" in item)


def remember_secrets(runner: Runner, values: dict[str, Any]) -> None:
    runner.secrets.update(str(value) for key, value in values.items()
                          if value and any(word in key.upper() for word in ("PASSWORD", "SECRET", "KEY", "TOKEN")))


def literal_compose(value: Any) -> Any:
    # Compose interpolates dollars even inside JSON strings. Preserve literals.
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, dict):
        return {key: literal_compose(item) for key, item in value.items()}
    if isinstance(value, list):
        return [literal_compose(item) for item in value]
    return value


def write_json(path: Path, data: Any, *, compose: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(literal_compose(data) if compose else data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def control_directory(root: Path = ROOT) -> Path:
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    folder = TMP / f"collector-manual-{os.getuid()}-{digest}"
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RehearsalError(f"Небезопасные права каталога состояния: {folder}")
    return folder


class Lock:
    def __init__(self, folder: Path) -> None:
        self.path = folder / "lock"

    def __enter__(self) -> None:
        self.stream = self.path.open("a")
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.stream.close()
            raise RehearsalError("Другая команда репетиции ещё выполняется.") from error

    def __exit__(self, *args: Any) -> None:
        self.stream.close()


def read_state(folder: Path) -> dict[str, Any] | None:
    path = folder / "state.json"
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    token = state.get("token", "")
    work = Path(state.get("work", "")).resolve()
    if (len(token) != 32 or any(c not in "0123456789abcdef" for c in token)
            or work.parent != TMP.resolve() or not work.name.startswith(f"moodle-rehearsal-{token[:8]}-")):
        raise RehearsalError("Некорректное состояние репетиции; автоматическое удаление отменено.")
    if state.get("project") != f"moodle-rehearsal-{token[:12]}":
        raise RehearsalError("Некорректное имя временного Compose-проекта.")
    return state


def compose(state: dict[str, Any], name: str, *args: str) -> list[str]:
    project = state["project"] if name == "moodle" else state["collector_project"]
    return ["docker", "compose", "-p", project, "-f", str(Path(state["work"]) / f"{name}.json"), *args]


def published_url(container: dict[str, Any], port: int) -> str:
    bindings = container["NetworkSettings"]["Ports"].get(f"{port}/tcp") or []
    if not bindings:
        raise RehearsalError(f"Порт {port} не опубликован на хосте.")
    return f"http://localhost:{int(bindings[0]['HostPort'])}"


def free_port(requested: int) -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", requested))
        return reservation.getsockname()[1]


def backend_document(config: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
    service = copy.deepcopy(config["services"]["backend"])
    if any(service.get(key) for key in ("network_mode", "volumes_from", "configs", "secrets")):
        raise RehearsalError("Нестандартные network_mode/configs/secrets backend требуют отдельной настройки репетиции.")
    for key in ("build", "depends_on", "profiles", "develop"):
        service.pop(key, None)
    service.update(image=backend["Image"], pull_policy="never", environment=environment(backend))
    service["labels"] = {key: value for key, value in backend["Config"].get("Labels", {}).items()
                         if not key.startswith("com.docker.compose.")}
    host = backend["HostConfig"]
    expected_ports = {(str(item.get("host_ip") or "0.0.0.0"), str(item["published"]),
                       f"{item['target']}/{item.get('protocol', 'tcp')}") for item in service.get("ports", [])}
    current_ports = {(str(binding.get("HostIp") or "0.0.0.0"), str(binding["HostPort"]), target)
                     for target, bindings in (host.get("PortBindings") or {}).items() for binding in bindings or []}
    if expected_ports != current_ports:
        raise RehearsalError("Порты в Compose отличаются от работающего backend. Сначала согласуйте основную конфигурацию.")
    if host.get("NanoCpus"):
        service["cpus"] = host["NanoCpus"] / 1_000_000_000
    if host.get("Memory"):
        service["mem_limit"] = host["Memory"]
    networks = {}
    for key in service.get("networks", {"default": None}):
        network_name = config["networks"][key]["name"]
        if network_name not in backend["NetworkSettings"]["Networks"]:
            raise RehearsalError("Сети текущего backend отличаются от docker compose config.")
        networks[key] = {"external": True, "name": network_name}
    document: dict[str, Any] = {"services": {"backend": service}, "networks": networks}
    volumes = {}
    for mount in service.get("volumes", []):
        if mount["type"] == "volume":
            source = mount["source"]
            volumes[source] = {"external": True, "name": config["volumes"][source]["name"]}
    if volumes:
        document["volumes"] = volumes
    return document


def temporary_document(state: dict[str, Any], moodle_image: str, database_image: str) -> dict[str, Any]:
    password = "Db1!" + secrets.token_urlsafe(24)
    return {"services": {
        "mariadb": {"image": database_image, "pull_policy": "never", "restart": "no",
            "cpus": 1.0, "mem_limit": "1g", "tmpfs": ["/var/lib/mysql:rw,nosuid,size=536870912"],
            "labels": {MARKER: state["token"]},
            "environment": {"MARIADB_ROOT_PASSWORD": secrets.token_urlsafe(32), "MARIADB_DATABASE": "moodle",
                            "MARIADB_USER": "moodle", "MARIADB_PASSWORD": password},
            "command": ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"],
            "healthcheck": {"test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
                            "interval": "5s", "timeout": "5s", "retries": 60}},
        "moodle": {"image": moodle_image, "pull_policy": "never", "restart": "no", "init": True,
            "cpus": 1.0, "mem_limit": "1536m", "tmpfs": ["/var/www/moodledata:rw,nosuid,size=536870912"],
            "labels": {MARKER: state["token"]},
            "entrypoint": ["bash", "/opt/manual-moodle-entrypoint.sh"], "command": [],
            "environment": {"MOODLE_URL": state["moodle_url"], "MOODLE_DB_PASSWORD": password,
                            "MOODLE_ADMIN_PASSWORD": state["admin_password"], "REHEARSAL_ID": state["token"][:12]},
            "ports": [f"127.0.0.1:{state['port']}:80"],
            "volumes": [
                {"type": "bind", "source": str(ROOT / "deploy/rehearsal/config.php"), "target": "/var/www/html/config.php", "read_only": True},
                {"type": "bind", "source": str(ROOT / "deploy/rehearsal/entrypoint.sh"), "target": "/opt/manual-moodle-entrypoint.sh", "read_only": True}],
            "depends_on": {"mariadb": {"condition": "service_healthy"}},
            "healthcheck": {"test": ["CMD", "curl", "-fsS", "http://localhost/health.php"],
                            "interval": "5s", "timeout": "5s", "retries": 150, "start_period": "120s"}}}}


def probe(state: dict[str, Any]) -> None:
    request = Request(state["collector_url"] + "/api/statistics/page", method="OPTIONS", headers={
        "Origin": state["moodle_url"], "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type"})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=10) as response:
            if response.status != 200 or response.headers.get("Access-Control-Allow-Origin") not in ("*", state["moodle_url"]):
                raise RehearsalError("Коллектор не разрешил CORS для временного Moodle.")
    except (URLError, OSError) as error:
        raise RehearsalError("Проверка CORS не прошла; проверьте доступность frontend/backend.") from error


def reload_frontend(runner: Runner, project: str) -> None:
    frontend = runner.service(project, "frontend")
    if not frontend or not frontend["State"]["Running"]:
        raise RehearsalError("Frontend коллектора не запущен; после восстановления выполните nginx -s reload.")
    runner.run(["docker", "exec", frontend["Id"], "nginx", "-s", "reload"])


def cleanup(runner: Runner, folder: Path, *, token: str | None = None) -> None:
    state = read_state(folder)
    if state is None or (token is not None and state["token"] != token):
        return
    failures = []
    if state["cors_attempted"]:
        try:
            if not state.get("cors_restored"):
                backend = runner.service(state["collector_project"], "backend")
                if backend and backend["Config"].get("Labels", {}).get(MARKER) == state["token"]:
                    print("Восстанавливаю CORS коллектора...", flush=True)
                    runner.run(compose(state, "collector-original", "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                                       "--wait", "--wait-timeout", "120", "backend"), timeout=150)
                elif backend and backend["State"]["Running"]:
                    print("Backend имеет другую конфигурацию; сохраняю её.")
                    state["backend_changed_elsewhere"] = True
                else:
                    raise RehearsalError("Backend не найден. Снимок конфигурации сохранён для повторного stop.")
                state["cors_restored"] = True
                write_json(folder / "state.json", state)
            if not state.get("backend_changed_elsewhere"):
                reload_frontend(runner, state["collector_project"])
        except RehearsalError as error:
            failures.append(str(error))
    try:
        runner.run(compose(state, "moodle", "down", "--volumes", "--remove-orphans", "--timeout", "20"), timeout=90)
    except RehearsalError as error:
        failures.append(str(error))
    if failures:
        raise RehearsalError("\n".join(failures) + "\nФайлы восстановления сохранены. Повторите: python3 scripts/manual-moodle.py stop")
    shutil.rmtree(state["work"])
    (folder / "state.json").unlink()
    print("Временный Moodle удалён. Собранные события остаются в коллекторе.")


def start(runner: Runner, folder: Path, args: argparse.Namespace, token: str) -> dict[str, Any]:
    if read_state(folder):
        raise RehearsalError("Репетиция уже существует. Используйте status или stop перед новым start.")
    base = ["docker", "compose"]
    for filename in args.compose_file:
        base += ["-f", str(Path(filename).resolve())]
    config = json.loads(runner.run([*base, "config", "--format", "json"]))
    project = config["name"]
    backend, frontend = runner.service(project, "backend"), runner.service(project, "frontend")
    if not backend or not frontend or not all(item["State"]["Running"] for item in (backend, frontend)):
        raise RehearsalError("Сначала запустите коллектор: docker compose up -d --no-build --pull never --wait backend frontend")
    if backend["Config"].get("Labels", {}).get(MARKER):
        raise RehearsalError("Backend уже занят другой репетицией; сначала завершите её.")
    values = environment(backend)
    if not values.get("COLLECTOR_INGEST_KEY"):
        raise RehearsalError("У работающего backend отсутствует COLLECTOR_INGEST_KEY.")
    remember_secrets(runner, values)
    images = []
    for service, explicit, fallback in [("moodle", args.moodle_image, f"{project}-moodle:latest"),
                                         ("mariadb", args.mariadb_image, "mariadb:10.11.11")]:
        existing = runner.service(project, service)
        image = explicit or (existing["Image"] if existing else fallback)
        try:
            images.append(json.loads(runner.run(["docker", "image", "inspect", image]))[0]["Id"])
        except RehearsalError as error:
            raise RehearsalError(f"Локальный образ {image} не найден; укажите --{service}-image. Скачивание не выполнялось.") from error
    port = free_port(args.port)
    original = backend_document(config, backend)
    work = Path(tempfile.mkdtemp(prefix=f"moodle-rehearsal-{token[:8]}-", dir=TMP))
    state = {"token": token, "work": str(work), "project": f"moodle-rehearsal-{token[:12]}",
             "collector_project": project, "collector_url": published_url(frontend, 8080),
             "moodle_url": f"http://localhost:{port}", "port": port,
             "admin_password": "Tmp1!" + secrets.token_urlsafe(20), "cors_attempted": False}
    remember_secrets(runner, state)
    candidate = copy.deepcopy(original)
    origins = [item.strip() for item in values.get("CORS_ORIGINS", "http://localhost:18082").split(",") if item.strip()]
    candidate["services"]["backend"]["environment"]["CORS_ORIGINS"] = ",".join(dict.fromkeys([*origins, state["moodle_url"]]))
    candidate["services"]["backend"]["labels"][MARKER] = token
    temporary = temporary_document(state, *images)
    for service in temporary["services"].values():
        remember_secrets(runner, service.get("environment", {}))
    write_json(work / "collector-original.json", original, compose=True)
    write_json(work / "collector-cors.json", candidate, compose=True)
    write_json(work / "moodle.json", temporary, compose=True)
    write_json(folder / "state.json", state)
    runner.run([sys.executable, str(ROOT / "scripts/build-moodle-plugin.py"), "--output", str(work / "local_actioncollector.zip")])
    print(f"Состояние репетиции: {work}\nУстановка чистого Moodle 5.0.2; до 15 минут...", flush=True)
    runner.run(compose(state, "moodle", "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "900"), timeout=960)
    current = runner.service(project, "backend")
    if not current or current["Id"] != backend["Id"]:
        raise RehearsalError("Backend изменился во время установки Moodle; CORS не меняю.")
    state["cors_attempted"] = True
    write_json(folder / "state.json", state)
    print("Добавляю временный origin в CORS; backend кратко перезапустится...", flush=True)
    runner.run(compose(state, "collector-cors", "up", "-d", "--no-deps", "--no-build", "--pull", "never",
                       "--wait", "--wait-timeout", "120", "backend"), timeout=150)
    reload_frontend(runner, project)
    probe(state)
    return state


def show(state: dict[str, Any]) -> None:
    archive = Path(state["work"]) / "local_actioncollector.zip"
    print(f"\nMoodle: {state['moodle_url']}\nЛогин: admin\nПароль: {state['admin_password']}")
    print(f"ZIP плагина: {archive}")
    if shutil.which("wslpath"):
        result = subprocess.run(["wslpath", "-w", str(archive)], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            print(f"Путь для Windows: {result.stdout.strip()}")
    print(f"Установка ZIP: {state['moodle_url']}/admin/tool/installaddon/index.php")
    print(f"Настройки плагина: {state['moodle_url']}/admin/settings.php?section=local_actioncollector")
    print(f"Коллектор: {state['collector_url']}\nCollector API URL: {state['collector_url']}/api")
    print("Collection key: во втором терминале выполните python3 scripts/manual-moodle.py settings")
    print("Плагин ещё не установлен. Установите ZIP через UI, включите collection и задайте URL/ключ.")


def use_saved_secrets(runner: Runner, state: dict[str, Any]) -> None:
    remember_secrets(runner, state)
    for name in ("moodle", "collector-original"):
        document = json.loads((Path(state["work"]) / f"{name}.json").read_text())
        for service in document["services"].values():
            remember_secrets(runner, service.get("environment", {}))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "settings", "logs", "cron"), nargs="?", default="start")
    parser.add_argument("--port", type=int, default=0, help="Free localhost port; default: choose automatically")
    parser.add_argument("--moodle-image", help="Existing project Moodle 5.0.2 image")
    parser.add_argument("--mariadb-image", help="Existing MariaDB 10.11 image")
    parser.add_argument("--compose-file", action="append", default=[], help="Main stack Compose file; repeat for overrides")
    args = parser.parse_args(argv)
    if args.port != 0 and not 1024 <= args.port <= 65535:
        parser.error("--port must be 0 or between 1024 and 65535")
    runner, owned_token, result = Runner(), None, 0
    try:
        if not shutil.which("docker"):
            raise RehearsalError("Docker CLI не найден. Запускайте скрипт внутри WSL/Linux с доступом к Docker.")
        folder = control_directory()
        if args.action == "start":
            owned_token = uuid4().hex
            with Lock(folder):
                state = start(runner, folder, args, owned_token)
            show(state)
            input("\nОставьте терминал открытым. Enter или Ctrl+C завершит и удалит временный Moodle.\n")
        else:
            with Lock(folder):
                state = read_state(folder)
                if not state:
                    print("Активной репетиции нет.")
                elif args.action == "stop":
                    use_saved_secrets(runner, state)
                    cleanup(runner, folder)
                elif args.action == "status":
                    print(f"Moodle: {state['moodle_url']}\nКоллектор: {state['collector_url']}\nФайлы: {state['work']}")
                    print(runner.run(compose(state, "moodle", "ps", "-a")))
                    probe(state)
                    print("CORS: OK")
                elif args.action == "settings":
                    backend = runner.service(state["collector_project"], "backend")
                    if not backend:
                        raise RehearsalError("Backend не найден.")
                    print(f"Collector API URL: {state['collector_url']}/api")
                    print(f"Collection key: {environment(backend).get('COLLECTOR_INGEST_KEY', '')}")
                elif args.action == "logs":
                    use_saved_secrets(runner, state)
                    print(runner.run(compose(state, "moodle", "logs", "--no-color", "--tail", "120")))
                elif args.action == "cron":
                    use_saved_secrets(runner, state)
                    print(runner.run(compose(state, "moodle", "exec", "-T", "--user", "www-data", "moodle",
                                             "php", "admin/cli/cron.php"), timeout=300))
    except (KeyboardInterrupt, EOFError):
        pass
    except (RehearsalError, OSError, ValueError, KeyError) as error:
        print(runner.redact(f"Ошибка: {error}"), file=sys.stderr)
        result = 1
        if owned_token is not None:
            try:
                state = read_state(folder)
                if state and state["token"] == owned_token:
                    print(runner.run(compose(state, "moodle", "logs", "--no-color", "--tail", "80")), file=sys.stderr)
            except (RehearsalError, OSError, ValueError, KeyError):
                pass
    finally:
        if owned_token is not None:
            try:
                with Lock(folder):
                    cleanup(runner, folder, token=owned_token)
            except (RehearsalError, OSError, ValueError, KeyError) as error:
                print(runner.redact(f"Очистка не завершена: {error}"), file=sys.stderr)
                result = 1
    return result


def interrupted(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    for name in ("SIGTERM", "SIGHUP"):
        signal.signal(getattr(signal, name), interrupted)
    raise SystemExit(main())
