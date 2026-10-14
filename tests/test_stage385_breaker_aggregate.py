"""Three independent slots bound the aggregate half-open probe load."""

import asyncio
import multiprocessing
import time

from exceptions import VetmanagerUpstreamUnavailable


def _slot_probe(result_queue, ready, release):
    from vm_transport.breaker import check_breaker_allows, get_breaker

    async def run():
        breaker = await get_breaker("devtr6")
        breaker.state = "open"
        breaker.opened_at = time.monotonic() - 120
        ready.set()
        release.wait(10)

        async def attempt():
            try:
                return bool(await check_breaker_allows("devtr6"))
            except VetmanagerUpstreamUnavailable:
                return False

        return await asyncio.gather(*(attempt() for _ in range(5)))

    result_queue.put(asyncio.run(run()))


def test_three_slots_admit_at_most_three_half_open_probes(monkeypatch):
    monkeypatch.setenv("BREAKER_COOLDOWN_SECONDS", "0")
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    ready = [context.Event() for _ in range(3)]
    release = context.Event()
    processes = [context.Process(target=_slot_probe, args=(queue, event, release))
                 for event in ready]
    try:
        for process in processes:
            process.start()
        assert all(event.wait(10) for event in ready)
        release.set()
        outcomes = [queue.get(timeout=10) for _ in processes]
        assert sum(sum(slot) for slot in outcomes) == 3
        assert sorted(sum(slot) for slot in outcomes) == [1, 1, 1]
    finally:
        release.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        assert all(process.exitcode == 0 for process in processes)
