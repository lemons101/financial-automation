# Financial Automation 交给龙虾部署说明

这份文档只回答一件事：

**怎么让龙虾把 `financial-automation` 这个 skill 部署起来，并开始可用。**

不讲项目原理，不讲代码结构，直接讲操作。

---

## 1. 先分清楚谁做什么

### 你手动做

你需要手动准备这 4 类东西：

1. GitHub 仓库地址
2. 飞书应用信息
3. Bitable 表信息
4. OAuth 授权拿到的用户 `code`

### 龙虾做

龙虾负责：

1. clone 仓库
2. 创建 Python 虚拟环境
3. 安装依赖
4. 创建 `.env`
5. 跑本地识别命令
6. 在你已经准备好飞书配置后，继续跑真实落表

---

## 2. 你需要先手动准备什么

在发给龙虾之前，你自己先准备好下面这些值。

### GitHub 仓库地址

```text
git@github.com:lemons101/financial-automation.git
```

HTTPS 备用：

```text
https://github.com/lemons101/financial-automation.git
```

### 飞书应用信息

你需要从飞书开放平台拿到：

```text
FEISHU_APP_ID
FEISHU_APP_SECRET
```

### Bitable 信息

你需要从目标多维表格链接里拿到：

```text
FEISHU_BITABLE_APP_TOKEN
FEISHU_BITABLE_TRANSPORT_TABLE
FEISHU_BITABLE_EXPENSE_TABLE
```

注意：

- `APP_TOKEN` 是整个 base 的 token
- `TABLE` 是具体表的 id
- 不要把 `view=...` 一起填进去

### OAuth 授权 code

这个项目要把真实附件写进 Bitable，依赖**用户身份 token**。

所以你还需要：

1. 在飞书开放平台配置 OAuth 回调地址
2. 打开授权链接
3. 完成授权
4. 从回调 URL 里拿到 `code`

这个 `code` 不是长期 token，只是一次性拿来换 token 的中间值。

如果你现在不知道“回调地址在哪里配、长什么样”，按下面这套做就行。

#### 1）先去哪里配置

打开飞书开放平台：

```text
https://open.feishu.cn/
```

然后按这个路径找：

```text
飞书开放平台
-> 开发者后台
-> 选择你的应用
-> 安全设置
-> 重定向 URL
```

你要在这里添加一个 OAuth 回调地址。

#### 2）回调地址长什么样

本地测试最简单可以先填这个：

```text
http://localhost:8080/callback
```

这是一个很常见的测试回调地址，格式上就是：

```text
http://<域名或IP>:<端口>/<回调路径>
```

例如：

```text
http://localhost:8080/callback
http://127.0.0.1:8080/callback
https://your-domain.com/feishu/callback
```

如果你现在只是为了先拿到 `code`，最推荐直接用：

```text
http://localhost:8080/callback
```

因为它最省事，也最容易看懂。

#### 3）配置时要注意什么

最关键的一条：

**你在飞书开放平台里填写的回调地址，必须和你后面拼授权链接时使用的 `redirect_uri` 完全一致。**

比如你在后台填的是：

```text
http://localhost:8080/callback
```

那你后面授权链接里也必须用：

```text
redirect_uri=http://localhost:8080/callback
```

不能后台填一个，授权链接再写另一个。

#### 4）授权链接怎么拼

你已经有：

- `FEISHU_APP_ID`

再加上你配置好的回调地址，比如：

```text
http://localhost:8080/callback
```

就能拼出一个授权链接：

```text
https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri=http://localhost:8080/callback&app_id=cli_xxxxxxxx
```

其中：

- `redirect_uri` 换成你刚刚配置的回调地址
- `app_id` 换成你自己的 `FEISHU_APP_ID`

如果你怕自己替换错，就直接按这个模板改：

```text
https://open.feishu.cn/open-apis/authen/v1/index?redirect_uri=YOUR_REDIRECT_URI&app_id=YOUR_APP_ID
```

#### 5）打开后会发生什么

你用浏览器打开这个授权链接后，会经历这几步：

1. 飞书让你登录
2. 飞书让你确认授权
3. 授权成功后，浏览器会跳转到你刚才配置的回调地址

跳转后的地址大概会长这样：

```text
http://localhost:8080/callback?code=abc123xyz456
```

这里最重要的就是：

```text
code=abc123xyz456
```

`code=` 后面这一串，就是你要拿去给脚本换 token 的值。

#### 6）你最终要拿到什么

你不需要自己实现回调服务，也不需要写网页。

你现在这一步真正要拿到的，只有这个：

```text
code=...
```

例如：

```text
http://localhost:8080/callback?code=uS9k2AbCdEfG
```

那你真正要复制出来的是：

