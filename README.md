# Financial Expense Automation

上传图片或 PDF 票据，识别报销信息，并把结构化结果连同**真实附件**写入 Feishu 多维表格（Bitable）。

> 正式链路：`图片/PDF -> 文本抽取 / OCR -> 结构化 -> 校验 -> 用户身份上传附件到 Bitable context -> 写入表格 -> 回读确认`

这不是只做 OCR，也不是只生成 `bitable_write_plan`，而是最终把**真附件**写进 Bitable 附件字段。

---

## 1. 项目能力

当前已验证通过的场景：

- 费用发票图片 -> 费用报销表 -> 真附件写入
- 费用发票 PDF -> 费用报销表 -> 真附件写入
- 交通票图片 -> 交通报销表 -> 真附件写入

成功标准不是脚本退出 0，而是同时满足：

1. 文档识别成功
2. `attachment_upload_result.ok = true`
3. `票据附件` 字段拿到真实 `file_token`
4. 真实 create/update 成功
5. 回读到 Bitable 记录，且附件字段可见

---

## 2. 核心模块与工作方式

这一节先讲项目本身是怎么工作的，再讲 Feishu 接入细节。

### 2.1 核心模块

- `src/skill_entry.py`
  - Skill 主入口
  - 接收输入文件，串起识别、结构化、校验和同步逻辑

- `src/ocr_extract.py`
  - 文档识别入口
  - 对图片走 OCR
  - 对 PDF 优先走原文抽取，必要时回退到 OCR
  - 已修复：当 `document["ext"]` 缺失时，会从 `file_path` / `file_name` 自动推断扩展名，避免 PDF 被误判为 unsupported extension

- `src/sync_bitable.py`
  - 把结构化结果转换成 Bitable 写入字段
  - 负责区分费用表 / 交通表
  - 负责生成 `bitable_write_plan`

- `src/bitable_attachment_uploader.py`
  - 负责把原始图片/PDF先上传到 **Bitable attachment context**
  - 成功后返回真实 `file_token`
  - 这是“真附件写入”能力的关键模块

- `scripts/get_user_access_token.py`
  - 用 Feishu OAuth code 换取用户 `access_token`
  - 保存并刷新 `refresh_token`

### 2.2 识别链路

#### 图片

1. 读取图片
2. 调 OCR 提取文本
3. 归一化为票据结构
4. 提取字段（金额、日期、票据号、乘车人、项目明细等）
5. 输出结构化文档

#### PDF

1. 优先做 PDF 原文抽取
2. 如果 PDF 提取不理想，再回退到 OCR
3. 按票据类型映射结构化字段
4. 输出结构化文档

### 2.3 写表链路

1. 识别出结构化字段
2. 判断目标表（费用 / 交通）
3. 如果配置了附件上传：
   - 先用用户身份把原文件上传到 Bitable context
   - 拿到真实 `file_token`
4. 组装成最终写表字段
5. create/update 到 Bitable
6. 回读确认表里实际可见

### 2.4 `bitable_write_plan` 只是中间态

`bitable_write_plan` 说明的是：

- 识别出了哪些字段
- 准备写哪张表
- 附件上传有没有拿到 `file_token`

它**不是最终完成态**。

最终完成必须继续执行：

- 真实 create/update
- 回读确认

---

## 3. 下载与部署

### 3.1 克隆项目

```bash
git clone git@github.com:lemons101/financial-automation.git
cd financial-automation
```

### 3.2 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3.3 安装依赖

```bash
pip install -r requirements.txt
```

> 必须优先使用项目 `.venv` 运行。不要混用系统 Python。
>
> 已真实踩坑：系统 Python 缺少 `rapidocr_onnxruntime` 时，会导致同样代码在不同环境下行为不一致。

### 3.4 目录说明

- `config/app_config.yaml`：主配置（只保留 env 引用，不放明文 secret）
- `scripts/get_user_access_token.py`：OAuth token 获取与刷新
- `src/skill_entry.py`：Skill 执行入口
- `runtime/oauth/feishu_user_token.json`：运行时用户 token 文件（不进 git）
- `.env.local`：本地环境变量文件（不进 git）

---

## 4. 本地环境配置

### 4.1 为什么用 `.env.local`

