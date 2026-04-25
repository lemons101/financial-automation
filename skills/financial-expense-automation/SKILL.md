---
name: financial-expense-automation
description: 识别用户上传的报销附件，提取结构化字段，并按报销类型写入飞书多维表格。
---

# 财务报销自动化

## 功能说明

这个 skill 用于处理用户上传的报销附件，并完成一条完整链路：

1. 接收 PDF、JPG、JPEG、PNG 格式的票据附件
2. 调用本项目的财务识别流水线提取结构化信息
3. 判断票据属于交通报销还是费用报销
4. 优先使用 OpenClaw 当前用户权限下可用的飞书多维表格能力写入目标表
5. 最后把识别结果、写表结果、是否需要人工复核返回给用户

当前第一版已支持并完成接入的核心范围：
- 费用类电子发票识别
- 交通类票据识别

其中当前最稳定的场景包括：
- 会议费相关电子发票
- 住宿/酒店相关电子发票
- 铁路电子客票

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

1. 先定位项目根目录。
2. 把用户上传的附件整理成 `src/skill_entry.py` 所需的 `attachments` 结构。
3. 调用 `run_skill_job(...)`，不要手动分别调用 ingest、OCR、validate、formatter。
4. 以返回的 `skill_result` 作为主结果对象。
5. 如果需要写入飞书多维表格，优先使用 OpenClaw 当前用户权限下可用的 `feishu-bitable` 能力。
6. 根据票据类型决定写入目标表：
   - `transportation_fee` 写入 `交通报销表`
   - 其他费用类票据写入 `费用报销表`
7. 写入时尽量同时带上：
   - 结构化字段
   - 原始附件
   - 是否需要人工复核
8. 最后回复用户：
   - 识别摘要
   - 写入了哪张表
   - 是否写入成功
   - 是否需要人工复核

## 写表策略

优先策略：
- 使用 OpenClaw 当前用户权限下的飞书多维表格能力完成写表
- 这样更符合你当前的使用方式，也更方便控制权限边界

备选策略：
- 如果当前环境明确要求走项目后端直连飞书 OpenAPI，也可以使用项目中的 Bitable 同步逻辑
- 但默认不要把“后端应用权限直写”当成第一选择

## 内置提示思路

当识别完成后，skill 应按下面的意图继续执行，而不是只停留在提取结果：

`请将本次识别结果按报销类型写入飞书多维表格。交通类写入交通报销表，费用类写入费用报销表，并尽量把原始附件一并写入票据附件字段。`

如果需要向 OpenClaw 明确说明动作，可使用这一类中文指令继续推进：

`请使用当前用户权限下可用的飞书多维表格能力，把识别结果写入对应表格，并返回写入状态。`

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

## 输出结果

返回对象本质上就是 `skill_result.json` 加上一些 job 元数据。

最重要的字段有：
- `user_summary`
- `summary`
- `highlights`
- `documents`
- `review_queue`
- `job`

只有在需要深入排查时，才查看这些输出文件：
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

## 当前能力范围

当前支持的业务分类：
- `conference_fee`：会议、会务、注册费、培训费等费用类发票
- `accommodation_fee`：住宿、酒店、房费等费用类发票
- `transportation_fee`：交通类票据，当前铁路电子客票识别最稳定
- `unknown`：暂时无法稳定归类的票据，仍会尽量提取通用字段并进入复核流程

当前重点提取字段：
- 发票号码、开票日期、金额、票据类型
- 发票购买方、销售方信息
- 发票项目名称、数量、单价、项目金额、税率、税额
- 火车票购票主体、税号、车次、出发站、到达站、乘车日期、发车时间、乘车人、座位信息
- 校验结果与复核原因

说明：
- 交通类里目前最成熟的是铁路电子客票
- 费用类里目前最成熟的是会议费、住宿费相关发票
- 对于其他尚未稳定模板化的票据，会先保留结构化提取结果，并通过复核机制兜底

## 回复方式

在聊天回复中：
- 优先用 `user_summary.headline` 开头
- 如果 `review_queue` 不为空，要明确指出哪些票据需要人工复核，以及原因
- 对普通发票，优先总结购买方、销售方、金额、项目名称
- 对火车票，优先总结购票主体、路线、乘车日期、乘车人、座位信息

当需要写入下游表格时：
- 使用 `documents` 作为标准结构化数据来源
- 使用 `review_queue` 标记需要人工跟进的记录