```text
uS9k2AbCdEfG
```

#### 7）拿到 code 后怎么用

这一步通常分成两半：

你手动做：

- 在浏览器里完成飞书授权
- 从跳转后的 URL 里拿到 `code`

龙虾做：

- 在服务器里执行换 token 脚本
- 把 `code` 换成 `access_token` 和 `refresh_token`
- 生成运行时 token 文件

也就是说，最常见的分工是：

**你拿 `code`，龙虾跑脚本。**

把这个 `code` 发给龙虾，让它执行：

```bash
cd /root/projects/financial-automation
source .venv/bin/activate
set -a
source .env
set +a
python scripts/get_user_access_token.py --code '<你刚拿到的code>'
```

执行成功后，会生成：

```text
runtime/oauth/feishu_user_token.json
```

#### 8）最容易踩坑的地方

最常见的坑就是这几个：

- 回调地址没在飞书后台配置
- 飞书后台配置的地址和授权链接里的 `redirect_uri` 不一致
- 拿到的是整个 URL，却没有把 `code=` 后面的值单独取出来
- `code` 放太久过期了
- 把 `code` 误当成长期 token

如果你看到的是这种短字符串：

```text
abc123xyz456
```

这通常是 `code`。

如果你看到的是脚本换出来后落盘的 `access_token`、`refresh_token`，那才是下一步真正运行时用的 token。

---

## 3. 你要发给龙虾的命令

下面这整段，直接发给龙虾即可。

```text
请帮我部署并初始化这个 OpenClaw skill：

仓库地址：git@github.com:lemons101/financial-automation.git
HTTPS 备用地址：https://github.com/lemons101/financial-automation.git

要求：
1. 不要只复制 skill 子目录，必须 clone 完整仓库
2. 项目部署目录使用 /root/projects/financial-automation
3. 创建 .venv 并安装 requirements.txt
4. 从 .env.example 复制出 .env
5. 等我补完飞书配置后，再继续跑验证

请执行下面这些步骤：

mkdir -p /root/projects
cd /root/projects
git clone git@github.com:lemons101/financial-automation.git
cd /root/projects/financial-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

然后请告诉我：
1. 仓库是否 clone 成功
2. 依赖是否安装成功
3. .env 是否已创建
4. 接下来需要我补哪些飞书配置
```

这一步的目标很简单：

**先让龙虾把项目环境搭起来。**

---

## 4. 先让龙虾去创建飞书多维表格

如果你希望龙虾先把飞书多维表格建好，再回来告诉你 `app_token`、`table_id` 这些值，可以直接把下面这段发给它。

前提是：

- 当前龙虾 / OpenClaw 会话已经具备飞书多维表格创建能力
- 它有权限在你的飞书里新建一个 Bitable

直接发这段：

```text
请先不要部署代码，也先不要跑票据识别。

请先帮我在飞书里创建一个用于 Financial Automation 的多维表格，并把后续部署要用到的信息整理给我。

要求：
1. 新建一个 Feishu Bitable
2. 创建两张表：
   - 费用报销表
   - 交通报销表
3. 两张表都要包含后续部署需要的核心字段
4. 其中“票据附件”必须创建为真正的附件字段，不能是文本字段
5. 创建完成后，把 app_token、table_id 和表结构信息整理回复给我

字段要求如下。

费用报销表至少包含：
- doc_id
- 报销类型
- 源文件名
- 票据附件
- 票据号码
- 开票日期
- 金额
- 币种
- 购买方名称
- 购买方税号
- 销售方名称
- 销售方税号
- 项目名称
- 数量
- 单价
- 项目金额
- 税率
- 税额
- 校验状态
- 是否复核
- 复核原因

交通报销表至少包含：
- doc_id
- 报销类型
- 源文件名
- 票据附件
- 票据号码
- 金额
- 币种
- 购票主体
- 购票主体税号
- 乘车人
- 车次
- 出发站
- 到达站
- 乘车日期
- 发车时间
- 座位号
- 座席
- 校验状态
- 是否复核
- 复核原因

完成后请按下面格式回复我：

1. Bitable 名称
2. Bitable 链接
3. FEISHU_BITABLE_APP_TOKEN=
4. FEISHU_BITABLE_EXPENSE_TABLE=
5. FEISHU_BITABLE_TRANSPORT_TABLE=
6. 费用报销表字段清单
7. 交通报销表字段清单
8. 请特别确认“票据附件”字段是否为附件字段

如果创建失败，请明确告诉我失败在哪一步：
- 没有飞书权限
- 没有创建 Bitable 的能力
- 字段类型不支持
- 其他报错
```

你理想中拿回来的结果，应该长这样：

