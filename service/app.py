"""Подопытный сервис стенда надёжности.

Одна полезная ручка /work, метрики для Prometheus и управляемая
неисправность: долю ошибок и добавочную задержку можно менять на лету
через POST /fault. Это позволяет вызвать аварию по команде и проверить,
что алерты и ранбуки действительно работают.
"""

import asyncio
import os
import random
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

# Базовая задержка обработки — имитация полезной работы.
BASE_LATENCY_MIN = float(os.getenv("BASE_LATENCY_MIN", "0.010"))
BASE_LATENCY_MAX = float(os.getenv("BASE_LATENCY_MAX", "0.060"))

# Границы гистограммы подобраны вокруг цели по задержке (300 мс).
# Без корзины ровно на пороге SLI по задержке посчитать нельзя.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)

requests_total = Counter(
    "stand_requests_total",
    "Обработанные запросы",
    ["endpoint", "code"],
)
request_duration = Histogram(
    "stand_request_duration_seconds",
    "Время обработки запроса",
    ["endpoint"],
    buckets=LATENCY_BUCKETS,
)
inflight = Gauge(
    "stand_inflight_requests",
    "Запросы в обработке прямо сейчас",
)
fault_error_rate = Gauge(
    "stand_fault_error_rate",
    "Заданная доля ошибок, 0..1",
)
fault_extra_latency = Gauge(
    "stand_fault_extra_latency_seconds",
    "Заданная добавочная задержка",
)

MEASURED_ENDPOINTS = ("/work", "/healthz")


class FaultState:
    """Текущая заданная неисправность.

    Держим в памяти процесса: стенд одноинстансный, состояние намеренно
    теряется при рестарте — это самый быстрый способ вернуть исходное.
    """

    def __init__(self) -> None:
        self.error_rate = 0.0
        self.extra_latency = 0.0
        self.export()

    def export(self) -> None:
        fault_error_rate.set(self.error_rate)
        fault_extra_latency.set(self.extra_latency)

    def reset(self) -> None:
        self.error_rate = 0.0
        self.extra_latency = 0.0
        self.export()


class FaultRequest(BaseModel):
    error_rate: float = Field(0.0, ge=0.0, le=1.0)
    extra_latency_ms: int = Field(0, ge=0, le=10_000)


fault = FaultState()
app = FastAPI(title="reliability stand", version="1.0.0")


@app.middleware("http")
async def observe(request: Request, call_next):
    """Метрики снимаем в middleware, а не в ручке.

    Так в статистику попадают и ответы, до обработчика не дошедшие:
    404, ошибки валидации, необработанные исключения. Если считать
    внутри ручки, SLI будет систематически оптимистичнее правды.
    """
    path = request.url.path
    if path not in MEASURED_ENDPOINTS:
        return await call_next(request)

    started = time.perf_counter()
    inflight.inc()
    try:
        response = await call_next(request)
        code = response.status_code
        return response
    except Exception:
        code = 500
        raise
    finally:
        inflight.dec()
        request_duration.labels(endpoint=path).observe(time.perf_counter() - started)
        requests_total.labels(endpoint=path, code=str(code)).inc()


@app.get("/work")
async def work() -> Response:
    """Ручка, по которой считаются оба SLI."""
    delay = random.uniform(BASE_LATENCY_MIN, BASE_LATENCY_MAX)
    await asyncio.sleep(delay + fault.extra_latency)

    if random.random() < fault.error_rate:
        return Response(
            content='{"status":"error"}',
            status_code=500,
            media_type="application/json",
        )
    return Response(
        content='{"status":"ok"}',
        status_code=200,
        media_type="application/json",
    )


@app.get("/healthz")
async def healthz() -> dict:
    """Живость процесса. Намеренно не зависит от заданной неисправности:
    сервис при 100% ошибок на /work всё ещё жив, и это разные вопросы."""
    return {"status": "ok"}


@app.get("/fault")
async def get_fault() -> dict:
    return {
        "error_rate": fault.error_rate,
        "extra_latency_ms": int(round(fault.extra_latency * 1000)),
    }


@app.post("/fault")
async def set_fault(payload: FaultRequest) -> dict:
    fault.error_rate = payload.error_rate
    fault.extra_latency = payload.extra_latency_ms / 1000
    fault.export()
    return {
        "error_rate": fault.error_rate,
        "extra_latency_ms": payload.extra_latency_ms,
    }


@app.delete("/fault")
async def clear_fault() -> dict:
    fault.reset()
    return {"error_rate": 0.0, "extra_latency_ms": 0}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
