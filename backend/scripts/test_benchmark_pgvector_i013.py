"""Harness checks only; these are not PostgreSQL performance results."""

import math
import unittest

from scripts.benchmark_pgvector_i013 import (
    fixture_vector,
    parse_positive_list,
    percentile,
    physical_memory_bytes,
    validate_database_url,
)


class I013BenchmarkHarnessTests(unittest.TestCase):
    def test_database_guard_rejects_sqlite_remote_and_nonisolated_database(self):
        rejected = (
            "sqlite:///blog_i013_bench_test",
            "postgres://localhost/blog",
            "postgres://example.com/blog_i013_bench_test",
            "postgres://localhost/blog_i013_bench_",
            "postgres://localhost/blog_i013_bench_test%2Fother",
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_database_url(url)
        self.assertEqual(
            validate_database_url("postgres://user:secret@127.0.0.1/blog_i013_bench_test"),
            "blog_i013_bench_test",
        )

    def test_fixture_vectors_are_deterministic_and_normalized(self):
        first = fixture_vector(3, 384, 13013)
        self.assertEqual(first, fixture_vector(3, 384, 13013))
        self.assertNotEqual(first, fixture_vector(4, 384, 13013))
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0)

    def test_statistics_and_scenario_inputs(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(percentile([1, 2, 3, 4, 5], 95), 4.8)
        self.assertEqual(parse_positive_list("1000, 10000"), (1000, 10000))
        for value in ("", "0,4", "-1", "4,nope"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_positive_list(value)

    def test_hardware_memory_probe(self):
        value = physical_memory_bytes()
        self.assertTrue(value is None or value > 0)


if __name__ == "__main__":
    unittest.main()
