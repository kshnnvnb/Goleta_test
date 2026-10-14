"""JSON 文件读取和报告保存。"""

import json
from pathlib import Path
import tempfile


class CheckError(Exception):
    """可直接展示给命令行用户的处理错误。"""


def ensure_distinct_paths(input_path, output_path):
    """识别相对路径别名、符号链接和已有硬链接。"""
    source, target = Path(input_path), Path(output_path)
    try:
        same = source.resolve() == target.resolve()
        if not same and source.exists() and target.exists():
            same = source.samefile(target)
    except (OSError, RuntimeError) as exc:
        raise CheckError(f"无法检查输入和报告路径：{exc}") from exc
    if same:
        raise CheckError("报告路径不能与输入文件相同，不能覆盖输入文件")


def _reject_constant(value):
    raise ValueError(f"不允许非标准 JSON 常量 {value}")


def read_records(path):
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            records = json.load(stream, parse_constant=_reject_constant)
    except FileNotFoundError as exc:
        raise CheckError(f"输入文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(
            f"JSON 无法解析：第 {exc.lineno} 行、第 {exc.colno} 列：{exc.msg}"
        ) from exc
    except UnicodeError as exc:
        raise CheckError(f"输入文件必须使用 UTF-8 编码：{exc}") from exc
    except (ValueError, RecursionError) as exc:
        raise CheckError(f"JSON 无法解析：{exc}") from exc
    except OSError as exc:
        raise CheckError(f"无法读取输入文件 {path}：{exc}") from exc
    if not isinstance(records, list):
        raise CheckError("JSON 最外层必须是数组")
    return records


def write_report(report, input_path, output_path):
    ensure_distinct_paths(input_path, output_path)
    target = Path(output_path)
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先完整写入临时文件，再替换报告，避免写入失败留下半份报告。
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=".json-report-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        temporary.replace(target)
    except OSError as exc:
        raise CheckError(f"无法保存报告 {output_path}：{exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # 清理失败不能掩盖原来的保存错误。
                pass