```text
FEISHU_BITABLE_APP_TOKEN=xxx
FEISHU_BITABLE_EXPENSE_TABLE=tblxxxx
FEISHU_BITABLE_TRANSPORT_TABLE=tblyyyy
```

有了这三个值，你后面就能直接填 `.env` 了。

---

## 5. 你需要手动填给龙虾的 `.env`

龙虾执行完上面步骤后，你需要把这些值提供给它，或者自己填到服务器里的 `.env`：

```text
FEISHU_APP_ID=cli_your_app_id
FEISHU_APP_SECRET=your_app_secret
FEISHU_BITABLE_APP_TOKEN=your_bitable_app_token
FEISHU_BITABLE_TRANSPORT_TABLE=your_transport_table_id
FEISHU_BITABLE_EXPENSE_TABLE=your_expense_table_id
```

建议你直接把这段连同真实值发给龙虾，让它写入：

```text
请把 /root/projects/financial-automation/.env 配成下面这样：

FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_BITABLE_APP_TOKEN=...
FEISHU_BITABLE_TRANSPORT_TABLE=...
FEISHU_BITABLE_EXPENSE_TABLE=...
```

---

## 6. 你要发给龙虾的第二段命令

当 `.env` 配好以后，再把下面这段发给龙虾：

```text
请继续做本地验证。

执行：
cd /root/projects/financial-automation
export FINANCIAL_AUTOMATION_ROOT=/root/projects/financial-automation
bin/run_skill_job /absolute/path/to/test_invoice.pdf

执行完成后请告诉我：
1. 是否成功跑通
2. 是否生成 documents
3. 是否生成 review_queue
4. 是否生成 bitable_write_plan
5. 如果失败，失败点是什么

注意：
不要把“已经生成 bitable_write_plan”当成任务完成。
```

这一步的目标是：

**确认项目本地识别链路已经能跑。**

---

## 7. 你要手动做的 OAuth 换 token

本地识别跑通后，你再自己处理飞书 OAuth。

先拿到授权 `code`，然后让龙虾执行：

```text
请执行飞书用户 token 初始化：

cd /root/projects/financial-automation
source .venv/bin/activate
set -a
source .env
set +a
python scripts/get_user_access_token.py --code '<我提供的OAuth code>'

执行完后请告诉我：
1. token 是否写入成功
2. runtime/oauth/feishu_user_token.json 是否已生成
3. 是否可以继续做真实附件上传和落表验证
```

后续刷新 token 用这段：

```text
请刷新飞书用户 token：

cd /root/projects/financial-automation
source .venv/bin/activate
set -a
source .env
set +a
python scripts/get_user_access_token.py
```

---

## 8. 你要发给龙虾的第三段命令

当用户 token 也准备好后，再让龙虾做真实链路验证：

```text
请继续验证真实落表链路。

要求：
1. 用同一个测试票据重新执行识别
2. 如果当前会话具备飞书写表能力，不要停在 bitable_write_plan
3. 继续执行真实的 Feishu Bitable create/update
4. 尝试把真实附件挂到 Bitable 附件字段
5. 返回最终结果

请重点告诉我：
1. attachment_upload_result.ok 是否为 true
2. 是否真实写入了 Bitable
3. 是写入交通报销表还是费用报销表
4. 回读是否能看到记录和附件
5. 如果失败，失败在 OAuth、附件上传、还是写表阶段
```

这一步的目标是：

**确认不是只识别成功，而是真的写表成功。**

---

## 9. 你自己还要手动确认一件事

去飞书多维表格里确认目标表真的存在这些字段：

```text
doc_id
报销类型
源文件名
票据附件
票据号码
金额
币种
校验状态
是否复核
复核原因
```

最重要的是：

`票据附件` 必须是飞书的**附件字段**，不能是文本字段。

---

## 10. 最小验收标准

你最终要看的不是“龙虾说部署完了”，而是下面这几件事有没有都成立：

1. `/root/projects/financial-automation` 已存在
2. `.venv` 已创建
3. `pip install -r requirements.txt` 已成功
4. `.env` 已写好
5. `runtime/oauth/feishu_user_token.json` 已生成
6. `bin/run_skill_job` 能跑出 `documents`
7. 能生成 `bitable_write_plan`
8. 能真实写入 Feishu Bitable
9. 附件字段里能看到真实附件

---

## 11. 一句话版本

如果你只想记最短流程，就是这 4 步：

1. 你先准备飞书配置和 OAuth code
2. 你把“clone + venv + pip install + cp .env.example .env”发给龙虾
3. 你把真实 `.env` 值发给龙虾，再让它跑 `bin/run_skill_job`
4. 最后再让它继续做真实写表，不要停在 `bitable_write_plan`
