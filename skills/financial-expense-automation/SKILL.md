---
name: financial-expense-automation
description: 识别用户上传的报销附件，提取结构化字段，并在当前会话具备飞书工具能力时，真实写入飞书多维表格。适用于 OpenClaw 或 Feishu 中上传的 PDF、JPG、JPEG、PNG 报销票据场景，覆盖识别、校验、写表数据生成与真实落表执行。
---

# Financial Expense Automation

## 概述

运行本地 Financial Automation 流水线，对用户上传的报销票据进行识别、结构化提取、校验，并在当前会话具备飞书多维表格工具能力时继续执行真实写表。

本 skill 当前第一阶段支持的票据范围仍然是：普通电子发票与铁路电子客票。

请明确：
- 识别票据只是前半段
- 生成 `bitable_write_plan` 只是中间产物
- 真正完成标准不是“拿到结构化结果”或“生成 plan”，而是**真实调用飞书多维表格 create/update 成功**

## Repository Location

This skill expects the full project repository to exist on the same machine.

Resolve the project root in this order:

1. Use `FINANCIAL_AUTOMATION_ROOT` if it is set.
2. Otherwise check these common paths:
   - `~/projects/financial-automation`
   - `~/.openclaw/workspace/financial-automation`
   - `/root/projects/financial-automation`

If none of these paths exists, stop and tell the user the repository has not been deployed to the server yet.

After locating the repository root, use:
- `<repo_root>/src/skill_entry.py`
- `<repo_root>/config/app_config.yaml`
- `<repo_root>/.venv/bin/python` as the default interpreter when the virtualenv exists
- `<repo_root>/bin/run_skill_job` as the preferred CLI wrapper for manual runs

## 执行流程

1. 先定位 repository root。
2. 如果 `<repo_root>/.venv/bin/python` 存在，优先使用它，而不是系统 `python3`。
3. 将用户上传文件转换成 `src/skill_entry.py` 所需的 attachment payload。
4. 调用 `run_skill_job(...)`，不要手工串接 ingest、OCR、validate、formatter。
5. 使用返回的 `skill_result` 作为识别结果主对象。
6. 面向用户总结时，优先使用 `user_summary` 与 `highlights`，不要直接堆砌原始 OCR 字段。
7. 当需要落到下游表格时，使用 `documents`、`review_queue` 与 `bitable_write_plan` 作为写表输入。
8. 当 `run_skill_job(...)` 已返回结构化结果或 `bitable_write_plan` 后，必须继续执行真实写表动作，而不是停在 plan。
9. 对飞书多维表格 real-run，默认优先走**当前会话用户身份写表**，而不是直接依赖应用身份写表。
10. **除非明确失败，否则不要停在 plan；必须继续执行真实写表。**

## 强制执行规则

1. `bitable_write_plan` 只是中间产物，不是最终结果。
2. 只要当前会话可用飞书多维表格工具，就必须继续执行真实写表。
3. 不要停留在“建议写入”“准备写入”“可写入”这类状态描述。
4. 只有真正调用 create/update 成功，才算任务完成。
5. 如果没有真实写入成功，必须明确说明失败点，不能把 plan 当完成结果。
6. 禁止把“已生成结构化字段”或“已生成 handoff/prompt”描述成已经完成落表。

## 写表执行规则

1. 当 `run_skill_job(...)` 返回结构化结果或 `bitable_write_plan` 后，必须继续执行写表动作。
2. 根据票据类型决定目标表：
   - `transportation_fee` 写入 `交通报销表`
   - 其他费用类票据写入 `费用报销表`
3. 调用当前会话中可用的飞书多维表格工具，执行真实记录创建或更新。
4. 如果记录不存在，则 create。
5. 如果记录已存在，则 update。
6. 如果附件链路当前不可用，仍然要先把非附件字段真实写入表格。
7. 写入完成后，必须回读或明确确认写入结果，再回复用户。
8. 只要工具可用，就应优先推进真实写表，不要把“后续可手动写入”当作默认交付方式。

## 完成标准

以下情况才算完成：
- 已成功识别票据
- 已成功判断目标表
- 已成功调用飞书多维表格创建或更新记录
- 已明确返回写入结果

以下情况都不算完成：
- 只输出 `bitable_write_plan`
- 只输出结构化字段
- 只说“建议写入”“准备写入”“待写入”
- 只生成 handoff / prompt，但没有真实执行 create/update

## 失败返回规则

如果无法真实写入飞书多维表格，必须明确返回：
1. 是否识别成功
2. 是否已生成写表数据
3. 是否已尝试调用飞书多维表格工具
4. 失败点是在：
   - 工具不可用
   - 权限不足
   - 表不存在
   - create/update 失败
   - 附件链路不可用
