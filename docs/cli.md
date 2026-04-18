# 命令行接口 （CLI) 使用说明

## 命令入口

推荐的命令入口：

```bash
qexec
```

为了向下兼容，也可以使用：

```bash
stockq
```

在开发环境下，你也可以直接通过 Python 模块执行：

```bash
PYTHONPATH=src python -m quant_execution_engine
```

请根据需要连接的券商安装相应的依赖包：

```bash
# 长桥证券
uv sync --group dev --extra cli --extra longport
# Alpaca
uv sync --group dev --extra cli --extra alpaca
# 盈透证券 （IBKR)
uv sync --group dev --extra cli --extra ibkr
# 安装所有券商依赖
uv sync --group dev --extra cli --extra full
```

如果未在配置文件 （`config/config.yaml`) 中显式指定券商后端 （`broker.backend`)，则在每次执行命令时都必须通过 `--broker` 参数进行指定。

## 子命令

### `config`

显示当前配置的券商后端、风控拦截机制、紧急停单状态以及相关凭证的摘要信息。

```bash
qexec config --broker longport-paper
qexec config --broker alpaca-paper
qexec config --broker ibkr-paper
```

对于长桥 （LongPort)，该命令还会详细列出各项核心凭证与参数（App Key / Secret / Access Token / Region / Overnight）的配置读取来源，方便你排查当前使用的是代码库本地的模拟盘配置，还是用户私有目录下的实盘配置。

对于盈透模拟盘 （`ibkr-paper`)，该命令会显示本地网关的主机地址、端口、客户 ID、账户 ID 及超时时间，并标明当前的运行环境设定（基于本地 IB Gateway 和 TWS API）。

### `evidence-maturity`

查看各券商接入代码的成熟度、最新的测试证据 （Evidence)、存在的功能缺口以及下一步的冒烟测试建议。

```bash
qexec evidence-maturity
qexec evidence-maturity --format json
```

该命令仅读取本地的测试证据文件 （`outputs/evidence/*.json`) 和券商的能力配置，不会向券商后台发起全量订单扫描，也不依赖任何外部数据库。

### `evidence-pack`

根据审计的运行编号 （`run_id`)，将某次执行产生的所有复查证据打包归档。

```bash
qexec evidence-pack <run-id>
qexec evidence-pack <run-id> --output-dir outputs/review
qexec evidence-pack <run-id> --operator-note "终端输出已人工复查"
```

打包结果默认输出到 `outputs/evidence-bundles/<run-id>` 目录下。系统会生成一份清单文件 （manifest)，记录审计日志、目标持仓文件、本地状态、冒烟测试证据以及操作员备注的包含、缺失或跳过状态；同时，安全机制会确保 `.env*` 等包含敏感信息的凭证文件不会被打包进去。

### `preflight`

在不改变券商实际账户状态的前提下，运行执行前的就绪性检查 （Preflight Check)。

```bash
qexec preflight --broker longport-paper
qexec preflight AAPL MSFT --broker longport-paper
qexec preflight --broker alpaca-paper
qexec preflight --broker ibkr-paper
```

当前的预检项包括：

- 券商接口能力矩阵
- 实盘执行保护机制状态
- 手动紧急停单状态
- 本地执行状态的紧急停单状态
- 账户解析是否正常
- 账户资产快照能否获取
- 行情、订单簿深度与成交量数据的可达性
- 检查已配置的依赖市场数据的风控项，判断是否会因为买卖盘或日成交量数据缺失而在正式执行时被降级跳过 （BYPASS)。

对于盈透模拟盘 （`ibkr-paper`)，这些检查能直接反映本地 IB Gateway 的连通性、账户解析情况和行情获取权限；如果发生失败，网关的网络连通性错误会直接体现在检查结果中。

### `account`

查询账户的资金与持仓概览。

```bash
qexec account --broker longport-paper
qexec account --broker longport-paper --format json
qexec account --broker longport-paper --funds
qexec account --broker longport-paper --positions
qexec account --broker alpaca-paper
qexec account --broker ibkr-paper
qexec account --account main
```

### `quote`

查询实时的市场行情。

```bash
qexec quote AAPL 700.HK --broker longport-paper
qexec quote AAPL --broker alpaca-paper
qexec quote AAPL --broker ibkr-paper
```

注意：当前盈透模拟盘 （`ibkr-paper`) 仅支持美股正股的基础行情；如果传入类似 `700.HK` 这类非美股代码，系统会直接报错拦截。

### `orders`

查看本地执行状态中已被系统跟踪的券商订单。

```bash
