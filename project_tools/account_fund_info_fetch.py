#!/usr/bin/env python3
"""
基金持仓信息获取脚本

该脚本使用LongPort OpenAPI获取账户基金持仓信息，包括：
- 账户类型
- 基金ISIN代码
- 基金名称
- 持有份额
- 当前净值
- 成本净值
- 货币信息
- 净值日期

使用方法：
1. 确保已安装longport库：pip install longport
2. 配置环境变量或.env文件：
   - LONGPORT_APP_KEY
   - LONGPORT_APP_SECRET
   - LONGPORT_ACCESS_TOKEN
   - LONGPORT_HTTP_URL (可选)
3. 运行脚本：python account_fund_info_fetch.py

可选参数：
- 可以指定特定的基金ISIN代码进行查询
"""

import os
import sys
from datetime import datetime

try:
    from longport.openapi import Config, OpenApiException, TradeContext
except ImportError:
    print("错误：未找到longport库，请先安装：pip install longport")
    sys.exit(1)


def format_timestamp(timestamp_str: str) -> str:
    """
    格式化时间戳为可读格式

    Args:
        timestamp_str: 时间戳字符串

    Returns:
        格式化后的日期字符串
    """
    try:
        if timestamp_str and timestamp_str != "0":
            timestamp = int(timestamp_str)
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return "未知"
    except (ValueError, OSError):
        return timestamp_str


def fetch_fund_positions(symbols: list[str] | None = None) -> None:
    """
    获取基金持仓信息

    Args:
        symbols: 可选的基金ISIN代码列表，如果不提供则获取所有持仓
    """
    try:
        # 检查环境变量
        required_env_vars = [
            "LONGPORT_APP_KEY",
            "LONGPORT_APP_SECRET",
            "LONGPORT_ACCESS_TOKEN",
        ]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if missing_vars:
            print("错误：缺少以下环境变量：")
            for var in missing_vars:
                print(f"  - {var}")
            print("\n请在.env文件中配置这些变量，或设置系统环境变量。")
            print("\n配置说明：")
            print("1. 在项目根目录创建.env文件")
            print("2. 添加以下内容：")
            print("   LONGPORT_APP_KEY=your_app_key")
            print("   LONGPORT_APP_SECRET=your_app_secret")
            print("   LONGPORT_ACCESS_TOKEN=your_access_token")
            print("   LONGPORT_HTTP_URL=https://openapi.longportapp.com (可选)")
            return

        # 从环境变量创建配置
        print("正在连接LongPort API...")
        config = Config.from_env()

        # 创建交易上下文
        ctx = TradeContext(config)

        # 获取基金持仓信息
        print("正在获取基金持仓信息...")
        if symbols:
            print(f"查询指定基金：{', '.join(symbols)}")
            resp = ctx.fund_positions(symbols)
        else:
            print("查询所有基金持仓")
            resp = ctx.fund_positions()

        # 解析并显示结果
        if not resp or not hasattr(resp, "list") or not resp.list:
            print("\n未找到基金持仓信息")
            return

        print("\n" + "=" * 80)
        print("基金持仓信息")
        print("=" * 80)

        total_accounts = len(resp.list)
        total_funds = 0

        for account_idx, account in enumerate(resp.list, 1):
            print(f"\n账户 {account_idx}/{total_accounts}:")
            print(f"  账户类型: {account.account_channel}")

            if not account.fund_info:
                print("  该账户无基金持仓")
                continue

            fund_count = len(account.fund_info)
            total_funds += fund_count
            print(f"  基金数量: {fund_count}")
            print("  " + "-" * 70)

            for fund_idx, fund in enumerate(account.fund_info, 1):
                print(f"\n  基金 {fund_idx}/{fund_count}:")
                print(f"    ISIN代码: {fund.symbol}")
                print(f"    基金名称: {fund.symbol_name}")
                print(f"    货币: {fund.currency}")
                print(f"    持有份额: {fund.holding_units}")
                print(f"    当前净值: {fund.current_net_asset_value}")
                print(f"    成本净值: {fund.cost_net_asset_value}")

                # 格式化净值日期
                nav_date = format_timestamp(fund.net_asset_value_day)
                print(f"    净值日期: {nav_date}")

                # 计算盈亏（如果数据可用）
                try:
                    current_value = (
                        float(fund.current_net_asset_value)
                        if fund.current_net_asset_value
                        else 0
                    )
                    cost_value = (
                        float(fund.cost_net_asset_value)
                        if fund.cost_net_asset_value
                        else 0
                    )
                    holding_units = (
                        float(fund.holding_units) if fund.holding_units else 0
                    )

                    if current_value > 0 and cost_value > 0 and holding_units > 0:
                        current_total = current_value * holding_units
                        cost_total = cost_value * holding_units
                        profit_loss = current_total - cost_total
                        profit_loss_pct = (
                            (profit_loss / cost_total) * 100 if cost_total > 0 else 0
                        )

                        print(f"    当前市值: {current_total:.2f} {fund.currency}")
                        print(f"    成本总额: {cost_total:.2f} {fund.currency}")
                        print(f"    盈亏金额: {profit_loss:+.2f} {fund.currency}")
                        print(f"    盈亏比例: {profit_loss_pct:+.2f}%")
                except (ValueError, TypeError, ZeroDivisionError):
                    print("    盈亏计算: 数据不足")

        print("\n" + "=" * 80)
        print(f"汇总信息: 共 {total_accounts} 个账户，{total_funds} 只基金")
        print("=" * 80)

    except OpenApiException as e:
        print("\nLongPort API错误：")
        print(f"错误代码: {e.code}")
        print(f"错误信息: {e.message}")
        print("\n可能的解决方案：")
        print("1. 检查API密钥是否正确")
        print("2. 检查网络连接")
        print("3. 确认账户权限")

    except Exception as e:
        print(f"\n程序执行错误: {str(e)}")
        print("\n请检查：")
        print("1. 网络连接是否正常")
        print("2. 环境变量配置是否正确")
        print("3. longport库是否正确安装")


def main():
    """
    主函数
    """
    print("LongPort 基金持仓信息获取工具")
    print("=" * 50)

    # 可以在这里指定特定的基金ISIN代码
    # 例如：symbols = ["HK0000447943", "HK0000676327"]
    symbols = None  # 获取所有基金持仓

    # 如果需要查询特定基金，可以取消注释下面的代码
    # symbols = ["HK0000447943"]  # 示例：查询特定基金

    fetch_fund_positions(symbols)

    print("\n程序执行完成。")


if __name__ == "__main__":
    main()