5. 当前是否至少已完成“非附件字段写入”

并明确遵守以下约束：
- **禁止把只生成 plan 描述成已经写入成功。**
- 如果附件失败但非附件字段已落表，必须把这两件事分开说清楚。
- 如果连 create/update 都未真正发起，也必须明确说明尚未完成真实写表。

## Inputs

Build attachments as a list of dictionaries in one of these shapes:

```python
[
    {
        "file_name": "hotel_invoice.pdf",
        "content_bytes": b"...",
    },
    {
        "file_name": "ticket.jpg",
        "source_path": "D:/path/to/ticket.jpg",
    },
]
```

Supported file types:
- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`

Ignore unsupported files instead of trying to force them through OCR.
If no supported files remain, stop and tell the user no valid expense attachments were provided.

## Entry Point

Use `<repo_root>/src/skill_entry.py` as the only skill execution entry point.

Preferred runtime choices:
1. **Best**: call `<repo_root>/bin/run_skill_job` for manual CLI runs.
2. **Otherwise**: import `run_skill_job(...)` using `<repo_root>/.venv/bin/python` when the virtualenv exists.
3. Fall back to system `python3` only when the virtualenv is absent.

Primary call:

```python
from src.skill_entry import run_skill_job

result = run_skill_job(attachments)
```

Optional override:

```python
result = run_skill_job(
    attachments,
    config_path=f"{repo_root}/config/app_config.yaml",
)
```

Manual CLI example:

```bash
/root/projects/financial-automation/bin/run_skill_job /path/to/invoice.pdf
```

Example repository root on a cloud server:

```python
repo_root = "/root/projects/financial-automation"
```

## 输出

返回对象本质上是 `skill_result.json` 的内容加上 job metadata。

最重要的字段包括：
- `user_summary`
- `summary`
- `highlights`
- `documents`
- `review_queue`
- `job`
- `bitable_write_plan`

其中：
- `bitable_write_plan` 是飞书真实写表的中间输入，不是完成态
- `documents` 是归一化后的结构化结果
- `review_queue` 用于标记需要人工复核的项目

只有在已经继续调用飞书多维表格工具并完成真实 create/update 后，整个技能调用才算闭环完成。

仅在需要深挖时再查看这些输出文件：
- `skill_json/*.json`
- `skill_review_queue.json`
- `skill_result.json`
- `run_summary.json`

## Deployment Note

Recommended cloud layout:

```text
/root/projects/financial-automation
~/.openclaw/workspace/skills/financial-expense-automation
```

The repository stores the pipeline code.
The skill directory stores the `SKILL.md` and agent metadata that tell OpenClaw how to use the pipeline.

## 当前业务范围

支持的票据类型：
- 普通电子发票
- 铁路电子客票

当前提取重点包括：
- 发票号码、开票日期、金额、发票类型
- 发票购方与销方信息
- 发票行项目合计、税率、税额
- 铁路票购买方、路线、车次、乘客、出行日期、发车时间、席位等字段
- 校验结论与复核原因

保留上述业务范围不变，但执行要求已经升级：**不能只停留在识别与 plan 阶段，具备工具能力时必须继续真实落表。**

## 回复与结果反馈规则

在聊天中回复用户时：
- 先用 `user_summary.headline` 概括识别结果
- 如果 `review_queue` 非空，要明确指出每个复核项及原因
- 发票场景总结购方、销方、金额、行项目重点
- 火车票场景总结购买方、路线、日期、乘客、席位信息

在写入飞书多维表格时：
- 使用 `documents` 作为标准化结构化数据来源
- 使用 `review_queue` 标记需要人工后续处理的项目
- 优先使用 `bitable_write_plan.records` 作为真实 Feishu Bitable 写表动作的输入
- 回复用户时不要只汇报 plan，必须汇报真实写表结果，或明确说明失败点

## 飞书多维表格真实执行建议

对于本 workspace / project，推荐且默认的 real-run 路径是：
1. 先运行本地流水线，拿到 `bitable_write_plan`
2. 在**当前 OpenClaw 会话**中调用飞书多维表格工具，并优先使用**用户身份**写表
3. 如出现授权卡片，要求用户完成授权后重试
4. 附件上传链路可作为单独问题继续跟进，但不能因此阻断“非附件字段先落表”的主链路
5. 只有在真实 create/update 成功后，才能向用户汇报已完成写入

原因：
- 应用身份 Feishu OpenAPI 当前虽可读 Bitable app，但仍可能在 record create 和附件上传上失败
- 用户身份写表已在当前项目方向上证明更接近可用主路径
- 因此该 skill 的默认执行要求应当是：**拿到 plan 后继续真实写表，而不是把 plan 当最终交付**
