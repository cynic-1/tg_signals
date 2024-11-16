import logging
from binance.um_futures import UMFutures  # 改用 UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
import time
from typing import Dict, Set
from decimal import Decimal
from config import ConfigLoader
import json
import asyncio
from functools import partial
import telegram

config = ConfigLoader.load_from_env()
API_KEY = config['api_key']
API_SECRET = config['api_secret']
TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID_SELF = config['TELEGRAM_CHAT_ID_SELF']

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class FuturesTradeManager:
    def __init__(self, api_key: str, api_secret: str):
        self.client = UMFutures(key=api_key, secret=api_secret)  # 使用 UMFutures
        self.ws_client = None
        self.active_positions: Dict[str, Dict] = {}
        self.bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.monitored_symbols: Set[str] = set()
        logging.getLogger('websockets').setLevel(logging.DEBUG)

    def send_telegram_message(self, message: str):
            """发送消息到Telegram"""
            try:
                max_length = 4096
                for i in range(0, len(message), max_length):
                    chunk = message[i:i + max_length]
                    self.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID_SELF,
                        text=chunk,
                        parse_mode='HTML'
                    )
            except Exception as e:
                logging.error(f"发送Telegram消息时出错: {e}")

    def format_position_info(self) -> str:
        """格式化持仓信息"""
        message = "当前持仓情况:\n"
        for symbol, position in self.active_positions.items():
            message += f"\n{symbol}:\n"
            message += f"持仓量: {position['amount']}\n"
            message += f"入场价: {position['entry_price']}\n"
            message += f"当前止损: {position['current_stop_loss']}\n"
            message += f"未实现盈亏: {position['unrealized_profit']}\n"
            message += "------------------------"
        return message

    def get_active_positions(self) -> Dict[str, Dict]:
            """获取所有活跃持仓"""
            try:
                account_info = self.client.account()
                positions = account_info.get('positions', [])
                
                active_positions = {}
                for position in positions:
                    amount = Decimal(position['positionAmt'])
                    if amount != 0:  # 只关注持仓量不为0的仓位
                        symbol = position['symbol']
                        # 计算入场价格（通过名义价值和持仓量）
                        notional = Decimal(position['notional'])
                        entry_price = abs(notional / amount) if amount != 0 else Decimal('0')
                        
                        active_positions[symbol] = {
                            'amount': amount,
                            'entry_price': entry_price,
                            'current_stop_loss': entry_price * Decimal('0.95'),  # 初始止损设为开仓价的95%
                            'notional': notional,
                            'unrealized_profit': Decimal(position['unrealizedProfit'])
                        }
                        logging.info(f"检测到持仓 {symbol}: 数量={amount}, 入场价={entry_price}, "
                                f"未实现盈亏={position['unrealizedProfit']}")
                return active_positions
            except Exception as e:
                logging.error(f"获取持仓信息失败: {str(e)}")
                return {}

    def update_websocket_subscriptions(self):
        """更新websocket订阅"""
        current_positions = set(self.active_positions.keys())
        
        # 需要新增订阅的交易对
        new_symbols = current_positions - self.monitored_symbols
        # 需要取消订阅的交易对
        remove_symbols = self.monitored_symbols - current_positions

        if self.ws_client:
            try:
                # 取消不再持仓的交易对订阅
                for symbol in remove_symbols:
                    stream_name = f"{symbol.lower()}@markPrice@1s"
                    self.ws_client.unsubscribe(stream=[stream_name])
                    logging.info(f"取消订阅 {symbol} 的标记价格推送")

                # 订阅新持仓的交易对
                if new_symbols:
                    streams = [f"{symbol.lower()}@markPrice@1s" for symbol in new_symbols]
                    self.ws_client.subscribe(stream=streams)
                    logging.info(f"订阅标记价格推送streams: {streams}")

                self.monitored_symbols = current_positions
                
            except Exception as e:
                logging.error(f"更新WebSocket订阅失败: {str(e)}")
                logging.exception(e)

    def start_monitoring(self):
        """开始监控持仓"""
        try:
            def on_open(ws):
                logging.info("WebSocket连接已建立")

            def on_close(ws, close_status_code, close_msg):
                logging.info(f"WebSocket连接已关闭: {close_status_code} - {close_msg}")

            def on_error(ws, error):
                logging.error(f"WebSocket错误: {error}")

            # 初始化websocket客户端，使用组合流
            self.ws_client = UMFuturesWebsocketClient(
                on_message=self.handle_price_update,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error,
                is_combined=True
            )

            # 先获取初始持仓
            new_positions = self.get_active_positions()
            self.active_positions = new_positions
            # 立即进行第一次订阅
            self.update_websocket_subscriptions()
            logging.info(f"初始活跃持仓: {list(self.active_positions.keys())}")

            while True:
                # 获取最新持仓情况
                new_positions = self.get_active_positions()
                
                # 检查持仓是否有变化
                if new_positions != self.active_positions:
                    self.active_positions = new_positions
                    self.update_websocket_subscriptions()
                    logging.info(f"持仓已更新: {list(self.active_positions.keys())}")

                time.sleep(60)  # 每分钟检查一次持仓情况

        except Exception as e:
            logging.error(f"监控过程发生错误: {str(e)}")
            logging.exception(e)
        finally:
            if self.ws_client:
                self.ws_client.stop()

    def handle_price_update(self, _, message):
        """处理实时价格更新"""
        try:
            logging.debug(f"收到原始消息: {message}")

            # 处理订阅确认消息
            if 'result' in message:
                logging.debug("收到订阅确认消息")
                return
            
                # 如果消息是字符串，尝试解析为字典
            if isinstance(message, str):
                try:
                    message = json.loads(message)
                except json.JSONDecodeError as e:
                    logging.debug(f"无法解析JSON消息: {e}")
                    return
            
            # 处理标记价格推送
            if 'stream' in message and 'data' in message:
                data = message['data']
                if data['e'] == 'markPriceUpdate':
                    symbol = data['s']
                    current_price = Decimal(data['p'])  # 标记价格
                    
                    if symbol in self.active_positions:
                        position = self.active_positions[symbol]
                        entry_price = position['entry_price']
                        
                        # 计算价格变动百分比
                        price_change_percent = ((current_price - entry_price) / entry_price) * Decimal('100')
                        
                        logging.info(f"{symbol} 当前标记价格: {current_price}, 入场价: {entry_price}, "
                                f"价格变动: {price_change_percent}%")
                        
                         # 只有在价格上涨时才考虑调整止损
                        if price_change_percent >= Decimal('10'):  # 至少要涨10%才考虑调整止损
                            new_stop_loss = self.calculate_new_stop_loss(price_change_percent, entry_price)
                            
                            # 只有当新的止损价高于当前止损价时才更新
                            if new_stop_loss > position['current_stop_loss']:
                                self.update_stop_loss_order(symbol, new_stop_loss)
                                position['current_stop_loss'] = new_stop_loss

                                # 发送Telegram通知
                                message = (
                                    f"🔄 止损价格调整通知\n\n"
                                    f"交易对: {symbol}\n"
                                    f"当前价格: {current_price}\n"
                                    f"价格涨幅: {price_change_percent}%\n"
                                    f"新止损价: {new_stop_loss}\n\n"
                                    f"{self.format_position_info()}"
                                )
                                self.send_telegram_message(message)

                                logging.info(f"{symbol} 更新止损价到: {new_stop_loss}")

        except Exception as e:
            logging.error(f"处理价格更新失败: {str(e)}")
            logging.debug(f"错误消息内容: {message}")
            logging.exception(e) 

    def calculate_new_stop_loss(self, price_change_percent: Decimal, entry_price: Decimal) -> Decimal:
        """
        计算新的止损价格
        每当价格上涨10%，止损价上调5%
        例如：
        - 涨幅10%-19.99%，止损为开仓价的105%
        - 涨幅20%-29.99%，止损为开仓价的110%
        - 涨幅30%-39.99%，止损为开仓价的115%
        以此类推
        """
        try:
            # 计算价格上涨了多少个10%
            rise_times = int(price_change_percent // Decimal('10'))
            
            # 相应地止损价上调多少个5%
            stop_loss_percent = Decimal('100') + (rise_times * Decimal('5'))
            
            # 计算新的止损价格
            new_stop_loss = entry_price * (stop_loss_percent / Decimal('100'))
            
            logging.info(f"价格涨幅: {price_change_percent}%, 上涨{rise_times}个10%, "
                        f"止损调整为开仓价的{stop_loss_percent}%, "
                        f"新止损价: {new_stop_loss}")
            
            return new_stop_loss
            
        except Exception as e:
            logging.error(f"计算止损价格时发生错误: {str(e)}")
            return entry_price * Decimal('0.95')  # 出错时返回默认止损价    

    def start_monitoring(self):
            """开始监控持仓"""
            try:
                self.ws_client = UMFuturesWebsocketClient(
                    on_message=self.handle_price_update,
                    is_combined=True
                )

                new_positions = self.get_active_positions()
                self.active_positions = new_positions
                self.update_websocket_subscriptions()
                
                # 发送初始持仓信息到Telegram
                initial_message = "🔵 开始监控持仓\n\n" + self.format_position_info()
                self.send_telegram_message(initial_message)
                
                logging.info(f"初始活跃持仓: {list(self.active_positions.keys())}")

                while True:
                    new_positions = self.get_active_positions()
                    
                    if new_positions != self.active_positions:
                        self.active_positions = new_positions
                        self.update_websocket_subscriptions()
                        
                        # 发送持仓更新信息到Telegram
                        update_message = "🔄 持仓发生变化\n\n" + self.format_position_info()
                        self.send_telegram_message(update_message)
                        
                        logging.info(f"持仓已更新: {list(self.active_positions.keys())}")

                    time.sleep(60)

            except Exception as e:
                logging.error(f"监控过程发生错误: {str(e)}")
                logging.exception(e)
            finally:
                if self.ws_client:
                    self.ws_client.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    manager = FuturesTradeManager(API_KEY, API_SECRET)
    manager.start_monitoring()