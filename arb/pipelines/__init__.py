"""数据管道(Phase 2 接入)。

- normalize:多源 SKU 命名规范化(同名异写合并)
- fx:汇率换算(local → CNY)
- dedupe:同 SKU 同日多源去重(取最低价 + 多源交叉验证)
"""