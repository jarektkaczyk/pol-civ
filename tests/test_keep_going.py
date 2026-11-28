"""`pipeline process|build --keep-going`: a failing source or builder keeps its previous output and the rest run."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pipeline.__main__ as cli


def _builder(produces, body):
    return types.SimpleNamespace(PRODUCES=produces, REQUIRES=[], build=body, __file__=__file__)


class KeepGoingBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.paths = mock.patch.object(cli, "output_path", lambda name: self.tmp / name)
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def run_build(self, builders, keep_going):
        with mock.patch.object(cli, "select_builders", lambda names, b, deps: list(b)):
            return cli.cmd_build([], force=True, builders=builders, keep_going=keep_going)

    def test_failing_builder_keeps_its_old_output_and_the_rest_run(self):
        (self.tmp / "a.json").write_text("old a")
        (self.tmp / "b.json").write_text("old b")

        def broken():
            (self.tmp / "a.json").write_text("half written")
            raise ValueError("source changed shape")

        def good():
            (self.tmp / "b.json").write_text("new b")

        failed = self.run_build({"a": _builder(["a.json"], broken), "b": _builder(["b.json"], good)}, True)
        self.assertEqual(failed, ["a"])
        self.assertEqual((self.tmp / "a.json").read_text(), "old a")
        self.assertEqual((self.tmp / "b.json").read_text(), "new b")

    def test_new_output_of_a_failing_builder_is_removed(self):
        def broken():
            (self.tmp / "c.json").write_text("partial")
            raise RuntimeError("boom")

        self.assertEqual(self.run_build({"c": _builder(["c.json"], broken)}, True), ["c"])
        self.assertFalse((self.tmp / "c.json").exists())

    def test_sys_exit_in_a_builder_counts_as_a_failure(self):
        def exits():
            raise SystemExit("bad input")

        self.assertEqual(self.run_build({"d": _builder(["d.json"], exits)}, True), ["d"])

    def test_without_keep_going_the_error_stops_the_build(self):
        def broken():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.run_build({"c": _builder(["c.json"], broken)}, False)


class KeepGoingProcessTest(unittest.TestCase):
    def test_failing_source_is_skipped_and_reported(self):
        saved = []
        ok = types.SimpleNamespace(process=lambda: {"rows": 1})

        def broken():
            raise OSError("publisher down")

        bad = types.SimpleNamespace(process=broken)
        with mock.patch.object(cli, "BY_ID", {"ok": ok, "bad": bad}), \
                mock.patch.object(cli, "_pick", lambda names, reg, kind: ["bad", "ok"]), \
                mock.patch.object(cli, "save_interim", lambda sid, data, vintage=None: saved.append(sid)):
            failed = cli.cmd_process([], keep_going=True)
        self.assertEqual(failed, ["bad"])
        self.assertEqual(saved, ["ok"])


if __name__ == "__main__":
    unittest.main()
