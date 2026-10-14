import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from json_checker.batch import check_batch
from json_checker.files import CheckError, read_records, write_report
from json_checker.validation import validate_records


ROOT = Path(__file__).resolve().parents[1]


def record(identifier="same", **changes):
    return dict(record_id=identifier, category="sensor", value=50, **changes)


class DuplicateTests(unittest.TestCase):
    def test_exact_matching_and_first_position(self):
        records = [record(value) for value in ("a", "A", " a", "a ", "a", "a", " a")]
        before = copy.deepcopy(records)
        report = validate_records(records)
        self.assertEqual((report["total_records"], report["valid_records"],
                          report["invalid_records"]), (7, 4, 3))
        self.assertEqual([issue["index"] for issue in report["issues"]], [4, 5, 6])
        for issue, first in zip(report["issues"], (0, 0, 2)):
            self.assertEqual(issue["field"], "record_id")
            self.assertIn(f"首次出现的位置为 {first}", issue["reason"])
        self.assertEqual(records, before)

    def test_invalid_other_fields_still_participate(self):
        report = validate_records([
            {"record_id": "x"},
            {"record_id": "x", "category": "bad", "value": False},
            record("x"),
        ])
        self.assertEqual(report["invalid_records"], 3)
        self.assertEqual(len(report["issues"]), 6)
        duplicates = [issue for issue in report["issues"] if "重复" in issue["reason"]]
        self.assertEqual([issue["index"] for issue in duplicates], [1, 2])
        self.assertTrue(all("首次出现的位置为 0" in issue["reason"] for issue in duplicates))

    def test_invalid_ids_do_not_participate(self):
        values = ["", " ", "\t", None, True, 5, [], {}]
        records = [record(value) for value in values for _ in range(2)] + [{}, {}, None]
        report = validate_records(records)
        self.assertEqual(report["invalid_records"], len(records))
        self.assertFalse(any("重复" in issue["reason"] for issue in report["issues"]))


class BatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "inputs"
        self.source.mkdir()
        self.output = self.root / "reports"

    def put(self, name, data):
        path = self.source / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "json_checker", *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")

    def batch_cli(self):
        return self.cli("--input-dir", self.source, "--output-dir", self.output)

    def test_selection_sorting_unique_reports_and_file_scope(self):
        for name in ("a.json", "a.JSON", "summary.json", "z.JsOn"):
            self.put(name, [record()])
        self.put("ignored.txt", [record(), record()])
        (self.source / "folder.json").mkdir()
        (self.source / "folder.json" / "nested.json").write_text("[]")
        (self.source / "link.json").symlink_to(self.source / "a.json")
        (self.source / "broken.json").symlink_to(self.source / "missing")
        before = {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        summary, path = check_batch(self.source, self.output)
        self.assertEqual(summary["total_files"], 4)
        self.assertEqual(summary["successful_files"], 4)
        self.assertEqual(summary["failed_files"], 0)
        self.assertEqual(summary["total_records"], 4)
        self.assertEqual(summary["valid_records"], 4)
        self.assertEqual(summary["invalid_records"], 0)
        entries = summary["files"]
        self.assertEqual([Path(item["input_path"]).name for item in entries],
                         ["a.JSON", "a.json", "summary.json", "z.JsOn"])
        self.assertEqual(len({item["report_path"] for item in entries} | {str(path)}), 5)
        for item in entries:
            report = json.loads(Path(item["report_path"]).read_text())
            self.assertEqual(report, validate_records([record()]))
            self.assertEqual(item["status"], "success")
            self.assertIsNone(item["error"])
        self.assertEqual(json.loads(path.read_text()), summary)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir() if p.is_file()})

    def test_parse_encoding_root_errors_continue_and_null_counts(self):
        (self.source / "a.json").write_bytes(b"[")
        (self.source / "b.json").write_bytes(b"\xff")
        self.put("c.json", {})
        self.put("d.json", [record(), record()])
        summary, _ = check_batch(self.source, self.output)
        self.assertEqual((summary["total_files"], summary["successful_files"],
                          summary["failed_files"]), (4, 1, 3))
        self.assertEqual((summary["total_records"], summary["valid_records"],
                          summary["invalid_records"]), (2, 1, 1))
        for item, message in zip(summary["files"][:3], ("JSON 无法解析", "UTF-8", "最外层")):
            self.assertIn(message, item["error"])
            self.assertEqual(item["status"], "failed")
            for key in ("total_records", "valid_records", "invalid_records", "report_path"):
                self.assertIsNone(item[key])

    def test_missing_unreadable_or_replaced_input_continues(self):
        first = self.put("a.json", [])
        self.put("b.json", [record()])
        for mode in ("missing", "permission", "symlink"):
            first.unlink(missing_ok=True)
            first.write_text("[]")
            original = read_records

            def change_then_read(path):
                if path.name == "a.json":
                    if mode == "missing":
                        path.unlink()
                    elif mode == "permission":
                        with patch("pathlib.Path.open", side_effect=PermissionError("denied")):
                            return original(path)
                return original(path)

            if mode == "symlink":
                from json_checker.batch import prepare_output

                def replace_after_scan(*args):
                    first.unlink()
                    first.symlink_to(self.source / "b.json")
                    return prepare_output(*args)

                context = patch("json_checker.batch.prepare_output", side_effect=replace_after_scan)
            else:
                context = patch("json_checker.batch.read_records", side_effect=change_then_read)
            with self.subTest(mode=mode), context:
                summary, _ = check_batch(self.source, self.output)
                self.assertEqual(summary["failed_files"], 1)
                self.assertEqual(summary["successful_files"], 1)
                self.assertIsNone(summary["files"][0]["total_records"])
                self.assertTrue(summary["files"][0]["error"])

    def test_save_failure_keeps_known_stats_and_excludes_from_totals(self):
        self.put("a.json", [record(), record()])
        self.put("b.json", [])

        def fail_first(report, source, target):
            if target.name == "report-000000.json":
                with patch("json_checker.files.json.dump", side_effect=OSError("disk full")):
                    return write_report(report, source, target)
            return write_report(report, source, target)

        with patch("json_checker.batch.write_report", side_effect=fail_first):
            summary, path = check_batch(self.source, self.output)
        self.assertEqual(summary["failed_files"], 1)
        self.assertEqual(summary["successful_files"], 1)
        self.assertEqual(summary["total_records"], 0)
        self.assertEqual(summary["invalid_records"], 0)
        failed = summary["files"][0]
        self.assertEqual(failed["total_records"], 2)
        self.assertEqual(failed["invalid_records"], 1)
        self.assertIsNone(failed["report_path"])
        self.assertIn("disk full", failed["error"])
        self.assertFalse((path.parent / "report-000000.json").exists())
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_old_reports_not_used_on_rerun_failure(self):
        source = self.put("a.json", [record()])
        old, old_path = check_batch(self.source, self.output)
        old_report = Path(old["files"][0]["report_path"])
        old_content = old_report.read_bytes()
        source.write_text("[")
        new, new_path = check_batch(self.source, self.output)
        self.assertNotEqual(old_path.parent, new_path.parent)
        self.assertIsNone(new["files"][0]["report_path"])
        self.assertEqual(new["successful_files"], 0)
        self.assertEqual(new["failed_files"], 1)
        self.assertIsNone(new["total_records"])
        self.assertIsNone(new["valid_records"])
        self.assertIsNone(new["invalid_records"])
        self.assertEqual(list(new_path.parent.glob("report-*.json")), [])
        self.assertEqual(old_report.read_bytes(), old_content)

    def test_input_directory_errors(self):
        for source, message in ((self.source, "没有匹配"),
                                (self.root / "missing", "输入目录无效")):
            with self.subTest(source=source):
                result = self.cli("--input-dir", source, "--output-dir", self.output)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
        file_path = self.put("file.json", [])
        with self.assertRaisesRegex(CheckError, "输入目录无效"):
            check_batch(file_path, self.output)
        with patch("json_checker.batch.os.scandir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(CheckError, "无法读取"):
                check_batch(self.source, self.output)

    def test_output_directory_restrictions_and_aliases(self):
        self.put("a.json", [])
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        for output in (self.source, self.source / "nested", alias, alias / "nested",
                       self.source / "sub" / ".." / "report"):
            with self.subTest(output=output):
                result = self.cli("--input-dir", self.source, "--output-dir", output)
                self.assertEqual(result.returncode, 2)
                self.assertIn("不能与输入目录相同或位于其内部", result.stderr)
        self.assertFalse((self.source / "nested").exists())

    def test_output_creation_write_and_summary_failure(self):
        self.put("a.json", [])
        blocker = self.root / "blocker"
        blocker.write_text("unchanged")
        for output in (blocker, blocker / "child"):
            with self.assertRaisesRegex(CheckError, "输出目录无法创建或写入"):
                check_batch(self.source, output)
        with patch("json_checker.batch.tempfile.TemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(CheckError, "输出目录无法创建或写入"):
                check_batch(self.source, self.output)

        def fail_summary(report, source, target):
            if target.name == "summary.json":
                raise CheckError("无法保存报告：summary disk full")
            return write_report(report, source, target)

        from json_checker.__main__ import main
        with patch("json_checker.batch.write_report", side_effect=fail_summary), \
                patch("sys.stderr") as stderr:
            code = main(["--input-dir", str(self.source), "--output-dir", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("summary disk full", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_exit_codes_and_single_file_duplicates(self):
        source = self.put("a.json", [record()])
        for data, expected in (([record()], 0), ([record(), record()], 1), ({}, 2), ([], 0)):
            source.write_text(json.dumps(data))
            result = self.batch_cli()
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertIn("汇总报告：", result.stdout)
        self.put("a.json", [record(), record()])
        result = self.cli(source, "-o", self.root / "single.json")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.root / "single.json").read_text())
        self.assertEqual(report["invalid_records"], 1)
        self.assertIn("首次出现的位置为 0", report["issues"][0]["reason"])
        self.put("b.json", {})
        self.assertEqual(self.batch_cli().returncode, 2)

    def test_cli_argument_combinations(self):
        for args in (("--input-dir", self.source), ("--output-dir", self.output),
                     ("file.json", "--input-dir", self.source, "--output-dir", self.output),
                     ("-o", "report.json", "--input-dir", self.source, "--output-dir", self.output)):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
