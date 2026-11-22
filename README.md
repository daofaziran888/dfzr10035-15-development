# 网关工坊 · API接口采集与数据网关平台

面向第三方API接入注册、接口鉴权编排、限流熔断、响应解析、schema映射、结果缓存、重放恢复与交付订阅的API接口采集与数据网关平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 接口提供方 | `api_provider` | API提供方 | 提供方编号、提供方名称、认证方式 |
| 鉴权配置 | `auth_profile` | 鉴权方案 | 方案编号、提供方、鉴权类型 |
| 接口定义 | `endpoint_def` | 接口端点 | 端点编号、提供方、请求路径 |
| 限流熔断 | `rate_limit` | 限流策略 | 策略编号、目标端点、QPS上限 |
| 请求批次 | `request_batch` | 调用批次 | 批次编号、关联端点、参数模板 |
| 响应解析 | `response_parse` | 解析规则 | 规则编号、目标端点、JSON路径 |
| Schema差异 | `schema_diff` | 差异记录 | 记录编号、关联端点、变更字段、引用差异、键映射 |
| 采集证据 | `diff_evidence` | 采集证据 | 证据编号、证据字段、旧键引用、样本原值 |
| 差异复核分组 | `diff_review_group` | 复核分组 | 分组编号、复核类型、覆盖差异、确认凭据 |
| 差异确认待办 | `diff_confirmation` | 差异确认待办 | 待办编号、确认凭据、审核结论、落库版本 |
| 结果缓存 | `data_cache` | 缓存策略 | 策略编号、目标端点、缓存TTL |
| 重放队列 | `retry_queue` | 重放任务 | 任务编号、失败端点、失败原因 |
| 数据投递 | `data_delivery` | 投递管道 | 管道编号、数据来源、目标地址 |
| 订阅管理 | `subscriber` | 订阅方 | 订阅编号、订阅方、数据主题 |
| 接口监控 | `api_monitor` | 监控指标 | 指标编号、目标端点、监控类型 |
| Webhook路由 | `webhook_router` | 回调规则 | 规则编号、触发事件、目标URL |
| 传输加密 | `data_encrypt` | 加密配置 | 配置编号、数据范围、加密算法 |
| 调用日志 | `call_log` | 调用记录 | 记录编号、接口端点、请求参数 |
| 数据版本 | `data_version` | 数据快照 | 版本编号、数据来源、行数统计 |
| 管道审计 | `pipeline_audit` | 审计记录 | 记录编号、管道名称、操作人 |
| 治理报告 | `govern_report` | 治理报告 | 报告编号、评估范围、合规指标 |
| 增量追踪 | `incr_tracker` | 增量标记 | 标记编号、目标端点、增量字段 |
| 抽样校验 | `sample_check` | 抽样计划 | 计划编号、目标端点、抽样比例 |
| 用量计费 | `cost_account` | 用量账单 | 账单编号、提供方、计费周期 |
| 任务调度 | `task_schedule` | 调度计划 | 计划编号、关联端点、Cron表达式 |

## 差异复核（按引用关系归并）

Schema差异单条标记不够用时，用一次提交选中多条差异，按字段差异的实际引用关系归并成复核分组：

- `POST /api/schema_diff/review/batch`：提交 `diff_ids`。同一端点下的差异按 `引用差异` 连通，
  共享 `键映射`（如 `order_id+line_no→item_key`）的字段进入**关联组**；没有引用关系、
  可单列验证的差异进入**独立组**。分组结果写回分组表，并同步登记治理报告与差异确认待办。
- `GET /api/schema_diff/review/workspace?endpoint=`：回查差异、证据、分组、报告、待办、数据版本。
- `POST /api/diff_evidence/review`：补采样本，保留 `样本原值`、`旧键引用` 和采集依据。
  关联组要凑齐旧键样本与新字段样本（新字段样本需覆盖全部旧键）才能组合出完整定义；
  独立组只需单列样本。
- `POST /api/diff_review_group/{id}/actions` `重提核验`：补采后重算证据，刷新报告与待办。
- `POST /api/diff_confirmation/batch`：批量确认待办。同一 `确认凭据` 只认一次，重复提交不会重复
  发待办或重复落库；证据不足的分组只回写缺口，不落库。
- 确认通过后差异置为 `已确认`，`data_version` 按已审核的来源与映射生成版本
  （`映射定义` 为组合出的完整定义，`依赖版本` 保留旧定义）。

前端复核台在 `/diff_review`，可批量勾选差异、查看分组归并/补采依据、确认待办并回查落库版本。
示例链路：`ENDP-ORD-0006` 上 `order_id`、`line_no`、`item_key` 三条差异共享同一键映射，
`remark` 为独立新增列；初始只提供旧键与备注样本，因此关联组需补采 `item_key` 覆盖两个旧键的样本后才能落库。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
