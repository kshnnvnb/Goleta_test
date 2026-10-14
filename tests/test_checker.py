import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from json_checker.files import CheckError, write_report
from json_checker.validation import validate_records


ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def test_valid_boundaries_categories_and_extra_fields(self):
        records = [
            {"record_id": f" {category}-{number} ", "category": category, "value": value, "extra": {}}
            for category in ("sensor", "manual", "import")
            for number, value in enumerate((0, 100, 0.0, 100.0, 23.5))
        ]
        before = copy.deepcopy(records)
        report = validate_records(records)
        self.assertEqual(report, dict(total_records=15, valid_records=15,
                                      invalid_records=0, issues=[]))
        self.assertEqual(records, before)

    def test_empty(self):
        self.assertEqual(validate_records([]), dict(total_records=0, valid_records=0,
                                                   invalid_records=0, issues=[]))

    def test_bad_fields(self):
        cases = {
            "record_id": ["", "   ", "\t\n", None, 1, True, [], {}],
            "category": ["", "Sensor", "sensor ", "other", None, 1, True, [], {}],
            "value": [-1, 100.01, "50", True, False, None, [], {},
                      float("inf"), float("-inf"), float("nan")],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    record = dict(record_id="a", category="sensor", value=50)
                    record[field] = value
                    report = validate_records([record])
                    self.assertEqual(report["invalid_records"], 1)
                    self.assertEqual(len(report["issues"]), 1)
                    self.assertEqual(report["issues"][0]["field"], field)
                    self.assertTrue(report["issues"][0]["reason"])

    def test_all_missing_and_multiple_errors_count_once(self):
        records = [{}, dict(record_id=" ", category="bad", value=False)]
        report = validate_records(records)
        self.assertEqual(report["invalid_records"], 2)
        self.assertEqual(report["valid_records"], 0)
        self.assertEqual(len(report["issues"]), 6)
        for index in (0, 1):
            self.assertEqual({item["field"] for item in report["issues"]
                              if item["index"] == index},
                             {"record_id", "category", "value"})

    def test_non_objects(self):
        records = [None, [], "text", 42, False]
        report = validate_records(records)
        self.assertEqual(report["invalid_records"], 5)
        self.assertEqual([issue["index"] for issue in report["issues"]], list(range(5)))
        self.assertTrue(all(issue["field"] == "$record" for issue in report["issues"]))


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / "input.json"
        self.output = self.directory / "new" / "report.json"
        self.source.write_text("[]", encoding="utf-8")

    def run_cli(self, source=None, output=None):
        return subprocess.run(
            [sys.executable, "-m", "json_checker", str(source or self.source),
             "--output", str(output or self.output)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )

    def test_examples_and_report_creation(self):
        for name, counts, issues, code in [
            ("valid", (3, 3, 0), 0, 0),
            ("mixed", (6, 1, 5), 10, 1),
            ("empty", (0, 0, 0), 0, 0),
        ]:
            with self.subTest(name=name):
                source = ROOT / "examples" / f"{name}.json"
                before = source.read_bytes()
                result = self.run_cli(source)
                self.assertEqual(result.returncode, code, result.stderr)
                report = json.loads(self.output.read_text(encoding="utf-8"))
                self.assertEqual(tuple(report[k] for k in
                                       ("total_records", "valid_records", "invalid_records")), counts)
                self.assertEqual(len(report["issues"]), issues)
                self.assertIn("检查完成", result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertEqual(source.read_bytes(), before)

    def test_input_errors_preserve_existing_report(self):
        self.output.parent.mkdir()
        self.output.write_text("previous report", encoding="utf-8")
        for content, message in [
            (b"[", "JSON 无法解析"), (b"", "JSON 无法解析"),
            (b"[NaN]", "JSON 无法解析"), (b"[Infinity]", "JSON 无法解析"),
            (b"{}", "最外层必须是数组"), (b"null", "最外层必须是数组"),
            (b'"text"', "最外层必须是数组"), (b"1", "最外层必须是数组"),
            (b"true", "最外层必须是数组"), (b"\xff", "UTF-8"),
        ]:
            with self.subTest(content=content):
                self.source.write_bytes(content)
                result = self.run_cli()
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(self.output.read_text(), "previous report")

    def test_missing_file_and_input_directory(self):
        self.source.unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("输入文件不存在", result.stderr)
        result = self.run_cli(self.directory)
        self.assertEqual(result.returncode, 2)
        self.assertIn("无法读取输入文件", result.stderr)
        self.assertFalse(self.output.exists())

    def test_same_file_aliases(self):
        symlink = self.directory / "symlink.json"
        symlink.symlink_to(self.source)
        hardlink = self.directory / "hardlink.json"
        hardlink.hardlink_to(self.source)
        for output in (self.source, self.directory / "sub" / ".." / "input.json",
                       symlink, hardlink):
            with self.subTest(output=output):
                result = self.run_cli(output=output)
                self.assertEqual(result.returncode, 2)
                self.assertIn("不能覆盖输入文件", result.stderr)
                self.assertEqual(self.source.read_text(), "[]")

    def test_output_errors(self):
        blocker = self.directory / "file"
        blocker.write_text("unchanged")
        for output in (blocker / "report.json", self.directory):
            with self.subTest(output=output):
                result = self.run_cli(output=output)
                self.assertEqual(result.returncode, 2)
                self.assertIn("无法保存报告", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(blocker.read_text(), "unchanged")
        self.assertEqual(list(self.directory.glob(".json-report-*.tmp")), [])

    def test_write_failure_keeps_previous_report(self):
        self.output.parent.mkdir()
        self.output.write_text("previous")
        with patch("json_checker.files.json.dump", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(CheckError, "无法保存报告"):
                write_report(validate_records([]), self.source, self.output)
        self.assertEqual(self.output.read_text(), "previous")
        self.assertEqual(list(self.output.parent.glob(".json-report-*.tmp")), [])

    def test_missing_cli_arguments(self):
        result = subprocess.run([sys.executable, "-m", "json_checker"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
