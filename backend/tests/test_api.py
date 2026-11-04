import asyncio

from fastapi.testclient import TestClient

from app import main


def test_remembered_serves_the_prepared_answer_until_refreshed():
    calls = []

    async def work():
        calls.append(1)
        return len(calls)

    main._ready.clear()

    async def run():
        first = await main.remembered("k", work)
        second = await main.remembered("k", work)
        third = await main.remembered("k", work, refresh=True)
        return first, second, third

    assert asyncio.run(run()) == (1, 1, 2)


def test_remembered_expires_old_answers():
    async def work():
        return "new"

    main._ready["old"] = (0.0, "old")
    assert asyncio.run(main.remembered("old", work)) == "new"


def test_failed_work_is_not_kept():
    async def bad():
        raise RuntimeError("upstream down")

    main._ready.clear()
    try:
        asyncio.run(main.remembered("x", bad))
    except RuntimeError:
        pass
    assert "x" not in main._ready


def test_every_city_endpoint_is_warmed():
    keys = [key for key, _ in main.warm_jobs()]
    assert "league" in keys and "fires" in keys
    assert all(f"{part}:delhi" in keys for part in ("now", "forecast", "sources", "insights", "history"))
    assert len(keys) == 2 + 8 * 5


def test_bad_inputs_get_clear_errors():
    client = TestClient(main.app)
    assert client.get("/api/city/mars/now").status_code == 404
    assert client.get("/api/map?date=2020-01-01").status_code == 422