`.env.local` 用来放本地敏感配置：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BITABLE_APP_TOKEN`
- `FEISHU_BITABLE_TRANSPORT_TABLE`
- `FEISHU_BITABLE_EXPENSE_TABLE`

建议只放在项目目录，不要写到全局环境（如 `/root/.bashrc`、`/etc/environment`）。

### 4.2 创建 `.env.local`

```bash
cp .env.example .env.local
```

然后按你自己的 Feishu / Bitable 配置填写。

### 4.3 `.env.local` 模板

```bash
FEISHU_APP_ID=cli_your_app_id
FEISHU_APP_SECRET=your_app_secret
FEISHU_BITABLE_APP_TOKEN=your_bitable_app_token
FEISHU_BITABLE_TRANSPORT_TABLE=your_transport_table_id
FEISHU_BITABLE_EXPENSE_TABLE=your_expense_table_id
```

### 4.4 加载本地环境

```bash
set -a
source .env.local
set +a
```

> 如果脚本报 `missing FEISHU_APP_ID or FEISHU_APP_SECRET`，通常就是没有先 `source .env.local`。

---

## 5. Feishu 接入（最小必要说明）

这里只讲项目真正依赖的配置和操作，不展开写成平台接入百科。

### 5.1 OAuth：获取与刷新用户 token

附件上传到 Bitable context 走的是**用户身份**，因此必须先拿到有效的 `user_access_token`。

#### 区分三个概念

- `code`
  - 短时有效
  - 一次性
  - 只能用来换 token
  - **不能直接写进** `runtime/oauth/feishu_user_token.json`

- `access_token`
  - 真正用于调用 Feishu 用户身份接口
  - 附件上传依赖它

- `refresh_token`
  - 用来刷新 `access_token`
  - 会和 `access_token` 一起保存到运行时文件

#### 如何获取 Feishu OAuth code

如果你还没有拿到 code，可以按下面步骤操作。

##### 1）准备一个飞书应用

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 进入「开发者后台」
3. 创建**企业自建应用**（或直接使用已有应用）
4. 记录应用的：
   - `App ID`
   - `App Secret`

这两个值后面分别对应：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

##### 2）配置 OAuth 重定向地址

在应用详情页中进入：

- 「安全设置」 -> 「重定向 URL」

添加一个回调地址。

- 本地测试可用：`http://localhost:8080/callback`
- 生产环境请填写你自己的真实回调接口 URL

> 注意：这里配置的 `redirect_uri`，必须和你后面拼授权链接时使用的地址一致。

##### 3）访问授权链接获取 code

把下面这个链接里的 `YOUR_REDIRECT_URI` 和 `YOUR_APP_ID` 替换成真实值：

```text
https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri=YOUR_REDIRECT_URI&app_id=YOUR_APP_ID
```

例如：

```text
https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri=http://localhost:8080/callback&app_id=cli_xxxxxx
```

然后：

1. 用需要授权的 Feishu 账号打开这个链接
2. 按页面提示完成登录 / 授权
3. 授权成功后，浏览器会跳转到你配置的 `redirect_uri`
4. 跳转后的 URL 参数里会带上 `code`

例如：

```text
http://localhost:8080/callback?code=abc123
```

这里的：

- `abc123`

就是要拿来换 token 的 OAuth code。

##### 4）立刻复制并使用 code

这串 code 一般时效较短，建议拿到后立刻执行换 token。

> 不要把这串 code 直接写进 `runtime/oauth/feishu_user_token.json`，它只是换 token 的中间票据。
>
> 如果你看到的是一串短码，而不是长效 token，大概率那就是 OAuth code。

#### 第一次：用 code 换 token

```bash
cd /root/projects/financial-automation
set -a
source .env.local
set +a
/root/projects/financial-automation/.venv/bin/python scripts/get_user_access_token.py --code '你的code'
```

成功后会写入：

```text
runtime/oauth/feishu_user_token.json
```

该文件里应保存的是脚本真正换出来的：

- `access_token`
- `refresh_token`
- `expires_in`

#### 后续：刷新 token

```bash
cd /root/projects/financial-automation
set -a
source .env.local
set +a
/root/projects/financial-automation/.venv/bin/python scripts/get_user_access_token.py
```

### 5.2 Bitable 配置说明

最容易配错的是三个 ID：

- `app_token`：整个多维表格应用（base）的 token
- `table_id`：具体某张表的 ID
- `view_id`：某个视图的 ID，通常不用填到 `.env.local`

#### 从链接里取值

示例：

```text
https://xcnid10v9ucm.feishu.cn/base/Eddlb4hyba3Vc8saUKFc9ALinjb?table=tblxcZyVvaDgoAcD&view=vew1weMFzv
```

应解析为：

- `FEISHU_BITABLE_APP_TOKEN = Eddlb4hyba3Vc8saUKFc9ALinjb`
- `FEISHU_BITABLE_EXPENSE_TABLE = tblxcZyVvaDgoAcD`
- `view_id = vew1weMFzv`（通常不用填）

#### 一个真实踩过的坑

错误示例：

```bash
FEISHU_BITABLE_TRANSPORT_TABLE=tblepj3koBKTidrW&view=vewEa7wpDL
```

