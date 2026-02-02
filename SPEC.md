# SPEC.md — 盘中涨跌看板（本地自用原型，从零实现）

## 0. 目标与范围
做一个“自用、无微服务、轻前端”的本地盘中涨跌看板原型：

- 本地桌面：Python + pywebview（内嵌 WebView）
- 前端：极简 HTML/JS 单页（无 React/无构建链）
- 存储：CSV 文件（配置为主；不做数据库）
- 功能：仅展示“当日盘中涨跌(%)”与来源信息
- 不做：盈亏计算、流水、OCR、账号/登录、日志系统（允许 stdout 打印）

**硬需求**：盘中（交易时段）必须能刷新出结果；如果某数据源停更（例如停在上周五），必须自动判定 stale 并降级到备援。

---

## 1. 总体架构与硬约束

### 1.1 无微服务
- 禁止 FastAPI/Flask/Django/任意 HTTP Server 作为主交互。
- 必须通过 pywebview 的 JS ↔ Python bridge 实现“按钮触发刷新”。

### 1.2 数据源策略（必须遵守）
- 不使用需要 API key 的服务；不使用付费 API。
- 禁止：Yahoo Finance/yfinance、TradingView、Google Finance、任何全球行情聚合 SDK。
- 不允许运行时用搜索引擎“发现”数据源 URL（百度/Google/DDG 等）。
- 允许的数据源必须是“公开可访问、无需登录/Key、可在浏览器验证”的页面或接口。

### 1.3 参考实现（必须）
数据获取逻辑必须参考并复用仓库的“fundgz 链路与解析思路”（只参考数据层，不照搬工程）：
- https://github.com/hzm0321/real-time-fund

要求：
- 在 README 中注明参考仓库、以及迁移了哪些 provider 与规则（文件/函数级别）。
- 不引入 Next.js/React/Node 依赖。

---

## 2. 功能定义（阶段 1）

### 2.1 UI 功能
- 显示一个表格：产品名/代码、盘中涨跌%、source_provider、asof_time、status/error、source_url
- 一个“刷新”按钮：点击后调用 Python `refresh()`，返回结果后渲染表格
- 显示免责声明：盘中估值/预估涨跌不等同于最终净值，仅供参考

### 2.2 输出字段（Python -> UI）
`refresh()` 返回数组，每个产品一个对象，必须包含：

- code: string
- name: string
- kind: otc/etf/lof/qdii
- intraday_pct: float 或 null（+1.23 表示 +1.23%）
- status: ok / na / error
- error: string 可空
- source_mode: fund_intraday（阶段1固定）
- source_provider: fundgz / aniu
- source_url: string（必须，可审计）
- asof_time: ISO 时间字符串（本地时间，Asia/Singapore）
- meta: object（可选，至少建议包含 est_date / gztime / raw_text 等）

---

## 3. 配置与存储（CSV）

### 3.1 data/products.csv（必须）
字段（必须）：
- code：字符串读取（保留前导零）
- name
- kind：otc/etf/lof/qdii
- mode：fund_intraday（阶段1固定）
- ref：可选扩展参数（key=value;key=value）
- enabled：1/0

ref 约定（可选）：
- providers=fundgz,aniu（覆盖默认 provider 顺序）
- stale_rule=auto|strict（默认 auto）
- timeout_s=3（可选，默认 3 秒）

示例：
```csv
code,name,kind,mode,ref,enabled
519674,银河创新成长混合A,otc,fund_intraday,"providers=fundgz,aniu;stale_rule=auto",1
013275,富国中证煤炭指数(LOF)C,otc,fund_intraday,"providers=fundgz,aniu;stale_rule=auto",1
```
