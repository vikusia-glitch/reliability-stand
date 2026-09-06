"""Генератор фоновой нагрузки на стенд.

Держит заданный RPS и печатает сводку: сколько запросов ушло, сколько
вернулось ошибками и какие получились перцентили. Нужен, чтобы у SLI
был знаменатель: без трафика доля ошибок не определена, а Prometheus
рисует пустоту вместо аварии.

    python loadgen/loadgen.py --rps 20 --duration 600
"""

import argparse
import asyncio
import time

import httpx


async def worker(client, url, interval, deadline, stats):
    while time.monotonic() < deadline:
        started = time.perf_counter()
        try:
            response = await client.get(url)
            code = response.status_code
        except httpx.HTTPError:
            code = 0
        elapsed = time.perf_counter() - started

        stats["latencies"].append(elapsed)
        stats["codes"][code] = stats["codes"].get(code, 0) + 1

        # Ждём остаток интервала, а не фиксированную паузу: иначе
        # реальный RPS проседает ровно на время обработки запроса.
        sleep_for = interval - elapsed
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


def percentile(values, share):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * share), len(ordered) - 1)
    return ordered[index]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/work")
    parser.add_argument("--rps", type=float, default=20.0)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    interval = args.concurrency / args.rps
    deadline = time.monotonic() + args.duration
    stats = {"latencies": [], "codes": {}}

    limits = httpx.Limits(max_connections=args.concurrency * 2)
    async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
        await asyncio.gather(
            *[
                worker(client, args.url, interval, deadline, stats)
                for _ in range(args.concurrency)
            ]
        )

    total = sum(stats["codes"].values())
    errors = sum(count for code, count in stats["codes"].items() if code >= 500 or code == 0)
    print(f"запросов:      {total}")
    print(f"по кодам:      {dict(sorted(stats['codes'].items()))}")
    print(f"доля ошибок:   {errors / total:.2%}" if total else "нет запросов")
    print(f"p50:           {percentile(stats['latencies'], 0.50) * 1000:.1f} мс")
    print(f"p99:           {percentile(stats['latencies'], 0.99) * 1000:.1f} мс")


if __name__ == "__main__":
    asyncio.run(main())
