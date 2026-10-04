import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from scaffold.statewise.agents import llm_client
from scaffold.statewise.experiments.experiment_manager import write_atomic


class CallMetricIsolationTests(unittest.TestCase):


    def test_threads_do_not_share_call_metrics(self):
        thread_count = 5
        counts = {}
        errors = []


        start = threading.Barrier(thread_count)
        mid = threading.Barrier(thread_count)

        def episode(index):
            try:
                llm_client.reset_call_metrics()
                start.wait(timeout=10)
                for call in range(index):
                    llm_client._call_metrics().append(
                        {"stage": f"e{index}_{call}", "ok": True, "total_tokens": 10}
                    )
                mid.wait(timeout=10)
                counts[index] = len(llm_client.get_call_metrics())
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=episode, args=(index,))
            for index in range(1, thread_count + 1)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])

        self.assertEqual(counts, {index: index for index in range(1, thread_count + 1)})

    def test_reset_in_one_thread_does_not_clear_another(self):
        holder_ready = threading.Event()
        resetter_done = threading.Event()
        observed = {}

        def holder():
            llm_client.reset_call_metrics()
            llm_client._call_metrics().append({"stage": "keep", "ok": True})
            holder_ready.set()
            resetter_done.wait(timeout=10)
            observed["holder"] = len(llm_client.get_call_metrics())

        def resetter():
            holder_ready.wait(timeout=10)
            llm_client.reset_call_metrics()
            observed["resetter"] = len(llm_client.get_call_metrics())
            resetter_done.set()

        threads = [threading.Thread(target=holder), threading.Thread(target=resetter)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)


        self.assertEqual(observed.get("holder"), 1)
        self.assertEqual(observed.get("resetter"), 0)

    def test_offset_slicing_stays_correct_per_thread(self):

        results = {}

        def episode(index):
            llm_client.reset_call_metrics()
            offset = len(llm_client.get_call_metrics())
            llm_client._call_metrics().append({"stage": "arm_a", "ok": True})
            first = llm_client.get_call_metrics()[offset:]
            offset = len(first) + offset
            llm_client._call_metrics().append({"stage": "arm_b", "ok": True})
            second = llm_client.get_call_metrics()[offset:]
            results[index] = (
                [item["stage"] for item in first],
                [item["stage"] for item in second],
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(episode, range(4)))

        for index, (first, second) in results.items():
            self.assertEqual(first, ["arm_a"], f"thread {index} arm_a slice")
            self.assertEqual(second, ["arm_b"], f"thread {index} arm_b slice")


class AtomicWriteConcurrencyTests(unittest.TestCase):
    def test_concurrent_writes_to_same_path_do_not_corrupt(self):

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "manifest.json"
            errors = []
            barrier = threading.Barrier(6)

            def writer(index):
                try:
                    barrier.wait(timeout=10)
                    for _ in range(15):
                        write_atomic(target, {"writer": index, "payload": "x" * 200})
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

            self.assertEqual(errors, [])


            parsed = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("writer", parsed)
            self.assertEqual(parsed["payload"], "x" * 200)

            leftovers = [p.name for p in Path(tmp).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
