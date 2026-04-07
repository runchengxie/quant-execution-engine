#!/usr/bin/env python3
"""
LongPort账户股票持仓信息获取工具

这是一个独立的Python脚本，用于测试LongPort API的股票持仓查询功能。
基于官方API文档: https://open.longportapp.com/docs/trade/asset/stock

使用前请确保:
1. 已安装longport包: pip install longport
2. 已设置相关环境变量 (LONGPORT_APP_KEY, LONGPORT_APP_SECRET, LONGPORT_ACCESS_TOKEN)

作者: 自动生成
日期: 2024
"""

import json
import os
import sys

try:
    from longport.openapi import Config, TradeContext
except ImportError as e:
    print("错误: 无法导入longport模块。请先安装: pip install longport")
    print(f"详细错误信息: {e}")
    sys.exit(1)


def check_environment_variables() -> bool:
    """
    检查必要的环境变量是否已设置

    Returns:
        bool: 如果所有必要的环境变量都已设置则返回True，否则返回False
    """
    required_vars = ["LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN"]

    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        print("错误: 以下环境变量未设置:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\n请设置这些环境变量后重试。")
        return False

    return True


def format_stock_position(stock_info: dict) -> str:
    """
    格式化单个股票持仓信息

    Args:
        stock_info (dict): 股票信息字典

    Returns:
        str: 格式化后的股票信息字符串
    """
    symbol = stock_info.get("symbol", "N/A")
    symbol_name = stock_info.get("symbol_name", "N/A")
    quantity = stock_info.get("quantity", "0")
    available_quantity = stock_info.get("available_quantity", "0")
    currency = stock_info.get("currency", "N/A")
    market = stock_info.get("market", "N/A")
    cost_price = stock_info.get("cost_price", "0")
    init_quantity = stock_info.get("init_quantity", "0")

    return f"""
    股票代码: {symbol}
    股票名称: {symbol_name}
    市场: {market}
    货币: {currency}
    持股数量: {quantity}
    可用数量: {available_quantity}
    成本价格: {cost_price}
    初始数量: {init_quantity}
    """


def get_stock_positions(symbols: list[str] | None = None) -> None:
    """
    获取股票持仓信息

    Args:
        symbols (Optional[List[str]]): 指定股票代码列表，格式为 ticker.region (如 AAPL.US)
                                     如果为None则获取所有持仓
    """
    try:
        print("正在初始化LongPort配置...")

        # 从环境变量加载配置
        config = Config.from_env()

        print("正在创建交易上下文...")

        # 创建交易上下文
        ctx = TradeContext(config)

        print("正在获取股票持仓信息...")

        # 调用股票持仓API
        if symbols:
            print(f"查询指定股票: {', '.join(symbols)}")
            # 注意: 根据API文档，symbols参数可能需要通过其他方式传递
            # 这里使用基本的stock_positions()调用
            resp = ctx.stock_positions()
        else:
            resp = ctx.stock_positions()

        print("\n=== 股票持仓信息 ===")

        # 如果响应是对象，尝试访问其属性
        if hasattr(resp, "__dict__"):
            print("\n=== 原始响应数据 ===")
            print(f"响应对象: {resp}")

            # 尝试访问常见的属性
            for attr in ["list", "data", "accounts"]:
                if hasattr(resp, attr):
                    data = getattr(resp, attr)
                    print(f"\n找到属性 '{attr}': {data}")

                    # 如果是列表，遍历处理
                    if isinstance(data, list):
                        process_stock_list(data)
                    break
        else:
            # 如果是字典或其他类型
            print(f"响应数据类型: {type(resp)}")
            print(f"响应内容: {resp}")

            # 尝试按照API文档的响应格式处理
            if isinstance(resp, dict):
                if "list" in resp:
                    process_stock_list(resp["list"])
                elif "data" in resp and "list" in resp["data"]:
                    process_stock_list(resp["data"]["list"])
                else:
                    print("\n无法识别的响应格式，原始数据:")
                    print(json.dumps(resp, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"获取股票持仓时发生错误: {e}")
        print(f"错误类型: {type(e).__name__}")

        # 提供一些常见错误的解决建议
        if "authentication" in str(e).lower() or "unauthorized" in str(e).lower():
            print("\n建议检查:")
            print("1. 环境变量中的API密钥是否正确")
            print("2. Access Token是否有效且未过期")
            print("3. 账户是否有相应的API访问权限")
        elif "network" in str(e).lower() or "connection" in str(e).lower():
            print("\n建议检查:")
            print("1. 网络连接是否正常")
            print("2. 是否需要代理设置")
            print("3. 防火墙是否阻止了连接")
        elif "permission" in str(e).lower() or "forbidden" in str(e).lower():
            print("\n建议检查:")
            print("1. 账户是否开通了股票交易权限")
            print("2. API权限是否包含股票持仓查询")
            print("3. 是否在交易时间内查询")


def process_stock_list(stock_list: list[dict]) -> None:
    """
    处理股票持仓列表

    Args:
        stock_list (List[dict]): 股票持仓列表
    """
    if not stock_list:
        print("\n当前没有股票持仓")
        return

    total_accounts = len(stock_list)
    print(f"\n找到 {total_accounts} 个账户的持仓信息:")

    for i, account in enumerate(stock_list, 1):
        account_channel = account.get("account_channel", "Unknown")
        stock_info_list = account.get("stock_info", [])

        print(f"\n--- 账户 {i}: {account_channel} ---")

        if not stock_info_list:
            print("该账户暂无股票持仓")
            continue

        print(f"持仓股票数量: {len(stock_info_list)}")

        total_value = 0
        for j, stock_info in enumerate(stock_info_list, 1):
            print(f"\n第 {j} 只股票:")
            print(format_stock_position(stock_info))

            # 尝试计算总价值（如果有成本价格和数量）
            try:
                cost_price = float(stock_info.get("cost_price", 0))
                quantity = float(stock_info.get("quantity", 0))
                stock_value = cost_price * quantity
                total_value += stock_value
                print(
                    f"    持仓价值: {stock_value:.2f} {stock_info.get('currency', '')}"
                )
            except (ValueError, TypeError):
                print("    持仓价值: 无法计算")

        if total_value > 0:
            print(f"\n账户 {account_channel} 总持仓价值: {total_value:.2f}")


def main():
    """
    主函数
    """
    print("LongPort账户股票持仓信息获取工具")
    print("=" * 40)

    # 检查环境变量
    if not check_environment_variables():
        sys.exit(1)

    try:
        # 获取所有股票持仓
        print("\n获取所有股票持仓信息:")
        get_stock_positions()

        # 可以尝试获取特定股票的持仓（如果API支持）
        # print("\n获取特定股票持仓信息:")
        # get_stock_positions(['AAPL.US', '700.HK'])

        print("\n" + "=" * 50)
        print("测试完成！")

    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        print(f"\n程序执行过程中发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
