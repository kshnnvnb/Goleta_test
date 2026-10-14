"""运行方式：python -m json_checker INPUT -o REPORT。"""

import argparse
import sys

from .files import CheckError, ensure_distinct_paths, read_records, write_report
from .validation import validate_records
from .batch import check_batch


def main(argv=None):
    parser = argparse.ArgumentParser(description="检查本地 JSON 数组中的业务记录")
    parser.add_argument("input", nargs="?", help="输入 JSON 文件（UTF-8）")
    parser.add_argument("-o", "--output", help="单文件 JSON 报告保存路径")
    parser.add_argument("--input-dir", help="批量检查的输入目录")
    parser.add_argument("--output-dir", help="批量报告输出目录")
    args = parser.parse_args(argv)
    batch_mode = args.input_dir is not None or args.output_dir is not None
    if batch_mode:
        if args.input is not None or args.output is not None:
            parser.error("单文件参数不能与批量目录参数混用")
        if args.input_dir is None or args.output_dir is None:
            parser.error("批量模式必须同时指定 --input-dir 和 --output-dir")
    elif args.input is None or args.output is None:
        parser.error("单文件模式必须指定输入文件和 --output")
    try:
        if batch_mode:
            summary, summary_path = check_batch(args.input_dir, args.output_dir)
            def display(key):
                return "未知" if summary[key] is None else summary[key]

            print(
                f"批量检查完成：文件 {summary['total_files']} 个，"
                f"成功 {summary['successful_files']} 个，失败 {summary['failed_files']} 个；"
                f"成功文件记录数 {display('total_records')}，"
                f"合格 {display('valid_records')}，不合格 {display('invalid_records')}。"
                f"汇总报告：{summary_path}"
            )
            if summary["failed_files"]:
                return 2
            return 1 if summary["invalid_records"] else 0
        ensure_distinct_paths(args.input, args.output)
        records = read_records(args.input)
        report = validate_records(records)
        write_report(report, args.input, args.output)
    except CheckError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(
        f"检查完成：总计 {report['total_records']} 条，"
        f"合格 {report['valid_records']} 条，"
        f"不合格 {report['invalid_records']} 条，"
        f"发现 {len(report['issues'])} 个问题。报告：{args.output}"
    )
    return 1 if report["invalid_records"] else 0


if __name__ == "__main__":
    sys.exit(main())
