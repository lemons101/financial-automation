# Runbook（P0）

## 1. 前置准备
- Python 3.10+（建议使用固定虚拟环境）
- 建议统一使用项目虚拟环境：`/root/projects/financial-automation/.venv`
- 准备输入目录（放发票 PDF/图片）
- 飞书相关（仅同步或 webhook 需要）：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_BITABLE_APP_TOKEN`
  - `FEISHU_BITABLE_EXPENSE_TABLE`
  - `FEISHU_BITABLE_REVIEW_TABLE`

## 2. 配置文件
- `config/app_config.yaml`：运行配置
  - 输入/输出路径
  - OCR 开关与参数
  - webhook 与 bitable 同步参数
- `config/rules.yaml`：规则配置
  - 必填字段
  - 置信度阈值
  - 复核策略

## 3. 本地批处理（主流程）
### 3.1 首次准备虚拟环境
```bash
cd /root/projects/financial-automation
python3 -m venv .venv
./.venv/bin/pip install -i https://pypi.org/simple --trusted-host pypi.org --trusted-host files.pythonhosted.org rapidocr_onnxruntime pypdf PyMuPDF
```

如果 OCR 模块报 `libGL.so.1` 缺失，需要额外安装系统库：

```bash
apt-get update && apt-get install -y libgl1
```

### 3.2 执行处理
1) 放置样例发票到输入目录  
2) 优先使用统一入口执行：

```bash
/root/projects/financial-automation/bin/run_skill_job /path/to/invoice.pdf
```

3) 如需直接调用 Python，请优先使用：

```bash
/root/projects/financial-automation/.venv/bin/python
```

4) 检查输出：
- `runtime/.../extracted_json/*.json`
- `runtime/.../review_queue.json`
- `runtime/.../compliance_report.json`
- `runtime/.../run_summary.json`

## 4. Bitable 同步
### 4.1 Dry-run
- 先执行 dry-run，检查字段映射与样本数据
- 确认主表/复核表字段名一致

### 4.2 Real-run
- 设置飞书环境变量
- 执行真实写入
- 核对新增/更新数量与幂等键行为

## 5. 飞书 webhook 模式
1) 启动 webhook 服务（后续以 `src/webhook.py` 为准）  
2) 在飞书开放平台配置事件订阅地址  
3) 上传文件触发处理  
4) 验证单消息独立目录：
- `runtime/feishu_jobs/<message_id>/<job_id>/`

## 6. 常见问题排查
- 文件锁导致写失败：更换运行输出目录，避免占用
- OCR 结果空：检查图片质量、OCR 依赖与模型路径
- `rapidocr_onnxruntime` 导入失败且提示 `libGL.so.1`：安装系统库 `libgl1`
- 系统 Python 与虚拟环境表现不一致：确认实际使用的是 `/root/projects/financial-automation/.venv/bin/python`
- 同步失败：检查 token、表 ID、字段名一致性
- 重复入库：检查幂等键生成与 upsert 逻辑
- webhook 无响应：检查回调 URL 连通性和事件订阅类型

## 7. 验收清单（Checklist）
- [ ] 主流程可从输入文件生成结构化结果
- [ ] warning/error 可进入复核队列
- [ ] dry-run 输出符合预期
- [ ] real-run 成功写入主表和复核表
- [ ] webhook 模式单消息不混单
- [ ] 运行日志与 summary 完整可追踪
