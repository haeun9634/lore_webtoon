"""new_harness 실험 경로의 job 줄서기 — 동시 실행 제한(비용 폭주 방지).

두 하네스·overlay 테스트와 같은 방식이다 (pytest 아님, 마지막 줄에 ALL PASS).
호출을 안 하니 돈이 안 든다 — 큐·워커 로직만 가짜 작업으로 검사한다.

    cd landing && python test_nh_pipeline.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import newharness_pipeline as NP  # noqa: E402

fails = []


def ok(name, cond, extra="") -> None:
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def check(name, got, want) -> None:
    ok(name, got == want, f"나온 것: {got!r} / 바라던 것: {want!r}")


def make_runner(root: Path) -> NP.NHRunner:
    """jobs_nh 를 실제 경로 대신 임시 폴더로 돌린다 — 진짜 job 저장소를 안 건드린다."""
    NP.JOBS_DIR = root / "jobs_nh"
    return NP.NHRunner()


def make_job(root: Path, job_id: str) -> NP.NHJob:
    d = root / "jobs_nh" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return NP.NHJob(id=job_id, form={}, dir=d)


def test_serial_execution() -> None:
    """줄에 넣은 일이 한 번에 하나씩만 돈다 — 두 개가 동시에 안 겹친다."""
    root = Path(tempfile.mkdtemp(prefix="nh-test-"))
    try:
        runner = make_runner(root)
        running = []
        max_concurrent = [0]
        lock = threading.Lock()

        def work(n):
            with lock:
                running.append(n)
                max_concurrent[0] = max(max_concurrent[0], len(running))
            time.sleep(0.05)
            with lock:
                running.remove(n)

        for i in range(5):
            runner._enqueue(f"job{i}", lambda i=i: work(i))

        deadline = time.time() + 5
        while runner._worker is not None and time.time() < deadline:
            time.sleep(0.01)

        check("한 번에 하나씩만 돌았다", max_concurrent[0], 1)
        check("큐가 다 비었다", runner.queue, [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_position() -> None:
    """줄에서 몇 번째인지 — 뒤에 온 job 일수록 순서가 크다."""
    root = Path(tempfile.mkdtemp(prefix="nh-test-"))
    try:
        runner = make_runner(root)
        gate = threading.Event()

        def blocked(_n):
            gate.wait(timeout=5)

        for i in range(3):
            runner._enqueue(f"job{i}", lambda i=i: blocked(i))
        time.sleep(0.05)  # 첫 job 이 워커를 잡을 시간

        check("맨 앞은 큐에서 이미 빠졌다(0)", runner.position("job0"), 0)
        check("두 번째는 줄의 0번째(다음 차례)", runner.position("job1"), 0)
        check("세 번째는 줄의 1번째", runner.position("job2"), 1)
        check("모르는 job 은 0", runner.position("job-없음"), 0)

        gate.set()
        deadline = time.time() + 5
        while runner._worker is not None and time.time() < deadline:
            time.sleep(0.01)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cancel_while_queued() -> None:
    """줄에서 기다리는 동안 취소되면 아예 안 돈다 — subprocess 를 안 띄운다."""
    root = Path(tempfile.mkdtemp(prefix="nh-test-"))
    try:
        runner = make_runner(root)
        job_a = make_job(root, "a")
        job_b = make_job(root, "b")
        runner.jobs[job_a.id] = job_a
        runner.jobs[job_b.id] = job_b

        called = []
        gate = threading.Event()

        def hold(_n):
            gate.wait(timeout=5)

        def mark_b():
            called.append("b")

        runner._enqueue(job_a.id, lambda: hold("a"))    # 워커를 잡아 둔다
        runner._enqueue(job_b.id, mark_b)
        time.sleep(0.05)
        job_b.cancel()                                   # 아직 줄에서 기다리는 중
        gate.set()

        deadline = time.time() + 5
        while runner._worker is not None and time.time() < deadline:
            time.sleep(0.01)

        ok("취소된 job 의 일은 실행되지 않았다", "b" not in called)
        check("취소된 job 은 에러로 마무리된다", job_b.status, NP.STATUS_ERROR)
        check("사유가 남는다", job_b.error, "취소되었습니다")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_pick_guards_against_double_queue() -> None:
    """pick() 이 두 번 불려도 같은 job 이 줄에 두 번 안 선다."""
    root = Path(tempfile.mkdtemp(prefix="nh-test-"))
    try:
        runner = make_runner(root)
        job = make_job(root, "p1")
        job.status = NP.STATUS_AWAITING_PICK
        job.directions = [{"n": 1}]
        runner.jobs[job.id] = job

        gate = threading.Event()
        calls = []

        def slow_board(job=job):
            calls.append(1)
            gate.wait(timeout=5)

        orig = NP._run_board_phase
        NP._run_board_phase = slow_board
        try:
            runner.pick(job.id, 1)
            ok("두 번째 pick 은 막힌다", _raises_value_error(lambda: runner.pick(job.id, 1)))
            time.sleep(0.05)
            gate.set()
            deadline = time.time() + 5
            while runner._worker is not None and time.time() < deadline:
                time.sleep(0.01)
            check("실제로는 한 번만 돌았다", len(calls), 1)
        finally:
            NP._run_board_phase = orig
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def main() -> int:
    for fn in (test_serial_execution, test_position, test_cancel_while_queued,
               test_pick_guards_against_double_queue):
        fn()
    if fails:
        print("FAILED:")
        for f in fails:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
