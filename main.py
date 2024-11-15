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
    url = "https://cryptobubbles.net/backend/data/bubbles1000.usd.json"
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
    
class ExchangeHandler:
    def __init__(self):
        # 定义交易所显示顺序
        self.exchange_order = {
            'binance': 1,
            'bybit': 2,
            'okx': 3,
            'coinbase': 4,
            'kraken': 5,
            'kucoin': 6,
            'gateio': 7,
            'bitget': 8,
            'htx': 9,
            'bingx': 10,
            'bitmart': 11,
            'mexc': 12
        }

    def sort_exchanges(self, exchanges: List[str]) -> List[str]:
        """按预定义顺序排序交易所"""
        return sorted(exchanges, key=lambda x: self.exchange_order.get(x, float('inf')))

class TokenFilter:
    def __init__(self):
        # 定义主流交易所列表
        self.major_exchanges = {'bybit', 'binance', 'gateio', 'bitget'}
        # 最小价格变化阈值
        self.change_threshold = 5

    def check_exchange_requirement(self, token: Dict) -> bool:
        """检查交易所要求"""
        token_exchanges = set(token['symbols'].keys()) if 'symbols' in token else set()
        return bool(token_exchanges.intersection(self.major_exchanges))

    def check_price_change(self, token: Dict) -> bool:
        """检查价格变化要求"""
        if 'performance' in token and 'min5' in token['performance']:
            min5_change = token['performance']['min5']
            return abs(min5_change) > self.change_threshold
        return False

    def apply_filters(self, token: Dict) -> bool:
        """应用所有筛选条件"""
        # 所有筛选条件都必须满足
        filters = [
            self.check_exchange_requirement,
            self.check_price_change,
            # 在这里可以轻松添加新的筛选条件
        ]

        return all(f(token) for f in filters)


def filter_tokens_by_conditions(data: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """主筛选函数"""
    gainers = []
    losers = []

    if not data:
        return [], []

    # 创建筛选器实例
    token_filter = TokenFilter()

    for token in data:
        # 应用所有筛选条件
        if token_filter.apply_filters(token):
            token_info = {
                'name': token['name'],
                'symbol': token['symbol'],
                'rank': token['rank'],
                'price': token['price'],
                'marketcap': "{:,}".format(token['marketcap']),
                'volume': "{:,}".format(token['volume']),
                'performance': token['performance'],
                'exchanges': list(token['symbols'].keys()) if 'symbols' in token else []
            }

            # 根据涨跌幅分类
            min5_change = token['performance']['min5']
            if min5_change > 0:
                gainers.append(token_info)
            else:
                losers.append(token_info)

    # 排序
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
    if not (gainers or losers):   
        return ""                                                                                                                                                                                                                                                             # 1. 首先展示概览信息                                                                                                                message = []                                                                                                                         if gainers:                                                                                                                              gainer_summary = "🔺 涨幅>5%: " + ", ".join([f"{token['symbol']}(+{token['performance']['min5']:.2f}%)" for token in gainers])
        
    exchange_handler = ExchangeHandler()
    message = []
    if gainers:
        gainer_summary = "🔺 涨幅>5%: " + ", ".join([f"{token['symbol']}(+{token['performance']['min5']:.2f}%)" for token in gainers])
        message.append(gainer_summary)

    if losers:
        loser_summary = "🔻 跌幅>5%: " + ", ".join([f"{token['symbol']}({token['performance']['min5']:.2f}%)" for token in losers])
        message.append(loser_summary)

    message.append("\n" + "=" * 30 + "\n")  # 分隔线
     # 2. 然后是详细信息
    if gainers:
        message.append("🔺 详细信息:")
        for token in gainers:
            exchanges = token.get('exchanges', [])
            sorted_exchanges = exchange_handler.sort_exchanges(exchanges)
            message.extend([
                f"\n<b>{token['symbol']}</b> (#{token['rank']} {token['name']})",
                f"<b>价格:</b> {token['price']}",
                f"<b>市值:</b> {token['marketcap']}",
                f"<b>交易量:</b> {token['volume']}",
                f"<b>涨跌幅:</b> {format_performance(token['performance'])}",
                f"<b>交易所:</b> {', '.join(sorted_exchanges)}\n"
            ])

    if losers:
        message.append("\n🔻 详细信息:")
        for token in losers:
            exchanges = token.get('exchanges', [])
            sorted_exchanges = exchange_handler.sort_exchanges(exchanges)
            message.extend([
                f"\n<b>{token['symbol']}</b> (#{token['rank']} {token['name']})",
                f"<b>价格:</b> {token['price']}",
                f"<b>市值:</b> {token['marketcap']}",
                f"<b>交易量:</b> {token['volume']}",
                f"<b>涨跌幅:</b> {format_performance(token['performance'])}",
                f"<b>交易所:</b> {', '.join(sorted_exchanges)}\n"
            ])

    # 3. 最后是更新时间
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message.append(f"\n更新时间: {current_time}")

    return '\n'.join(message)

async def main():
    print("开始监控加密货币5分钟涨跌幅变化...")
    print("按 Ctrl+C 停止监控")

    try:
        while True:
            crypto_data = get_crypto_data()
            gainers, losers = filter_tokens_by_conditions(crypto_data)

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