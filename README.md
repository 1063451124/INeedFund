# 盘中涨跌看板（本地原型）

本项目是一个本地桌面原型，用于展示基金/ETF 盘中涨跌预估（仅供参考）。

## 特性
- Python + pywebview，本地 WebView 桌面应用
- 纯 HTML/JS 单页，无构建链
- CSV 配置（`data/products.csv`）
- 支持 fundgz 与 aniu 数据源，自动判定 stale 后降级

## 运行方式
1. 安装依赖：
   ```bash
   pip install pywebview
   ```
2. 启动：
   ```bash
   python app.py
   ```

## 配置
编辑 `data/products.csv`：
```csv
code,name,kind,mode,ref,enabled
519674,银河创新成长混合A,otc,fund_intraday,"providers=fundgz,aniu;stale_rule=auto",1
```

`ref` 字段支持：
- `providers=fundgz,aniu`：覆盖默认 provider 顺序
- `stale_rule=auto|strict`：stale 判定规则
- `timeout_s=3`：请求超时（秒）

## 参考实现说明
本项目数据层参考了仓库 [real-time-fund](https://github.com/hzm0321/real-time-fund) 的 fundgz 链路与解析思路（仅参考数据层，不搬运工程结构）。迁移点如下：
- fundgz 估值 JSONP 解析（`fetch_fundgz`、`extract_jsonp`）
- aniu 作为备援 provider（`fetch_aniu`、`parse_aniu_payload`）
- stale 判定逻辑（`is_stale` 中的“日期匹配 + 交易时段时间窗”规则）

## 免责声明
盘中估值/预估涨跌不等同于最终净值，仅供参考。
