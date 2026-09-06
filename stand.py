#!/usr/bin/env python3
"""Единая точка входа в стенд — работает одинаково на macOS, Linux и Windows.

Makefile есть только для удобства в Unix и просто зовёт этот скрипт.
Внешних зависимостей нет: docker compose вызывается через subprocess,
HTTP-запросы идут через urllib из стандартной библиотеки, поэтому
ни curl, ни make, ни bash не нужны.

    python stand.py up
    python stand.py break --error-rate 0.10
    python stand.py heal
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = ROOT / "deploy" / "docker-compose.yml"
DEFAULT_HOST = os.environ.get("STAND_HOST", "http://127.0.0.1:8000")


# --------------------------------------------------------------------------
# вспомогательное
# --------------------------------------------------------------------------

def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"ошибка: {message}", file=sys.stderr)
    raise SystemExit(1)


def compose_command() -> list[str]:
    """Найти docker compose.

    Сначала плагин (`docker compose`), потом старый отдельный бинарь
    (`docker-compose`) — он ещё встречается на Linux из репозиториев
    дистрибутива.
    """
    if shutil.which("docker"):
        probe = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    fail(
        "не найден docker compose. Поставьте Docker Desktop (macOS, Windows) "
        "или docker-ce с плагином docker-compose-plugin (Linux)."
    )


def compose(*args: str, check: bool = True) -> int:
    cmd = [*compose_command(), "-f", str(COMPOSE_FILE), *args]
    print("+", " ".join(cmd))
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{DEFAULT_HOST.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode()
    except urllib.error.URLError as exc:
        fail(f"сервис недоступен по адресу {url}: {exc}. Поднят ли стенд?")
    return json.loads(body) if body else {}


def python_executable() -> str:
    """Интерпретатор для дочерних процессов.

    sys.executable, а не 'python3': на Windows такой команды может не
    быть, а в виртуальном окружении важно попасть именно в него.
    """
    return sys.executable or "python"


# --------------------------------------------------------------------------
# команды
# --------------------------------------------------------------------------

def cmd_up(args) -> None:
    compose("up", "-d", "--build")
    print()
    print("сервис      ", f"{DEFAULT_HOST}/work")
    print("метрики     ", f"{DEFAULT_HOST}/metrics")
    print("Prometheus   http://127.0.0.1:9090")
    print("Grafana      http://127.0.0.1:3000  (admin / admin)")


def cmd_down(args) -> None:
    compose("down")


def cmd_logs(args) -> None:
    compose("logs", "-f", "--tail=100")


def cmd_test(args) -> None:
    if args.docker:
        compose("--profile", "tools", "run", "--rm", "tests")
        return
    result = subprocess.run(
        [python_executable(), "-m", "pytest", "tests", "-q"],
        cwd=ROOT / "service",
    )
    raise SystemExit(result.returncode)


def cmd_load(args) -> None:
    if args.docker:
        compose(
            "--profile", "tools", "run", "--rm", "loadgen",
            "--rps", str(args.rps),
            "--duration", str(args.duration),
            "--concurrency", str(args.concurrency),
        )
        return
    result = subprocess.run(
        [
            python_executable(),
            str(ROOT / "loadgen" / "loadgen.py"),
            "--url", f"{DEFAULT_HOST.rstrip('/')}/work",
            "--rps", str(args.rps),
            "--duration", str(args.duration),
            "--concurrency", str(args.concurrency),
        ]
    )
    raise SystemExit(result.returncode)


def cmd_break(args) -> None:
    state = request(
        "POST",
        "/fault",
        {"error_rate": args.error_rate, "extra_latency_ms": args.latency_ms},
    )
    print(json.dumps(state, ensure_ascii=False))


def cmd_heal(args) -> None:
    print(json.dumps(request("DELETE", "/fault"), ensure_ascii=False))


def cmd_status(args) -> None:
    print(json.dumps(request("GET", "/fault"), ensure_ascii=False))


def cmd_check_rules(args) -> None:
    """Проверить правила алертов.

    promtool ставится вместе с Prometheus. Если его нет в системе —
    запускаем во временном контейнере, чтобы команда работала везде
    одинаково и ничего не нужно было доустанавливать.
    """
    rules = ROOT / "deploy" / "prometheus" / "rules"
    tests = ROOT / "deploy" / "prometheus" / "tests"

    if shutil.which("promtool"):
        checks = [
            (["promtool", "check", "rules", "slo.yml"], rules),
            (["promtool", "test", "rules", "slo_test.yml"], tests),
        ]
        for cmd, cwd in checks:
            print("+", " ".join(cmd), f"({cwd.name})")
            if subprocess.run(cmd, cwd=cwd).returncode != 0:
                raise SystemExit(1)
        return

    print("promtool не найден, запускаю в контейнере")
    compose("--profile", "tools", "run", "--rm", "check-rules")


def cmd_doctor(args) -> None:
    """Проверить, что окружение готово. Полезно на новой машине."""
    print(f"платформа       {sys.platform}")
    print(f"python          {sys.version.split()[0]}")

    docker = shutil.which("docker")
    print(f"docker          {docker or 'НЕ НАЙДЕН'}")
    if docker:
        info = subprocess.run(["docker", "info"], capture_output=True, text=True)
        print(f"docker daemon   {'запущен' if info.returncode == 0 else 'НЕ ЗАПУЩЕН'}")
        arch = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Arch}}"],
            capture_output=True, text=True,
        )
        if arch.returncode == 0:
            print(f"архитектура     {arch.stdout.strip()}")

    print(f"promtool        {shutil.which('promtool') or 'нет (запустится в контейнере)'}")
    print(f"ansible         {shutil.which('ansible-playbook') or 'нет (нужен только для развёртывания)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stand",
        description="Управление стендом надёжности",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("up", help="поднять стенд").set_defaults(func=cmd_up)
    sub.add_parser("down", help="погасить стенд").set_defaults(func=cmd_down)
    sub.add_parser("logs", help="логи контейнеров").set_defaults(func=cmd_logs)
    tests = sub.add_parser("test", help="тесты сервиса")
    tests.add_argument(
        "--docker", action="store_true",
        help="прогнать в контейнере, без локального Python",
    )
    tests.set_defaults(func=cmd_test)
    sub.add_parser("status", help="что выкручено сейчас").set_defaults(func=cmd_status)
    sub.add_parser("heal", help="снять неисправность").set_defaults(func=cmd_heal)
    sub.add_parser("doctor", help="проверить окружение").set_defaults(func=cmd_doctor)
    sub.add_parser("check-rules", help="проверить правила алертов").set_defaults(
        func=cmd_check_rules
    )

    load = sub.add_parser("load", help="фоновая нагрузка")
    load.add_argument("--rps", type=float, default=20.0)
    load.add_argument("--duration", type=float, default=600.0)
    load.add_argument("--concurrency", type=int, default=10)
    load.add_argument(
        "--docker", action="store_true",
        help="запустить в контейнере, без локального Python",
    )
    load.set_defaults(func=cmd_load)

    broken = sub.add_parser("break", help="выкрутить неисправность")
    broken.add_argument("--error-rate", type=float, default=0.10)
    broken.add_argument("--latency-ms", type=int, default=0)
    broken.set_defaults(func=cmd_break)

    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    parsed.func(parsed)
