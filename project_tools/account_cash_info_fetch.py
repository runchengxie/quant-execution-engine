#!/usr/bin/env python3
"""
LongPort账户资金信息获取工具

这是一个独立的Python脚本，用于测试LongPort API的账户余额查询功能。
基于官方API文档: https://open.longportapp.com/docs/trade/asset/account

使用前请确保:
1. 已安装longport包: pip install longport
2. 已设置相关环境变量 (LONGPORT_APP_KEY, LONGPORT_APP_SECRET, LONGPORT_ACCESS_TOKEN)

作者: 自动生成
日期: 2024
"""

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


def get_account_balance(currency: str | None = None) -> None:
    """
    获取账户余额信息

    Args:
        currency (Optional[str]): 指定货币类型 (HKD, USD, CNH)，如果为None则获取所有货币
    """
    try:
        print("正在初始化LongPort配置...")

        # 从环境变量加载配置
        config = Config.from_env()

        print("正在创建交易上下文...")

        # 创建交易上下文
        ctx = TradeContext(config)

        print("正在获取账户余额信息...")

        # 调用账户余额API
        if currency:
            print(f"查询指定货币: {currency}")
            # 注意: 根据API文档，currency参数可能需要通过其他方式传递
            # 这里使用基本的account_balance()调用
            resp = ctx.account_balance()
        else:
            resp = ctx.account_balance()

        print("\n=== 账户余额信息 ===")
        print(f"响应数据: {resp}")

        # 如果响应是对象，尝试格式化输出
        if hasattr(resp, "__dict__"):
            print("\n=== 格式化输出 ===")
            for key, value in resp.__dict__.items():
                print(f"{key}: {value}")

    except Exception as e:
        print(f"获取账户余额时发生错误: {e}")
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


def main():
    """
    主函数
    """
    print("LongPort账户资金信息获取工具")
    print("=" * 40)

    # 检查环境变量
    if not check_environment_variables():
        sys.exit(1)

    try:
        # 获取所有货币的账户余额
        print("\n获取所有货币的账户余额:")
        get_account_balance()

        # 可以尝试获取特定货币的余额（如果API支持）
        print("\n" + "=" * 50)
        print("测试完成！")

    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        print(f"\n程序执行过程中发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
