# 本地 JSON 数据检查工具

仅使用 Python 标准库，无需安装依赖。需要 Python 3.10 或更新版本。在项目根目录执行命令。

```bash
python3 -m json_checker examples/valid.json --output reports/valid-report.json
python3 -m json_checker examples/mixed.json --output reports/mixed-report.json
python3 -m json_checker examples/empty.json --output reports/empty-report.json
```

将输入路径替换为业务系统导出的 UTF-8 JSON 文件。最外层必须是数组；每个元素必须是对象。工具仅检查，不转换或修改原始数据，忽略额外字段。

| 必填字段 | 规则 |
| --- | --- |
| `record_id` | 非空字符串，纯空白（包括空格、制表符、换行）不合格 |
| `category` | 字符串，严格匹配 `sensor`、`manual`、`import` |
| `value` | 0～100 的整数或浮点数，包含两端，不接受字符串和布尔值 |

每条对象记录会检查全部字段。非对象元素仅报告一条记录格式错误。空数组合法。非标准 JSON 常量 `NaN`、`Infinity`、`-Infinity` 按解析错误处理。

同一文件内还会检查 `record_id` 重复：只有非空、非纯空白的字符串参与，按原字符串精确匹配，区分大小写，不去除首尾空白。因此 `a`、`A`、` a`、`a ` 是不同 ID。从第二次出现起，每次都增加一个 `record_id` 问题，原因中注明首次出现的原数组下标（从 0 开始）。首次记录即使缺字段或其他字段不合格，也会参与重复判断。重复错误与字段错误全部保留，不合格记录仍只计一次。不同文件之间不检查重复。单文件和批量模式使用相同规则。

单文件模式的终端会显示总数、合格数、不合格数、问题数和报告路径。报告目录不存在时自动创建；已有报告会被替换，但报告路径不能指向输入文件（包括路径别名、符号链接和硬链接）。读取或校验输入格式失败时，不生成或替换报告。报告先写临时文件，写完后才替换目标文件。

打开报告 JSON 查看结果，也可在终端执行：

```bash
python3 -m json.tool reports/mixed-report.json --no-ensure-ascii
```

报告字段：

| 字段 | 含义 |
| --- | --- |
| `total_records` | 原数组长度 |
| `valid_records` | 合格记录数 |
| `invalid_records` | 不合格记录数，每条记录最多计一次 |
| `issues` | 所有问题；没有问题时为 `[]` |

每个问题包含 `index`（原数组下标，从 0 开始）、`field`（字段名，`$record` 表示整个记录格式错误）、`reason`（错误原因）。例如：

```json
{"index": 1, "field": "record_id", "reason": "字符串不能为空或仅包含空白字符"}
```

退出码：`0` 表示检查成功且全部合格；`1` 表示检查成功但存在不合格记录，报告仍已保存；`2` 表示参数、读取、JSON 解析、根节点格式或报告保存错误，错误提示输出到标准错误。

三个虚构样例的预期结果：

| 样例 | 总数 | 合格 | 不合格 | 问题数 | 退出码 |
| --- | --- | --- | --- | --- | --- |
| `valid.json` | 3 | 3 | 0 | 0 | 0 |
| `mixed.json` | 6 | 1 | 5 | 10 | 1 |
| `empty.json` | 0 | 0 | 0 | 0 | 0 |

## 批量检查

```bash
python3 -m json_checker --input-dir examples/batch --output-dir reports/batch
```

单文件参数与批量参数不能混用。仅选择输入目录直接包含的 `.json` 普通文件，扩展名不区分大小写；按原文件名排序（Python 字符串排序，区分大小写），不递归，也不跟随文件或子目录符号链接。输入目录无效、无匹配文件、输出目录无法创建或写入时会明确报错并返回 `2`。输出目录不能与输入目录相同，也不能位于输入目录内部；检查会解析路径中的 `..` 和符号链接。

每次运行会在输出目录内自动创建一个新的 `run-随机字符/` 子目录：

```text
reports/batch/run-随机字符/
  report-000000.json
  report-000001.json
  report-000003.json
  summary.json
```

独立报告按排序后的文件序号命名，不依赖原文件名，因此 `a.json`、`a.JSON`、`summary.json` 都不会导致报告重名。报告结构与单文件模式一致。处理失败的文件没有本次有效报告，序号允许跳过。历史运行目录会保留，但其报告不会作为本次结果；请以**本次终端打印的汇总报告路径**为准。可按需手动删除历史运行目录。

某个文件消失、无法读取、编码错误、JSON 解析失败、根节点不是数组或报告保存失败时，汇总会记录原因，并继续处理后续文件。字段错误与重复记录不算文件处理失败。“成功”只表示完成检查并成功保存独立报告。

`summary.json` 包含：

| 字段 | 含义 |
| --- | --- |
| `total_files` | 扫描得到的待处理文件总数 |
| `successful_files` / `failed_files` | 成功 / 失败文件数 |
| `total_records` / `valid_records` / `invalid_records` | 仅成功文件的记录合计；没有任何成功文件时为 `null`，成功处理空数组则为 `0` |
| `files` | 按输入文件名排序的逐文件结果 |

每个 `files` 元素包含 `input_path`（绝对路径）、`status`（`success` 或 `failed`）、三项记录统计、`report_path`（本次有效报告绝对路径）及 `error`（失败原因）。读取失败等无法得到的统计为 `null`；校验已完成但报告保存失败时，保留已知的统计，但不纳入成功文件合计。失败文件的 `report_path` 固定为 `null`，成功文件的 `error` 为 `null`。

终端会显示文件处理数、成功文件的记录合计和汇总路径。汇总报告自身保存失败也会明确报错，返回 `2`，此时本次运行目录里可能已有独立报告，但不应视为完整批次结果。

批量退出码：全部处理成功且记录全部合格为 `0`；全部处理成功但存在不合格记录为 `1`；存在任何文件处理失败或其他运行错误为 `2`（优先于 `1`）。

批量样例包含两个数据文件、一个根节点格式错误文件和一个空数组。预期文件总数 `4`、成功 `3`、失败 `1`；成功文件共 `6` 条记录，合格 `4` 条、不合格 `2` 条，退出码为 `2`。其中重复样例第二条同时有重复 ID、category 和 value 错误，第三条仍指向下标 `0` 的首次记录。另一个文件中的同名 ID 不算重复。

也可以单独运行重复样例（预期 4 条中 2 条不合格，共 4 个问题，退出码 `1`）：

```bash
python3 -m json_checker examples/batch/02-duplicates.JSON -o reports/duplicates-report.json
```

查看批量结果时，打开终端给出的 `summary.json`，再按 `files` 中的 `report_path` 打开成功文件报告。也可以将实际路径传给 `python3 -m json.tool 路径 --no-ensure-ascii`。

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

保留原有 12 项测试，仅将原“正常记录”测试中重复使用的 ID 调整为独立 ID，以兼容新增规则。新增测试覆盖精确匹配、首次位置、无效 ID 排除、文件内作用域、批量筛选排序、报告命名、失败后继续、未知统计、旧报告隔离、目录限制、批量退出码及命令行参数组合。读取权限、写权限和磁盘写入失败通过标准库 mock 注入，以稳定验证异常路径；路径错误、损坏 JSON、无效编码、符号链接和硬链接等使用真实临时文件测试。

文件职责：`json_checker/validation.py` 负责字段及重复校验；`files.py` 负责文件读写与路径保护；`batch.py` 负责批量扫描、逐文件处理与汇总；`__main__.py` 负责命令行及终端汇总；`examples/` 存放虚构数据；`tests/` 存放标准库 unittest 测试。
