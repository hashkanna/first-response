import asyncio

from verification.runner import counts, run_process


def test_pytest_summary_counts_use_final_line():
    output = "AssertionError: 90 failed\n================ 2 failed, 22 passed in 0.1s ================"
    assert counts(output) == (24, 2)


def test_runner_enforces_timeout(tmp_path):
    async def scenario():
        code, output = await run_process(tmp_path, ["-c", "import time; time.sleep(10)"], timeout=0.05)
        assert code == 124
        assert "exceeded" in output
    asyncio.run(scenario())


def test_runner_bounds_output(tmp_path):
    async def scenario():
        code, output = await run_process(tmp_path, ["-c", "print('a' * 100000)"])
        assert code == 0
        assert len(output) <= 24000
    asyncio.run(scenario())