正确示例：

```bash
FEISHU_BITABLE_TRANSPORT_TABLE=tblepj3koBKTidrW
```

如果 `FEISHU_BITABLE_APP_TOKEN` 配错，附件上传常见报错是：

```text
parent node not exist
```

---

## 6. 表结构要求

### 6.1 费用报销表（示例）

建议至少包含：

- `doc_id`
- `报销类型`
- `源文件名`
- `票据附件`
- `票据号码`
- `开票日期`
- `金额`
- `币种`
- `购买方名称`
- `购买方税号`
- `销售方名称`
- `销售方税号`
- `项目名称`
- `数量`
- `单价`
- `项目金额`
- `税率`
- `税额`
- `校验状态`
- `是否复核`
- `复核原因`

### 6.2 交通报销表（示例）

建议至少包含：

- `doc_id`
- `报销类型`
- `源文件名`
- `票据附件`
- `票据号码`
- `金额`
- `币种`
- `购票主体`
- `购票主体税号`
- `乘车人`
- `车次`
- `出发站`
- `到达站`
- `乘车日期`
- `发车时间`
- `座位号`
- `座席`
- `校验状态`
- `是否复核`
- `复核原因`

> `票据附件` 必须是真正的**附件字段**，不能用文本字段占位。

---

## 7. 运行方式

### 7.1 用 `run_skill_job` 跑单个文件

```bash
cd /root/projects/financial-automation
set -a
source .env.local
set +a
/root/projects/financial-automation/.venv/bin/python - <<'PY'
from src.skill_entry import run_skill_job

result = run_skill_job([
    {
        'file_name': 'example.pdf',
        'source_path': '/absolute/path/to/example.pdf',
    }
], config_path='config/app_config.yaml')

print(result)
PY
```

### 7.2 最终成功如何判断

不要只看脚本有没有输出，也不要只看 `bitable_write_plan`。

一次完整成功应满足：

- 文档类型识别正确
- 校验状态通过（或给出明确复核结果）
- `attachment_upload_result.ok = true`
- `票据附件` 字段是 `[{"file_token": ...}]` 这种真附件结构
- Bitable 真实写入成功
- 回读时能看到记录和附件信息

---

## 8. 常见错误与排查

### `Invalid access token for authorization`

原因：

- 把 code 当成了 token
- token 文件内容不对

处理：

- 重新获取 code
- 再运行 `scripts/get_user_access_token.py --code '...'`

### `code is expired`

原因：

- OAuth code 已过期

处理：

- 重新获取新 code
- 立即执行换 token

### `missing FEISHU_APP_ID or FEISHU_APP_SECRET`

原因：

- 没有加载 `.env.local`

处理：

```bash
set -a
source .env.local
set +a
```

### `parent node not exist`

原因：

- `FEISHU_BITABLE_APP_TOKEN` 配错
- 把 table/view 相关值误当成 app token

处理：

- 从 Bitable URL 的 `/base/<app_token>` 位置重新取值

### PDF 被识别成 unsupported extension

历史原因：

- 某些 PDF 输入下 `document["ext"]` 缺失

当前处理：

- 已在代码中修复：当 `ext` 缺失时，自动从 `file_path` / `file_name` 推断扩展名

### 表里没看到结果

排查方向：

- 你是不是只跑到了 `bitable_write_plan`
- 有没有执行真实写表
- 有没有做回读确认

---

## 9. 安全与 Git 提交约束

### 不要提交这些文件

- `.env.local`
- `runtime/oauth/`
- `runtime/oauth/feishu_user_token.json`

### 可以提交这些内容

- 代码
- `.gitignore`
- 配置模板（如 `.env.example`）
- `README.md`

### `config/app_config.yaml` 的原则

仓库中只保留：

- env key 引用
- 非敏感默认值

不要把这些敏感值直接写进 repo：

- app secret
- 用户 token
- refresh token

---

## 10. 推荐操作顺序

1. 克隆项目
2. 创建 `.venv`
3. 安装依赖
4. 创建并填写 `.env.local`
5. 准备好 Feishu Bitable 表结构
6. 获取 OAuth code
7. 执行 `get_user_access_token.py --code '...'`
8. 准备测试图片/PDF
9. 执行 skill
10. 检查 `attachment_upload_result`
11. 真实写入 Bitable
12. 回读确认记录与附件

---

## 11. 已验证通过的真实结果

本项目已做过真实端到端验证，包括：

- PDF -> 费用表 -> 真附件写入 -> 回读成功
- 图片 -> 交通表 -> 真附件写入 -> 回读成功

因此当前主链路已经不是 demo，而是可实际落表的完整流程。
