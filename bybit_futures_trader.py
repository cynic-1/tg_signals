import logging
import json
import queue
import asyncio
from decimal import Decimal
from typing import Dict, Set
import telegram
from config import ConfigLoader
from timer import PerformanceTimer
from pybit.unified_trading import HTTP, WebSocket
from datetime import datetime
from message_formatter import MessageFormatter


class BybitUSDTFuturesTraderManager:
    def __init__(self, testnet: bool, api_key, api_secret, bot_token, chat_id):
        self.rest_client = HTTP(testnet=testnet, api_key=api_key, api_secret=api_secret)
        self.testnet = testnet
        self.ws_client = None
        self.active_positions = {}  # 当前活跃持仓
        self.monitored_symbols = set()  # 监控的交易对
        self.message_queue = queue.Queue()  # 消息队列
        self.performance_timer = PerformanceTimer()
        self.TELEGRAM_BOT_TOKEN = bot_token
        self.TELEGRAM_CHAT_ID = chat_id
        self.api_key = api_key
        self.api_secret = api_secret
        # 初始化时获取所有交易对信息并存储
        self.symbols_info = {}
        self._init_symbols_info()
        self._start_ws_monitor()
    
    def has_position(self, symbol: str):
        position = self.active_positions.get(symbol)
        
        return position and float(position.get('amount', 0)) != 0

    def has_trade_pair(self, symbol: str):
        return symbol in self.symbols_info

    def new_order(self, leverage: int, symbol: str, usdt_amount: float, 
                                tp_percent: float = None, sl_percent: float = None, long: bool = True):
        self.set_leverage(symbol=symbol, leverage=leverage)

        try: 
            # 执行开仓
            response = self.limit_open_long_with_tp_sl(
                symbol=symbol,
                usdt_amount=usdt_amount,
                tp_percent=tp_percent,
                sl_percent=sl_percent
            )
            
            if response:
                logging.info(f"做多开仓成功: {response}")
        
        except Exception as e:
            logging.error(f"Bybit 做多开仓失败 {symbol if 'symbol' in locals() else 'unknown'}: {e}")
            raise e

    def _init_symbols_info(self):
        """初始化所有交易对信息"""
        try:
            exchange_info = self.rest_client.get_instruments_info(category='linear', limit=1000)
            logging.info(exchange_info)
            # 将交易对信息转换为字典格式，便于快速查询
            self.symbols_info = {
                s['symbol']: s for s in exchange_info['result']['list']
            }
            logging.info(f"已加载 {len(self.symbols_info)} 个交易对信息")
        except Exception as e:
            logging.error(f"初始化交易对信息失败: {e}")
            raise

    def _start_ws_monitor(self):
        """启动WebSocket监控"""
        self.ws_client = WebSocket(
            testnet=self.testnet,
            channel_type="linear",
        )
        self.pr_ws_client = WebSocket(
            testnet=self.testnet,
            channel_type="private",
            api_key=self.api_key,
            api_secret=self.api_secret
        )
        # 初始化持仓和订阅
        self.active_positions = self.get_active_positions()
        self.update_price_subscriptions()

        # self.pr_ws_client.position_stream(callback=self.handle_ws_message)
        self.pr_ws_client.execution_stream(callback=self.handle_ws_message)

    def handle_ws_message(self, message):
        """处理WebSocket消息"""
        try:
            if "tickers" in message['topic']:
                self.handle_price_update(message)
            elif "execution" in message['topic']:
                self.handler_execution_update(message)
            elif "position" in message['topic']:
                self.handle_position_update(message)
                
        except Exception as e:
            logging.error(f"处理WebSocket消息失败: {e}")

    def handler_execution_update(self, message):
        update_message = MessageFormatter.format_bybit_trades(message['data'])
        self.message_queue.put(update_message)
        self.active_positions = self.get_active_positions()

    def update_price_subscriptions(self):
        """更新价格订阅"""
        try:
            current_positions = set(self.active_positions.keys())
            
            # 取消不再持仓的订阅
            remove_symbols = self.monitored_symbols - current_positions
            for symbol in remove_symbols:
                self.ws_client.unsubscribe(stream=[f"tickers.{symbol}"])
                logging.debug(f"取消订阅：{symbol}")

            # 添加新持仓的订阅
            new_symbols = current_positions - self.monitored_symbols
            if new_symbols:
                for symbol in new_symbols:
                    self.ws_client.ticker_stream(symbol=symbol, callback=self.handle_ws_message)
                    logging.debug(f"开始订阅：{symbol}")

            self.monitored_symbols = current_positions
        except Exception as e:
            logging.error(f"更新价格订阅失败: {e}")

    def handle_price_update(self, message):
        """处理价格更新,更新止损"""
        try:
            symbol = (message['topic'].split('.')[-1])
            data = message['data']

            current_price = Decimal(data['markPrice'])
            
            if symbol in self.active_positions:
                position = self.active_positions[symbol]
                entry_price = Decimal(position['entry_price'])
                current_stop_loss = Decimal(position['current_stop_loss'])
                
                # 计算价格变化百分比
                price_change_percent = ((current_price - entry_price) / entry_price) * Decimal('100')
                
                # 如果价格上涨超过10%，更新止损
                if price_change_percent >= Decimal('10'):
                    new_stop_loss = self.calculate_new_stop_loss(price_change_percent, entry_price)
                    
                    if new_stop_loss > current_stop_loss:
                        self.update_stop_loss_order(symbol, new_stop_loss)
                        position['current_stop_loss'] = new_stop_loss
                        
                        update_message = (
                            f"🔄 止损更新\n\n"
                            f"交易对: {symbol}\n"
                            f"前高价格: {current_price}\n"
                            f"涨幅: {price_change_percent:.2f}%\n"
                            f"新止损价: {new_stop_loss}\n"
                        )
                        self.message_queue.put(update_message)
                        
        except Exception as e:
            logging.error(f"处理价格更新失败: {e}")



    def handle_position_update(self, message):
        try:
            logging.debug(message)
            logging.debug(message)
            update_message = BybitUSDTFuturesTraderManager.format_positions(message['data'])
            self.message_queue.put(update_message)
            self.active_positions = self.get_active_positions()
        except Exception as e:
            logging.error(f"处理仓位更新失败: {e}")
        

    @staticmethod
    def format_position(position: dict) -> str:
        """
        将持仓数据格式化为易读的Telegram消息
        使用emoji增加可读性
        """
        if float(position['size']) == 0:
            return f"📊 {position['symbol']}: 当前无持仓"
            
        # 确定持仓方向的emoji
        side_emoji = "🔴" if position['side'] == "Sell" else "🟢"
        
        # 计算盈亏百分比
        entry_price = float(position['entryPrice'])
        mark_price = float(position['markPrice'])
        unrealized_pnl = float(position['unrealisedPnl'])
        pnl_percentage = (mark_price - entry_price) / entry_price * 100
        if position['side'] == "Sell":
            pnl_percentage = -pnl_percentage
        
        # 构建消息
        message = (
            f"{side_emoji} {position['symbol']}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📈 方向: {position['side'] or '无'}\n"
            f"📊 仓位: {position['size']}\n"
            f"💰 开仓价: {position['entryPrice']}\n"
            f"📍 标记价: {position['markPrice']}\n"
            f"⚡️ 杠杆: {position['leverage']}x\n"
            f"💵 未实现盈亏: {unrealized_pnl:.2f} ({pnl_percentage:+.2f}%)\n"
            f"📈 已实现盈亏: {position['curRealisedPnl']}\n"
            f"🎯 止盈: {position['takeProfit'] or '无'}\n"
            f"🛑 止损: {position['stopLoss'] or '无'}\n"
        )
        
        return message

    @staticmethod
    def format_positions(positions: list) -> str:
        """
        格式化多个持仓数据
        """
        if not positions:
            return "📊 当前无持仓"
            
        messages = []
        total_unrealized_pnl = 0
        total_realized_pnl = 0
        
        for pos in positions:
            if float(pos['size']) > 0:  # 只处理有持仓的数据
                messages.append(BybitUSDTFuturesTraderManager.format_position(pos))
                total_unrealized_pnl += float(pos['unrealisedPnl'])
                total_realized_pnl += float(pos['curRealisedPnl'])
        
        if not messages:
            return "📊 当前无持仓"
            
        # 添加汇总信息
        summary = (
            f"\n📊 总计\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 未实现盈亏: {total_unrealized_pnl:.2f}\n"
            f"💵 已实现盈亏: {total_realized_pnl:.2f}\n"
        )
        
        return "\n\n".join(messages) + summary

    def update_stop_loss_order(self, symbol: str, stop_price: float):
        try:
            position = self.active_positions[symbol]

            self.rest_client.cancel_all_orders(category="linear", symbol=symbol)
            response = self.rest_client.place_order(
                category="linear",
                symbol=symbol,
                isLeverage=1,
                side="SELL" if position['position_amt'] > 0 else "BUY",
                orderType="Market",
                triggerDirection=2,
                triggerPrice=self.round_price(price=stop_price, symbol=symbol),
                triggerBy="MarkPrice",
                qty=abs(position['position_amt']),
                timeInForce="GTC",
                reduceOnly="true"
            )

            if not response:
               raise

        except Exception as e:
            logging.error(f"更新止损订单失败 {symbol}: {e}")


    def calculate_new_stop_loss(self, price_change_percent: Decimal, entry_price: Decimal) -> Decimal:
        """计算新的止损价格"""
        try:
            rise_times = int(price_change_percent // Decimal('10'))
            stop_loss_percent = Decimal('100') + (rise_times * Decimal('5'))
            return entry_price * (stop_loss_percent / Decimal('100'))
        except Exception as e:
            logging.error(f"计算止损价格失败: {e}")
            return entry_price * Decimal('0.95')

    def get_symbol_info(self, symbol: str) -> dict:
        """从缓存中获取交易对信息"""
        if symbol not in self.symbols_info:
            raise ValueError(f"未找到交易对 {symbol} 的信息")
        return self.symbols_info[symbol]

    def refresh_symbols_info(self):
        """刷新交易对信息缓存"""
        self._init_symbols_info()

    def get_symbol_price(self, symbol: str) -> float:
        """获取当前市价"""
        try:
            ticker = self.rest_client.get_mark_price_kline(
                category="linear",
                symbol=symbol,
                interval=1
                )
            return float(ticker['result']['list'][0][2])
        except Exception as e:
            logging.error(f"获取价格失败: {e}")
            raise

    def calculate_quantity(self, symbol: str, usdt_amount: float, price: float) -> float:
        """计算下单数量"""
        def get_precision_from_step(step_size: str) -> int:
                """
                从step_size计算精度
                例如:
                "0.001" -> 3
                "0.01" -> 2
                "0.1" -> 1
                "1" -> 0
                "10" -> 0
                """
                decimal_part = step_size.rstrip('0').split('.')
                if len(decimal_part) == 1:  # 没有小数点
                    return 0
                return len(decimal_part[1])
        try:
            symbol_info = self.get_symbol_info(symbol)
            qty_step = symbol_info['lotSizeFilter']['qtyStep']
            quantity_precision = get_precision_from_step(qty_step)
            min_qty = float(symbol_info['lotSizeFilter']['minOrderQty']) 
            
            quantity = round(usdt_amount / price, quantity_precision)
            
            if quantity < min_qty:
                raise ValueError(f"计算得到的数量 {quantity} 小于最小下单量 {min_qty}")
                
            return quantity
        except Exception as e:
            logging.error(f"计算下单数量失败: {e}")
            raise

    def set_leverage(self, symbol: str, leverage: int):
        """设置杠杆倍数"""
        try:
            response = self.rest_client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            logging.info(f"设置杠杆响应: {response}")
            return response
        except Exception as e:
            error_str = str(e)
            if "110043" in error_str:
                logging.info(f"杠杆倍数已经是 {leverage}，无需修改")
                return {"retCode": 0, "leverage": leverage}  # 返回一个模拟的成功响应
            logging.error(f"设置杠杆失败: {e}")
            raise

    def round_price(self, price: float, symbol: str) -> float:
        """按照交易对精度四舍五入价格"""
        try:
            logging.debug(self.symbols_info[symbol])
            pf = self.symbols_info[symbol]['priceFilter']
            min_price = float(pf['minPrice'])
            max_price = float(pf['maxPrice'])
            tick_size= float(pf['tickSize'])

            # 检查价格范围
            if price < min_price:
                raise ValueError(f"价格 {price} 小于最小价格 {min_price}")
            if price > max_price:
                raise ValueError(f"价格 {price} 大于最大价格 {max_price}")
                
            # 根据 tick_size 四舍五入
            rounded_price = round(price / tick_size) * tick_size
            
            # 确保结果仍在范围内
            rounded_price = max(min_price, min(rounded_price, max_price))   
            return rounded_price
        except Exception as e:
            logging.error(f"处理价格时出错: {e}")
            raise
    
    def limit_open_long_with_tp_sl(self, symbol: str, usdt_amount: float, 
                                    tp_percent: float = None, sl_percent: float = None):
                """限价开多并设置止盈止损"""
                try:
                    current_price = self.get_symbol_price(symbol)
                    price = self.round_price(symbol=symbol, price=(current_price*0.97))
                    logging.info(f"当前市价: {current_price}")
                    
                    quantity = self.calculate_quantity(symbol, usdt_amount, price=price)
                    logging.info(f"下单数量: {quantity}")

                    sl_price = self.round_price(current_price * (1 - 5/100), symbol)
                    if sl_percent:
                        sl_price = self.round_price(current_price * (1 - sl_percent/100), symbol)
                        
                    # 4. 执行市价开多订单
                    open_params = {
                        'category': 'linear',
                        'symbol': symbol,
                        'isLeverage': 1,
                        'side': 'Buy',
                        'orderType': 'LIMIT',
                        'price': price,
                        'qty': quantity,
                        'stopLoss': sl_price 
                    }
                    
                    response = self.rest_client.place_order(**open_params)
                    logging.info(f"开仓订单响应: {response}")
                    
                    return {
                        'open_order': response,
                    }
                    
                except Exception as e:
                    logging.error(f"开仓设置止盈止损失败: {e}")
                    # 如果开仓成功但设置止盈止损失败，尝试关闭仓位
                    try:
                        self.close_position(symbol)
                        logging.info("已关闭仓位")
                    except:
                        logging.error("关闭仓位失败，请手动处理")
                    raise

    def market_open_long_with_tp_sl(self, symbol: str, usdt_amount: float, 
                                tp_percent: float = None, sl_percent: float = None):
            """市价开多并设置止盈止损"""
            try:
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                price = self.round_price(symbol=symbol, price=(current_price*0.97))
                logging.info(f"当前市价: {current_price}")
                
                quantity = self.calculate_quantity(symbol, usdt_amount, price=price)
                logging.info(f"下单数量: {quantity}")
                

                sl_price = self.round_price(current_price * (1 - 5/100), symbol)
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 - sl_percent/100), symbol)
                    
                # 4. 执行市价开多订单
                open_params = {
                    'category': 'linear',
                    'symbol': symbol,
                    'isLeverage': 1,
                    'side': 'Buy',
                    'orderType': 'MARKET',
                    'qty': quantity,
                    'stopLoss': sl_price 
                }
                
                response = self.rest_client.place_order(**open_params)
                logging.info(f"开仓订单响应: {response}")
                
                return {
                    'open_order': response,
                }
                
            except Exception as e:
                logging.error(f"开仓设置止盈止损失败: {e}")
                # 如果开仓成功但设置止盈止损失败，尝试关闭仓位
                try:
                    self.close_position(symbol)
                    logging.info("已关闭仓位")
                except:
                    logging.error("关闭仓位失败，请手动处理")
                raise

    def get_active_positions(self) -> Dict[str, Dict]:
        """获取所有活跃持仓"""
        try:
            positions = self.rest_client.get_positions(
                category="linear",
                settleCoin="USDT"
            )
            active_positions = {}
            for position in positions['result']['list']:
                amount = Decimal(position['size'])
                if amount != 0:
                    symbol = position['symbol']
                    active_positions[symbol] = {
                        'amount': amount,
                        'entry_price': position['avgPrice'],
                        'current_stop_loss': position['stopLoss'],
                        'unrealized_profit': Decimal(position['unrealisedPnl'])
                    }
            return active_positions
        except Exception as e:
            logging.error(f"获取活跃持仓失败: {e}")
            return {}

    async def process_message_queue(self):
        """处理消息队列"""
        while True:
            try:
                while not self.message_queue.empty():
                    message = self.message_queue.get_nowait()
                    await self.send_telegram_message(message)
                    self.message_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                logging.error(f"处理消息队列失败: {e}")
            finally:
                await asyncio.sleep(1)

    async def send_telegram_message(self, message: str):
        """发送Telegram消息"""
        try:
            bot = telegram.Bot(token=self.TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=self.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='HTML'
            )
            await bot.send_message(
                chat_id=644902470,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"发送Telegram消息失败: {e}")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def main():
    try:
        # 从配置获取API密钥
        config = ConfigLoader.load_from_env()
        api_key = config['bybit_api_key']
        api_secret = config['bybit_api_secret']
        TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
        TELEGRAM_CHAT_ID_SELF = config['TELEGRAM_CHAT_ID_SELF']
        # 初始化交易器
        trader = BybitUSDTFuturesTraderManager(
            testnet=False,
            api_key=api_key, 
            api_secret=api_secret, 
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID_SELF
            )
        
        # 启动WebSocket监控
        # trader.start_ws_monitor()
        
        # 发送启动消息
        # await trader.send_telegram_message("🤖 Bybit 交易机器人启动\n监控开始！")
        
        trader.set_leverage(symbol='RIFSOLUSDT', leverage=5)
        trader.limit_open_long_with_tp_sl(
            symbol='RIFSOLUSDT', 
            usdt_amount=100,
            tp_percent=100.0,
            sl_percent=5.0
            )
        # 启动消息处理任务
        # message_processor = asyncio.create_task(trader.process_message_queue())
        
        # 保持程序运行
        # await asyncio.gather(message_processor)
        
    except KeyboardInterrupt:
        logging.info("程序已手动停止")
    except Exception as e:
        logging.error(f"程序发生错误: {e}")
        logging.exception(e)
    # finally:
        # if trader.ws_client:
            # trader.ws_client.stop()


if __name__ == "__main__":
    # 安装必要的包
    # pip install python-telegram-bot requests

    # 运行异步主函数
    asyncio.run(main())
