# 私有 Dashboard

## 定位

Dashboard 是 TDX 模拟交易系统的只读观察与复盘入口。它不下单、不撤单、不修改账户、不切换策略，也不重新计算收益、滑点或研究结论。

## 页面

- `/`：账户权益、持仓、明日计划摘要、执行结果、活动和异常。
- `/trade-plan`：下一交易日计划、策略理由、限价、数量与取消条件。
- `/account`：TDX／策略账户资金、持仓、盈亏、费用和对账状态。
- `/execution`：当日计划、发送、确认、成交和账实差异。
- `/research`：策略、行业和专题研究报告的索引与详情。
- `/system`：Runner、行情、任务、同步、告警和原始健康状态。

## 数据时序

工作日收盘后先镜像 TDX 订单、成交、资产和持仓，再生成执行复盘；策略计划生成成功后发布 `ReviewBundle v2`。研究文档按来源 commit 生成 `ResearchBundle`，只有内容变化才产生新版本。Windows Outbox 负责断网补传，服务器只保存不可变文件和查询索引。

## 研究报告约定

首版研究库把仓库内已经确认的研究证据发布为三类报告：

- 策略：多因子候选、稳健性、分段表现和拒绝／观察结论。
- 行业：申万 2021 一级行业中性与轮动研究。
- 专题：分钟成交质量、P4 审计和执行链等专题证据。

报告生成器不调用大模型，不修改报告原文，也不重新计算指标。摘要与结论来自明确的发布清单；正文直接保存来源 Markdown，详情页展示来源路径、commit、数据截止时间和 SHA256。

## API

- `GET /api/v1/overview`：最新 Bundle、LiveStatus、告警和研究摘要。
- `GET /api/v1/reviews`、`GET /api/v1/reviews/{bundle_id}`：复盘历史与详情。
- `GET /api/v1/research`、`GET /api/v1/research/{report_id}`：研究索引与不可变正文。
- `PUT /api/v1/ingest/bundles/{bundle_id}`、`PUT /api/v1/ingest/research/{report_id}`、`PUT /api/v1/ingest/live-status/{source_id}`：仅供 Bearer token 同步客户端使用。

浏览器查询 API 和静态资源统一要求 Tailscale 身份允许列表；`/healthz` 是唯一匿名健康接口。

## 展示规则

缺少事实时明确显示“尚无数据”或“不适用”，不使用模板 Mock 数字。浏览器只保存主题等非权威偏好；日期、账户、订单、告警和报告内容始终以服务器响应为准。
