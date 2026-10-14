"""业务规则校验：仅检查数据，不修改记录。"""

CATEGORIES = {"sensor", "manual", "import"}


def validate_records(records):
    """返回可 JSON 序列化的报告；根节点必须是列表。"""
    if not isinstance(records, list):
        raise ValueError("JSON 最外层必须是数组")

    issues = []
    invalid_count = 0
    first_positions = {}
    for index, record in enumerate(records):
        start = len(issues)

        def add(field, reason):
            issues.append({"index": index, "field": field, "reason": reason})

        if not isinstance(record, dict):
            add("$record", "记录格式错误：数组元素必须是对象")
        else:
            for field in ("record_id", "category", "value"):
                if field not in record:
                    add(field, "缺少必填字段")
                    continue
                value = record[field]
                if field == "record_id":
                    if not isinstance(value, str):
                        add(field, "必须是非空字符串")
                    elif not value.strip():
                        add(field, "字符串不能为空或仅包含空白字符")
                    elif value in first_positions:
                        add(field, f"record_id 重复，首次出现的位置为 {first_positions[value]}（下标从 0 开始）")
                    else:
                        first_positions[value] = index
                elif field == "category":
                    if not isinstance(value, str):
                        add(field, "必须是字符串")
                    elif value not in CATEGORIES:
                        add(field, "只允许 sensor、manual、import")
                elif isinstance(value, bool) or not isinstance(value, (int, float)):
                    add(field, "必须是数字，不接受数字字符串或布尔值")
                elif not 0 <= value <= 100:
                    add(field, "必须在 0 到 100 之间（包含两端）")

        if len(issues) > start:
            invalid_count += 1

    return {
        "total_records": len(records),
        "valid_records": len(records) - invalid_count,
        "invalid_records": invalid_count,
        "issues": issues,
    }
