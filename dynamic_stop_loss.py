import time
import logging
from typing import Dict
from decimal import Decimal
from config import ConfigLoader
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
import asyncio
import telegram

config = ConfigLoader.load_from_env()
TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID_SELF = config['TELEGRAM_CHAT_ID_SELF']
API_KEY = config['api_key']
API_SECRET = config['api_secret']


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class DynamicStopLossManager:
    def __init__(self):
        self.client = UMFutures(
            key=API_KEY,
            secret=API_SECRET
        )
        self.ws_client = None
        self.positions = {}  # 存储持仓信息
        self.stop_loss_levels = {}  # 存储止损等级
        self.running = True

    def message_handler(self, _, message):
        """处理WebSocket消息
        第一个参数是websocket client实例
        第二个参数是消息内容
        """
        try:
            if isinstance(message, dict):
                if 'e' not in message:  # 忽略非行情消息
                    return
                    
                symbol = message['s']
                if symbol not in self.positions:
                    return
                    
                current_price = float(message['c'])  # 最新价格
                self.check_and_update_stop_loss(symbol, current_price)
            else:
                logging.debug(f"收到非字典消息: {message}")
                
        except Exception as e:
            logging.error(f"处理WebSocket消息失败: {e}")

    async def send_telegram_message(self, message: str):
        """发送Telegram消息"""
        try:
            bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID_SELF,
                text=message,
                parse_mode='HTML'
            )
            logging.info(f"已发送Telegram消息: {message}")
        except Exception as e:
            logging.error(f"发送Telegram消息失败: {e}")

    def update_positions(self):
        """更新持仓信息"""
        try:
            positions = self.client.get_position_risk()
            new_positions = {}
            
            for position in positions:
                amt = float(position['positionAmt'])
                if amt != 0:
                    symbol = position['symbol']
                    new_positions[symbol] = {
                        'entry_price': float(position['entryPrice']),
                        'position_amt': amt,
                        'symbol': symbol
                    }
                    
                    if symbol not in self.stop_loss_levels:
                        self.stop_loss_levels[symbol] = 0

            # 检查是否有新的或已关闭的持仓
            old_symbols = set(self.positions.keys())
            new_symbols = set(new_positions.keys())
            
            self.positions = new_positions
            return new_symbols, old_symbols - new_symbols
            
        except Exception as e:
            logging.error(f"更新持仓信息失败: {e}")
            return set(), set()

    def check_and_update_stop_loss(self, symbol: str, current_price: float):
        """检查并更新止损"""
        try:
            if symbol not in self.positions:
                return
                
            position = self.positions[symbol]
            entry_price = position['entry_price']
            
            # 计算价格涨幅
            price_increase = ((current_price - entry_price) / entry_price) * 100
            new_level = int(price_increase / 10)  # 每10%一个等级
            
            logging.debug(f"检查止损 {symbol}: 当前价格={current_price}, 入场价格={entry_price}, "
                     f"涨幅={price_increase:.2f}%, 当前等级={new_level}, "
                     f"现有等级={self.stop_loss_levels.get(symbol, 0)}")
        

            if new_level > self.stop_loss_levels.get(symbol, 0):
                # 计算新的止损价格 (entry_price * (1 + 5 * level%))
                stop_loss_percent = 1 + (5 * new_level) / 100
                new_stop_loss = entry_price * stop_loss_percent
                
                logging.info(f"触发止损更新 {symbol}: 新止损价格={new_stop_loss}, 新等级={new_level}") 
                
                self.update_stop_loss_order(
                    symbol=symbol,
                    stop_price=new_stop_loss,
                    new_level=new_level
                )
                
        except Exception as e:
            logging.error(f"检查止损更新失败 {symbol}: {e}")

    def update_stop_loss_order(self, symbol: str, stop_price: float, new_level: int):
        """更新止损订单"""
        try:
            position = self.positions[symbol]
            
            # 取消现有止损订单
            self.client.cancel_all_orders(symbol=symbol)
            
            # 创建新的止损市价单
            response = self.client.new_order(
                symbol=symbol,
                side="SELL" if position['position_amt'] > 0 else "BUY",
                type="STOP_MARKET",
                stopPrice=stop_price,
                quantity=abs(position['position_amt']),
                timeInForce="GTC"
            )
            
            if response:
                self.stop_loss_levels[symbol] = new_level
                asyncio.create_task(self.send_telegram_message(
                    f"🔄 更新止损 {symbol}\n"
                    f"价格涨幅达到: {new_level * 10}%\n"
                    f"新止损价格: {stop_price}\n"
                    f"（开仓价格的 {100 + 5 * new_level}%）"
                ))
                logging.info(f"已更新{symbol}的止损订单: {response}")
                
        except Exception as e:
            logging.error(f"更新止损订单失败 {symbol}: {e}")

    def start_websocket(self):
        """启动WebSocket连接"""
        try:
            if self.ws_client:
                self.ws_client.stop()
                
            self.ws_client = UMFuturesWebsocketClient(
                on_message=self.message_handler
            )
            
            # 订阅所有持仓的价格流
            for symbol in self.positions:
                self.ws_client.ticker(symbol=symbol.lower())
                logging.info(f"订阅{symbol}的价格流")
                
        except Exception as e:
            logging.error(f"启动WebSocket失败: {e}")

    def run(self):
        """运行主程序"""
        try:
            while self.running:
                current_time = time.time()
                # 更新持仓信息
                new_symbols, removed_symbols = self.update_positions()
                
                 # 检查是否需要重启WebSocket
                need_restart = (
                    new_symbols or 
                    removed_symbols or 
                    (current_time - last_ws_check > ws_check_interval and not self.ws_client)
                )
                
                if need_restart:
                    self.start_websocket()
                    last_ws_check = current_time
                
                time.sleep(3)  # 每30秒检查一次持仓变化
                
        except KeyboardInterrupt:
            self.running = False
            if self.ws_client:
                self.ws_client.stop()
            logging.info("程序已停止")
        except Exception as e:
            logging.error(f"程序运行出错: {e}")
            if self.ws_client:
                self.ws_client.stop()

if __name__ == "__main__":
    manager = DynamicStopLossManager()
    manager.run()