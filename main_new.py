from config import ConfigLoader
import requests
import json
from typing import Dict, List, Tuple
import time
from datetime import datetime
import telegram
import asyncio
from config import ConfigLoader
import logging
from binance_futures_trader import USDTFuturesTraderManager

# 在程序开始处添加日志配置
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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
        self.major_exchanges = {'bybit', 'binance', 'okx', 'bitget'}
        # 最小价格变化阈值
        self.change_threshold_5min = 5
        self.change_threshold_1min = 2

    def check_exchange_requirement(self, token: Dict) -> bool:
        """检查交易所要求"""
        token_exchanges = set(token['symbols'].keys()) if 'symbols' in token else set()
        return bool(token_exchanges.intersection(self.major_exchanges))

    def check_price_change(self, token: Dict) -> bool:
        """检查价格变化要求"""
        if 'performance' in token and 'min5' in token['performance'] and 'min1' in token['performance']:
            min5_change = token['performance']['min5']
            min1_change = token['performance']['min1']
            return abs(min5_change) > self.change_threshold_5min or abs(min1_change) > self.change_threshold_1min
        return False

    def check_volume_change(self, token: Dict) -> bool:
        return token['volume'] > 5000000

    def apply_filters(self, token: Dict) -> bool:
        """应用所有筛选条件"""
        # 所有筛选条件都必须满足
        filters = [
            self.check_exchange_requirement,
            self.check_price_change,
            self.check_volume_change,
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

class TradingExecutor:
    def __init__(self, api_key, api_secret, leverage, usdt_amount, tp_percent, sl_percent, bot_token, chat_id):
        self.trader = USDTFuturesTraderManager(api_key, api_secret, bot_token, chat_id)
        self.leverage = leverage
        self.usdt_amount = usdt_amount
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
    
    def has_position(self, symbol: str) -> bool:
        """检查是否已有该交易对的持仓"""
        try:
            position = self.trader.get_position(symbol)
            if position and float(position.get('positionAmt', 0)) != 0:
                logging.info(f"{symbol} 已有持仓，数量: {position.get('positionAmt')}")
                return True
            return False
        except Exception as e:
            logging.error(f"检查持仓状态时出错: {e}")
            return False  # 出错时保守起见返回False，避免重复开仓
    
    def get_positions_info(self) -> str:
        """获取格式化的持仓信息"""
        try:
            positions = self.trader.get_all_positions()
            if not positions:
                return "暂无持仓"

            position_messages = []
            for position in positions:
                if float(position.get('positionAmt', 0)) != 0:
                    try:
                        symbol = position.get('symbol', 'Unknown')
                        position_amt = float(position.get('positionAmt', 0))
                        entry_price = float(position.get('entryPrice', 0))
                        unrealized_profit = float(position.get('unRealizedProfit', 0))
                        
                        side = "多" if position_amt > 0 else "空"
                        pnl_emoji = "📈" if unrealized_profit > 0 else "📉"
                        
                        position_msg = (
                            f"{symbol} ({side})\n"
                            f"数量: {abs(position_amt):.8f}\n"
                            f"开仓价: {entry_price:.8f}\n"
                            f"未实现盈亏: {pnl_emoji} {unrealized_profit:.3f} USDT"
                        )
                        position_messages.append(position_msg)
                    except (ValueError, TypeError) as e:
                        logging.error(f"处理持仓数据出错 {symbol}: {e}")
                        continue

            return "\n\n".join(position_messages) if position_messages else "暂无持仓"
        except Exception as e:
            logging.error(f"获取持仓信息失败: {e}")
            return "获取持仓信息失败"
        
    async def send_trading_message(self, message: str):
        """发送Telegram消息"""
        try:
            positions_info = self.get_positions_info()
            full_message = f"{message}\n\n📊 当前持仓信息:\n{positions_info}"
            
            await self.trader.send_telegram_message(
                message=full_message,
            )
            logging.info(f"已发送Telegram消息: {full_message}")
        except Exception as e:
            logging.error(f"发送Telegram消息失败: {e}")

    async def execute_long(self, token: Dict) -> None:
        """执行做多交易"""
        try:
            # 检查必要的字段是否存在
            if 'symbol' not in token:
                logging.error("Token missing symbol field")
                return
                
            symbol = f"{token['symbol']}USDT"
            
            # 首先检查是否已有持仓
            if self.has_position(symbol):
                logging.info(f"跳过 {symbol} 因为已有持仓")
                return

            # 检查交易对是否存在
            try:
                symbol_info = self.trader.get_symbol_info(symbol)
            except ValueError:
                logging.info(f"币安无此交易对: {symbol}")
                return
            except Exception as e:
                logging.error(f"检查交易对时发生错误 {symbol}: {e}")
                return

            logging.info(f"发现做多机会: {symbol}")
            
            # 设置杠杆
            self.trader.set_leverage(symbol, self.leverage)
            
            # 执行开仓
            response = self.trader.market_open_long_with_tp_sl(
                symbol=symbol,
                usdt_amount=self.usdt_amount,
                tp_percent=self.tp_percent,
                sl_percent=self.sl_percent
            )
            
            if response:
                message = (
                    f"🎯 开多 {symbol}\n"
                    f"金额: {self.usdt_amount} USDT\n"
                    f"杠杆: {self.leverage}X\n"
                    f"止盈: {self.tp_percent}%\n"
                    f"止损: {self.sl_percent}%"
                )
                logging.info(f"做多开仓成功: {response}")
                await self.send_trading_message(message)
            
        except Exception as e:
            logging.error(f"做多开仓失败 {symbol if 'symbol' in locals() else 'unknown'}: {e}")

    async def execute_short(self, token: Dict) -> None:
        """执行做空交易"""
        try:
            # 检查必要的字段是否存在
            if 'symbol' not in token:
                logging.error("Token missing symbol field")
                return
                
            symbol = f"{token['symbol']}USDT"
            
            # 首先检查是否已有持仓
            if self.has_position(symbol):
                logging.info(f"跳过 {symbol} 因为已有持仓")
                return

            # 检查交易对是否存在
            try:
                symbol_info = self.trader.get_symbol_info(symbol)
            except ValueError:
                logging.info(f"币安无此交易对: {symbol}")
                return
            except Exception as e:
                logging.error(f"检查交易对时发生错误 {symbol}: {e}")
                return

            logging.info(f"发现做空机会: {symbol}")
            
            # 设置杠杆
            self.trader.set_leverage(symbol, self.leverage)
            
            # 执行开仓
            response = self.trader.market_open_short_with_tp_sl(
                symbol=symbol,
                usdt_amount=self.usdt_amount,
                tp_percent=self.tp_percent,
                sl_percent=self.sl_percent
            )
            
            if response:
                message = (
                    f"🎯 开空 {symbol}\n"
                    f"金额: {self.usdt_amount} USDT\n"
                    f"杠杆: {self.leverage}X\n"
                    f"止盈: {self.tp_percent}%\n"
                    f"止损: {self.sl_percent}%"
                )
                logging.info(f"做空开仓成功: {response}")
                await self.send_trading_message(message)
            
        except Exception as e:
            logging.error(f"做空开仓失败 {symbol if 'symbol' in locals() else 'unknown'}: {e}")

def format_message(gainers: List[Dict], losers: List[Dict]) -> str:
    """格式化消息内容"""
    if not (gainers or losers):   
        return None
        
    exchange_handler = ExchangeHandler()
    message = []
    
    # 处理上涨的币种
    if gainers:
        gainer_summary = "🟢 " + ", ".join([
            f"{token['symbol']}(+{token['performance']['min5']:.2f}%)" 
            for token in gainers
        ])
        message.append(gainer_summary)

    # 处理下跌的币种
    if losers:
        loser_summary = "🔴 " + ", ".join([
            f"{token['symbol']}({token['performance']['min5']:.2f}%)" 
            for token in losers
        ])
        message.append(loser_summary)

    if len(message) > 0:
        message.append("\n" + "=" * 30 + "\n")
    
    # 详细信息部分
    if gainers:
        message.append("🟢 详细信息:")
        for token in gainers:
            message.extend(_format_token_details(token, exchange_handler))

    if losers:
        message.append('\n🔴 详细信息:')
        for token in losers:
            message.extend(_format_token_details(token, exchange_handler))

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message.append(f"\n更新时间: {current_time}")
    
    final_message = '\n'.join(message)
    logging.info(f"Telegram message: {final_message}")
    
    return final_message

def _format_token_details(token: Dict, exchange_handler: ExchangeHandler) -> List[str]:
    """格式化单个代币的详细信息"""
    exchanges = token.get('exchanges', [])
    sorted_exchanges = exchange_handler.sort_exchanges(exchanges)
    
    return [
        f'\n<b>{token["symbol"]}</b> (#{token["rank"]} {token["name"]})',
        f'<b>价格:</b> {token["price"]}',
        f'<b>市值:</b> {token["marketcap"]}',
        f'<b>交易量:</b> {token["volume"]}',
        f'<b>涨跌幅:</b> {format_performance(token["performance"])}',
        f'<b>交易所:</b> {", ".join(sorted_exchanges)}\n'
    ]

async def main():
    # 从.env加载配置
    config = ConfigLoader.load_from_env()
    TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
    TELEGRAM_CHAT_ID = config['TELEGRAM_CHAT_ID']
    TELEGRAM_CHAT_ID_SELF = config['TELEGRAM_CHAT_ID_SELF']

    trading_executor = TradingExecutor(api_key=config['ct_api_key'], 
                                     api_secret=config['ct_api_secret'], 
                                     leverage=4, 
                                     usdt_amount=500, 
                                     tp_percent=100.0, 
                                     sl_percent=5.0,
                                     bot_token=TELEGRAM_BOT_TOKEN,
                                     chat_id=TELEGRAM_CHAT_ID_SELF)
    bn_executor = TradingExecutor(api_key=config['api_key'], 
                                     api_secret=config['api_secret'], 
                                     leverage=10, 
                                     usdt_amount=200, 
                                     tp_percent=100.0, 
                                     sl_percent=5.0,
                                     bot_token=TELEGRAM_BOT_TOKEN,
                                     chat_id=TELEGRAM_CHAT_ID_SELF)
    auto_long = True
    auto_short = False
    
    try:
        # trading_executor.trader.start_ws_monitor()
        bn_executor.trader.start_ws_monitor()
        # await trading_executor.trader.send_telegram_message("🤖 交易机器人启动\n监控开始！")
        await bn_executor.trader.send_telegram_message("🤖 交易机器人启动\n监控开始！")
        # message_processor = asyncio.create_task(trading_executor.trader.process_message_queue())
        message_processor_1 = asyncio.create_task(bn_executor.trader.process_message_queue())
        
        logging.info("开始监控")
        while True:
            try:
                start_time = time.time()
                
                crypto_data = get_crypto_data()
                gainers, losers = filter_tokens_by_conditions(crypto_data)

                # 执行交易
                if auto_long:
                    for token in gainers:
                    #    await trading_executor.execute_long(token)
                        await bn_executor.execute_long(token)
                        
                if auto_short:
                    for token in losers:
                    #     await trading_executor.execute_short(token)
                        await bn_executor.execute_short(token)

                # 发送市场监控消息到群组
                message = format_message(gainers, losers)
                if message:
                    await send_telegram_message(message)

                execution_time = time.time() - start_time
                
                logging.info(f"本次执行耗时: {execution_time:.2f}秒")
                await asyncio.sleep(60)
                
            except KeyboardInterrupt:
                print("\n程序已停止")
                break
            except Exception as e:
                logging.error(f"发生错误: {e}")
                await asyncio.sleep(60)
                
    except KeyboardInterrupt:
        logging.info("程序已手动停止")
    except Exception as e:
        logging.error(f"程序发生错误: {e}")
        logging.exception(e)
    finally:
        #if trading_executor.trader.ws_client:
        #    trading_executor.trader.ws_client.stop()
        if bn_executor.trader.ws_client:
            bn_executor.trader.ws_client.stop()

if __name__ == "__main__":
    # 安装必要的包
    # pip install python-telegram-bot requests

    # 运行异步主函数
    asyncio.run(main())