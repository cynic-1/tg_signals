from config import ConfigLoader
import requests
import json
from typing import Dict, List, Tuple
import time
from datetime import datetime
import telegram
import asyncio
from config import ConfigLoader

# 从.env加载配置
config = ConfigLoader.load_from_env()
TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = config['TELEGRAM_CHAT_ID']


async def send_telegram_message(message: str):
    """发送消息到Telegram"""
    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        # Telegram消息有长度限制，如果太长需要分段发送
        max_length = 4096

        # 如果消息长度超过限制，分段发送
        for i in range(0, len(message), max_length):
            chunk = message[i:i + max_length]
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=chunk,
                parse_mode='HTML'  # 启用HTML格式
            )
    except Exception as e:
        print(f"发送Telegram消息时出错: {e}")


def get_crypto_data() -> List[Dict]:
    url = "https://cryptobubbles.net/backend/data/bubbles1000.btc.json"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        return []


def filter_tokens_by_5min_change(data: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    gainers = []
    losers = []

    if not data:
        return [], []

    for token in data:
        if 'performance' in token and 'min5' in token['performance']:
            min5_change = token['performance']['min5']

            if abs(min5_change) > 3:
                token_info = {
                    'name': token['name'],
                    'symbol': token['symbol'],
                    'rank': token['rank'],
                    'price': token['price'],
                    'performance': token['performance'],
                    'exchanges': list(token['symbols'].keys()) if 'symbols' in token else []
                }

                if min5_change > 0:
                    gainers.append(token_info)
                else:
                    losers.append(token_info)

    gainers.sort(key=lambda x: x['performance']['min5'], reverse=True)
    losers.sort(key=lambda x: x['performance']['min5'])

    return gainers, losers


def format_performance(perf: Dict) -> str:
    periods = [
        ('min1', '1分钟'),
        ('min5', '5分钟'),
        ('min15', '15分钟'),
        ('hour', '1小时'),
        ('day', '24小时'),
        ('week', '7天'),
        ('month', '30天'),
        ('year', '1年')
    ]

    perf_str = []
    for period_key, period_name in periods:
        if period_key in perf and perf[period_key] is not None:
            value = perf[period_key]
            try:
                value = float(value)
                sign = '+' if value > 0 else ''
                perf_str.append(f"{period_name}: {sign}{value:.2f}%")
            except (ValueError, TypeError):
                perf_str.append(f"{period_name}: N/A")
        else:
            perf_str.append(f"{period_name}: N/A")

    return ' | '.join(perf_str)


def format_message(gainers: List[Dict], losers: List[Dict]) -> str:
    """格式化要发送到Telegram的消息"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = [f"<b>数据更新时间: {current_time}</b>\n"]

    if gainers or losers:
        if gainers:
            message.append("\n🔺 <b>5分钟涨幅超过3%的代币:</b>")
            for token in gainers:
                message.extend([
                    f"\n<b>代币:</b> #{token['rank']} {token['name']} ({token['symbol']})",
                    f"<b>价格:</b> {token['price']}",
                    f"<b>涨跌幅:</b> {format_performance(token['performance'])}",
                    f"<b>交易所:</b> {', '.join(token['exchanges'])}\n"
                ])

        if losers:
            message.append("\n🔻 <b>5分钟跌幅超过3%的代币:</b>")
            for token in losers:
                message.extend([
                    f"\n<b>代币:</b> #{token['rank']} {token['name']} ({token['symbol']})",
                    f"<b>价格:</b> {token['price']}",
                    f"<b>涨跌幅:</b> {format_performance(token['performance'])}",
                    f"<b>交易所:</b> {', '.join(token['exchanges'])}\n"
                ])
    else:
        message.append("\n没有找到5分钟涨跌幅超过3%的代币")

    return '\n'.join(message)


async def main():
    print("开始监控加密货币5分钟涨跌幅变化...")
    print("按 Ctrl+C 停止监控")

    try:
        while True:
            crypto_data = get_crypto_data()
            gainers, losers = filter_tokens_by_5min_change(crypto_data)

            # 格式化消息并发送到Telegram
            message = format_message(gainers, losers)
            await send_telegram_message(message)

            # 控制台也打印消息
            print(message)

            # 倒计时
            for i in range(60, 0, -1):
                print(f"\r下次更新倒计时: {i}秒", end='', flush=True)
                await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n已停止监控")
        await send_telegram_message("🔄 监控已停止")
    except Exception as e:
        error_message = f"\n发生错误: {e}"
        print(error_message)
        await send_telegram_message(f"❌ {error_message}")


if __name__ == "__main__":
    # 安装必要的包
    # pip install python-telegram-bot requests

    # 运行异步主函数
    asyncio.run(main())