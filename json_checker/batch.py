"""批量编排：独立检查文件，并在本次专属目录保存结果。"""

import os
from pathlib import Path
import tempfile

from .files import CheckError, read_records, write_report
from .validation import validate_records


COUNTS = ("total_records", "valid_records", "invalid_records")


def discover_files(input_dir):
    try:
        with os.scandir(input_dir) as entries:
            files = [Path(entry.path) for entry in entries
                     if entry.name.lower().endswith(".json")
                     and entry.is_file(follow_symlinks=False)]
    except OSError as exc:
        raise CheckError(f"输入目录无效或无法读取 {input_dir}：{exc}") from exc
    if not files:
        raise CheckError(f"输入目录没有匹配的 JSON 普通文件：{input_dir}")
    return sorted(files, key=lambda path: path.name)


def prepare_output(input_dir, output_dir):
    try:
        source = Path(input_dir).resolve()
        target = Path(output_dir).resolve()
        if target == source or source in target.parents:
            raise CheckError("报告输出目录不能与输入目录相同或位于其内部")
        target.mkdir(parents=True, exist_ok=True)
        # 每次使用新目录：旧报告不会混入本次结果，也没有文件名碰撞。
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=target))
        with tempfile.TemporaryFile(dir=run_dir) as probe:
            probe.write(b"write check")
            probe.flush()
        return run_dir
    except (OSError, RuntimeError) as exc:
        raise CheckError(f"输出目录无法创建或写入 {output_dir}：{exc}") from exc


def check_batch(input_dir, output_dir):
    files = discover_files(input_dir)
    run_dir = prepare_output(input_dir, output_dir)
    summary = {
        "total_files": len(files), "successful_files": 0, "failed_files": 0,
        **{key: None for key in COUNTS}, "files": [],
    }
    for number, source in enumerate(files):
        result = {
            "input_path": str(source.absolute()), "status": "failed",
            **{key: None for key in COUNTS}, "report_path": None, "error": None,
        }
        target = run_dir / f"report-{number:06d}.json"
        try:
            # 扫描后文件可能消失或被替换；逐文件记录错误并继续。
            if source.is_symlink():
                raise CheckError("输入文件已变为符号链接，不跟随符号链接")
            report = validate_records(read_records(source))
            result.update({key: report[key] for key in COUNTS})
            write_report(report, source, target)
        except CheckError as exc:
            result["error"] = str(exc)
            summary["failed_files"] += 1
        else:
            result["status"] = "success"
            result["report_path"] = str(target)
            summary["successful_files"] += 1
            for key in COUNTS:
                summary[key] = (summary[key] or 0) + report[key]
        summary["files"].append(result)

    summary_path = run_dir / "summary.json"
    write_report(summary, files[0], summary_path)
    return summary, summary_path
