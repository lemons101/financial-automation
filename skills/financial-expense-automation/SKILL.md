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

## 仓库位置

这个 skill 依赖完整项目仓库，不能只单独拷贝 `SKILL.md` 使用。

按以下顺序定位项目根目录：

1. 如果设置了 `FINANCIAL_AUTOMATION_ROOT`，优先使用它
2. 否则依次检查这些常见路径：
   - `~/projects/financial-automation`
   - `~/.openclaw/workspace/financial-automation`
   - `/root/projects/financial-automation`

如果这些路径都不存在，应直接告诉用户：服务器上还没有部署完整项目仓库。

找到根目录后，主要使用：
- `<repo_root>/src/skill_entry.py`
- `<repo_root>/config/app_config.yaml`

## 执行流程

1. 先定位 repository root。
2. 将用户上传文件转换成 `src/skill_entry.py` 所需的 attachment payload。
3. 调用 `run_skill_job(...)`，不要手工串接 ingest、OCR、validate、formatter。
4. 使用返回的 `skill_result` 作为识别结果主对象。
5. 面向用户总结时，优先使用 `user_summary` 与 `highlights`，不要直接堆砌原始 OCR 字段。
6. 当需要落到下游表格时，使用 `documents`、`review_queue` 与 `bitable_write_plan` 作为写表输入。
7. 当 `run_skill_job(...)` 已返回结构化结果或 `bitable_write_plan` 后，必须继续执行真实写表动作，而不是停在 plan。
8. 对飞书多维表格 real-run，默认优先走**当前会话用户身份写表**。
9. 写表前，必须先判断目标表是否存在可复用空白行。
10. 附件字段禁止直接使用通用 Drive upload token，必须先上传到当前 **bitable attachment context**，再写回对应 `file_token`；如果附件链路不可用，也要先完成非附件字段写入。
11. **除非明确失败，否则不要停在 plan；必须继续执行真实写表。**

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
6. 如果存在可复用空白行，优先 update 空白行，而不是盲目追加 create。
7. 如果附件链路当前不可用，仍然要先把非附件字段真实写入表格。
8. 写入完成后，必须回读或明确确认写入结果，再回复用户。

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

## 输入格式

附件应整理成如下列表结构之一：

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

支持的文件类型：
- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`

对于不支持的文件类型，直接忽略，不要强行 OCR。
如果过滤后没有可用附件，应直接告诉用户：没有收到可处理的报销附件。

## 入口

唯一入口使用 `<repo_root>/src/skill_entry.py`。

标准调用方式：

```python
from src.skill_entry import run_skill_job

result = run_skill_job(attachments)
```

如有需要，也可以显式传入配置文件：

```python
result = run_skill_job(
    attachments,
    config_path=f"{repo_root}/config/app_config.yaml",
)
```

云端常见仓库路径示例：

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

## 部署说明

推荐的云端目录布局：

```text
/root/projects/financial-automation
~/.openclaw/workspace/skills/financial-expense-automation
```

项目仓库存放流水线代码。  
skill 目录存放 `SKILL.md` 和 agent 配置，用来告诉 OpenClaw 如何使用这套能力。

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
- 回复用户时不要只汇报 plan，必须汇报真实写表结果，或明确说明失败点

## 飞书多维表格真实执行建议

对于本 workspace / project，推荐且默认的 real-run 路径是：
1. 先运行本地流水线，拿到 `bitable_write_plan`
2. 在**当前 OpenClaw 会话**中调用飞书多维表格工具，并优先使用**用户身份**写表
3. 如出现授权卡片，要求用户完成授权后重试
4. 针对 `bitable_write_plan.records` 中的每一项，先判断目标表：
   - `transport` → `交通报销表`
   - `expense` → `费用报销表`
5. 写入前先查询目标表，寻找**第一个可复用空白行**
6. 若 `doc_id` 为空 / 缺失 / 空白，则视为可复用空白行
7. 若存在可复用空白行，则优先对该 `record_id` 执行 **update**
8. 若不存在可复用空白行，再执行 **create**
9. 非附件字段必须优先真实写入
10. 附件字段如可用，则先上传到 bitable attachment context，再写入返回的 `file_token`
11. 只有在真实 create/update 成功后，才能向用户汇报已完成写入

### 写入策略（必须遵守）

写报销记录到 Feishu Bitable 时：
- 优先采用 **update-first-blank-row-then-create**
- 如果前面存在可复用空白行，禁止盲目追加 create
- 主要的空白判断字段是 `doc_id`
- 即便某些装饰/默认列已有值，只要 `doc_id` 为空，仍可复用该行
- 若 `doc_id` 已有值，则视为已占用，除非用户明确要求覆盖，否则不要覆写

### 字段映射规则

必须使用项目格式化后的展示字段，而不是原始机器枚举值。

期望展示映射：
- `transportation_fee` → `🚄 交通报销`
- 其他费用类票据 → `🧾 费用报销`
- `pass` → `✅ 通过`
- `warning` → `⚠️ 待复核`
- `error` → `❌ 异常`

期望的人类可读字段包括：
- `报销类型`
- `校验状态`
- `识别摘要`
- `票据附件`
- `原始JSON`

### 附件降级规则

如果当前运行环境还不能稳定提供 bitable-context 附件上传能力：
- **不要**伪造 `file_token`
- **不要**使用通用 Drive upload token 冒充 bitable 附件
- 应将 `票据附件` 先写成纯文本占位，例如 `🖼️ 原图已接收：<文件名>`
- 同时继续把该行其他字段真实写入表格，确保报销记录先落表

原因：
- 应用身份 Feishu OpenAPI 当前虽可读 Bitable app，但 record create 与附件上传仍可能失败
- 用户身份写表才是当前会话内的主 real-run 路径
- 通用 Drive upload token 已被实验验证不适用于 bitable 附件字段

写入下游表格时：
- 使用 `documents` 作为标准化结构化数据来源
- 使用 `review_queue` 表示需要人工后续处理的项目
- 使用 `bitable_write_plan.records` 作为真实非附件字段写表输入
- 若 `bitable_write_plan.attachment_upload_handoff.required` 为 true，则视为附件必须走 bitable 专用上传链路，不能把通用上传当成完成态
