# Runbook（P0）

## 1. 前置准备
- Python 3.10+（建议使用固定虚拟环境）
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
1) 放置样例发票到输入目录  
2) 执行入口（后续以 `src/main.py` 为准）  
3) 检查输出：
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
