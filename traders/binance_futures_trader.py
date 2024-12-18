import json
import queue
import asyncio
from decimal import Decimal, InvalidOperation, ConversionSyntax
from typing import Dict, Optional
import telegram
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from config import ConfigLoader
from utils import PerformanceTimer, setup_logger
from services import MessageFormatter
import time
from threading import Thread, Lock

class BinanceUSDTFuturesTraderManager:
    MAX_RECONNECT_ATTEMPTS = 10
    HEARTBEAT_TIMEOUT = 200
    LISTEN_KEY_REFRESH_INTERVAL = 1800  # 30分钟
    PING_INTERVAL = 20

    def __init__(self, api_key, api_secret, bot_token, chat_id):
        self.rest_client = UMFutures(key=api_key, secret=api_secret)
        self.ws_client = None
        self.active_positions = {}
        self.monitored_symbols = set()
        self.message_queue = queue.Queue()
        self.performance_timer = PerformanceTimer()
        self.TELEGRAM_BOT_TOKEN = bot_token
        self.TELEGRAM_CHAT_ID = chat_id
        
        # 初始化锁
        self.ws_lock = Lock()
        self.position_lock = Lock()
        
        # WebSocket状态
        self.is_ws_connected = False
        self.ws_reconnect_count = 0
        self.listen_key = None
        
        # 初始化日志
        self.logger = setup_logger('binance_trader')
        
        # 初始化交易对信息
        self.symbols_info = {}
        self._init_symbols_info()
        
        # 启动WebSocket
        self._start_ws_monitor()
        
        # 启动监控线程
        # self.ws_monitor_thread = Thread(target=self._monitor_ws_connection, daemon=True)
        # self.ws_monitor_thread.start()
        
        # 启动listen key维护线程
        self.listen_key_thread = Thread(target=self._keep_listen_key_alive, daemon=True)
        self.listen_key_thread.start()
        
        self.last_heartbeat = time.time()


    def _get_listen_key(self) -> Optional[str]:
        """获取新的listen key"""
        try:
            response = self.rest_client.new_listen_key()
            return response['listenKey']
        except Exception as e:
            self.logger.error(f"获取listen key失败: {e}")
            return None

    def _keep_listen_key_alive(self):
        while True:
            try:
                # 使用延长listen key有效期的接口
                self.rest_client.renew_listen_key(self.listen_key)
                self.logger.info("续期listen key成功")
                time.sleep(300)  # 建议改为5分钟检查一次
            except Exception as e:
                if e.error_code == -1125:  # listen key不存在
                    self.logger.warning("Listen key已失效，正在重新获取...")
                    new_key = self._get_listen_key()
                    if new_key:
                        self.listen_key = new_key
                        self._reconnect_websocket()
                self.logger.error(f"续期listen key失败: {e}")
                time.sleep(60)

    def _start_ws_monitor(self):
        """启动WebSocket监控"""
        with self.ws_lock:
            try:
                if self.ws_client:
                    self.ws_client.stop()
                
                # 获取新的listen key
                self.listen_key = self._get_listen_key()
                if not self.listen_key:
                    raise Exception("Failed to get listen key")
                
                self.ws_client = UMFuturesWebsocketClient(
                    on_message=self.handle_ws_message,
                    is_combined=True
                )
                
                # 订阅用户数据流
                self.ws_client.user_data(listen_key=self.listen_key)
                
                self.is_ws_connected = True
                self.ws_reconnect_count = 0
                self.last_heartbeat = time.time()
                
                self.logger.info("WebSocket连接成功建立")
                
                # 更新持仓信息和订阅
                with self.position_lock:
                    self.active_positions = self.get_active_positions()
                self.update_price_subscriptions()
                
            except Exception as e:
                self.logger.error(f"启动WebSocket失败: {e}")
                self.is_ws_connected = False
                raise

    def _reconnect_websocket(self):
        """重新连接WebSocket"""
        try:
            self._start_ws_monitor()
            return True
        except Exception as e:
            self.logger.error(f"重连失败: {e}")
            return False

    def _handle_ws_disconnection(self):
        """处理WebSocket断开连接"""
        if self.ws_reconnect_count >= self.MAX_RECONNECT_ATTEMPTS:
            self.logger.error("达到最大重连次数，停止重连")
            return False
            
        delay = min(2 ** self.ws_reconnect_count, 300)
        self.logger.info(f"等待 {delay} 秒后尝试重连...")
        time.sleep(delay)
        
        self.ws_reconnect_count += 1
        self.logger.info(f"尝试第 {self.ws_reconnect_count} 次重连")
        
        return self._reconnect_websocket()

    def _monitor_ws_connection(self):
        """监控WebSocket连接状态"""
        disconnect_time = None
        
        while True:
            try:
                current_time = time.time()
                
                if (current_time - self.last_heartbeat > self.HEARTBEAT_TIMEOUT or 
                    not self.is_ws_connected):
                    
                    if disconnect_time is None:
                        disconnect_time = current_time
                        self.logger.warning("检测到WebSocket断开")
                        self.notify_disconnect()
                    
                    if self._handle_ws_disconnection():
                        self.logger.info("重连成功")
                        self.notify_reconnect()
                        disconnect_time = None
                else:
                    if disconnect_time is not None:
                        self.logger.info("连接恢复正常")
                        disconnect_time = None
                        
                time.sleep(10)
                
            except Exception as e:
                self.logger.error(f"监控线程错误: {e}")
                time.sleep(10)

    def handle_ws_message(self, _, message):
            """处理WebSocket消息"""
            try:
                self.last_heartbeat = time.time()
                self.is_ws_connected = True
                
                if isinstance(message, str):
                    message = json.loads(message)
                
                # 忽略心跳和订阅确认消息
                if message.get('result') is None:
                    return
                    
                self.logger.debug(f"Received message: {message}")
                
                # 确保消息包含必要的字段
                if 'data' not in message:
                    return
                    
                data = message['data']
                
                # 处理不同类型的消息
                if isinstance(data, dict) and 'e' in data:
                    event_type = data['e']
                    if event_type == 'ACCOUNT_UPDATE':
                        self.handle_account_update(data)
                    elif event_type == 'ORDER_TRADE_UPDATE':
                        self.handle_order_update(data)
                
                elif 'stream' in message and 'markPrice' in message['stream']:
                    self.handle_price_update(message)
                    
            except Exception as e:
                self.logger.error(f"处理WebSocket消息失败: {str(e)}", exc_info=True)
    
    def _init_symbols_info(self):
        """初始化所有交易对信息"""
        try:
            exchange_info = self.rest_client.exchange_info()
            # 将交易对信息转换为字典格式，便于快速查询
            self.symbols_info = {
                s['symbol']: s for s in exchange_info['symbols']
            }
            self.logger.info(f"已加载 {len(self.symbols_info)} 个交易对信息")
        except Exception as e:
            self.logger.error(f"初始化交易对信息失败: {e}")
            raise

    def has_trade_pair(self, symbol: str):
            return symbol in self.symbols_info

    def has_position(self, symbol: str):
        self.logger.info(f"enter has_position({symbol})")
        position = self.active_positions.get(symbol)
        self.logger.info(f"position: {position}")
        return position and float(position.get('amount', 0)) != 0

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
                    self.logger.info(f"做多开仓成功: {response}")

            except Exception as e:
                self.logger.error(f"Binance 做多开仓失败 {symbol if 'symbol' in locals() else 'unknown'}: {e}")
                raise e

    def update_price_subscriptions(self):
        """更新价格订阅"""
        try:
            current_positions = set(self.active_positions.keys())
            
            # 取消不再持仓的订阅
            remove_symbols = self.monitored_symbols - current_positions
            for symbol in remove_symbols:
                self.ws_client.unsubscribe(stream=[f"{symbol.lower()}@markPrice@1s"])

            # 添加新持仓的订阅
            new_symbols = current_positions - self.monitored_symbols
            if new_symbols:
                streams = [f"{symbol.lower()}@markPrice@1s" for symbol in new_symbols]
                self.ws_client.subscribe(stream=streams)

            self.monitored_symbols = current_positions
        except Exception as e:
            self.logger.error(f"更新价格订阅失败: {e}")

    def notify_disconnect(self):
            """发送断连通知"""
            message = f"⚠️ WebSocket连接断开\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.message_queue.put(message)

    def notify_reconnect(self):
            """发送重连成功通知"""
            message = f"✅ WebSocket重连成功\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.message_queue.put(message)

    def handle_account_update(self, message):
        """处理账户更新消息"""
        self.logger.debug("处理账户更新")
        try:
            update_message = MessageFormatter.format_account_update(message)
            self.message_queue.put(update_message)
            self.active_positions = self.get_active_positions()
            # self.update_price_subscriptions()
        except Exception as e:
            self.logger.error(f"处理账户更新失败: {e}")

    def handle_price_update(self, data):
        """处理价格更新,更新止损"""
        def safe_decimal_convert(value, default=None):
            """安全地将值转换为Decimal"""
            try:
                if value is None:
                    return default
                return Decimal(str(value).strip())
            except (InvalidOperation, ConversionSyntax) as e:
                self.logger.error(f"Decimal转换失败 - 值: {value}, 错误: {e}")
                return default
        try:
            symbol = data['s']
            current_price = safe_decimal_convert(data['p'])
            if current_price is None:
                return

            if symbol in self.active_positions:
                position = self.active_positions[symbol]
                entry_price = safe_decimal_convert(position['entry_price'])
                if entry_price is None:
                    return

                current_stop_loss = position['current_stop_loss']
                
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
                            f"当前价格: {current_price}\n"
                            f"涨幅: {price_change_percent:.2f}%\n"
                            f"新止损价: {new_stop_loss}\n"
                        )
                        self.message_queue.put(update_message)
                        
        except Exception as e:
            self.logger.error(f"处理价格更新失败: {e}")

    def update_stop_loss_order(self, symbol: str, stop_price: float):
        try:
            position = self.active_positions[symbol]

            self.rest_client.cancel_open_orders(symbol=symbol)
            self.logger.debug("创建新止损前")
            response = self.rest_client.new_order(
                symbol=symbol,
                side="SELL" if position['amount'] > 0 else "BUY",
                type="STOP_MARKET",
                stopPrice=self.round_price(stop_price, symbol),
                quantity=abs(position['amount']),
                timeInForce="GTC"
            )
            self.logger.debug("创建新止损后")

            if not response:
               raise

        except Exception as e:
            self.logger.error(f"更新止损订单失败 {symbol}: {e}")


    def calculate_new_stop_loss(self, price_change_percent: Decimal, entry_price: Decimal) -> Decimal:
        """计算新的止损价格"""
        try:
            rise_times = int(price_change_percent // Decimal('10'))
            stop_loss_percent = Decimal('100') + (rise_times * Decimal('5'))
            return entry_price * (stop_loss_percent / Decimal('100'))
        except Exception as e:
            self.logger.error(f"计算止损价格失败: {e}")
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
            ticker = self.rest_client.ticker_price(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"获取价格失败: {e}")
            raise

    def calculate_quantity(self, symbol: str, usdt_amount: float, price: float) -> float:
        """计算下单数量"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            quantity_precision = next(
                (int(filter['stepSize'].find('1') - 1)
                 for filter in symbol_info['filters']
                 if filter['filterType'] == 'LOT_SIZE'),
                4
            )
            min_qty = float(next(
                (filter['minQty']
                 for filter in symbol_info['filters']
                 if filter['filterType'] == 'LOT_SIZE'),
                0
            ))
            
            quantity = round(usdt_amount / price, quantity_precision)
            
            if quantity < min_qty:
                raise ValueError(f"计算得到的数量 {quantity} 小于最小下单量 {min_qty}")
                
            return quantity
        except Exception as e:
            self.logger.error(f"计算下单数量失败: {e}")
            raise

    def close_position(self, symbol: str):
        """市价全部平仓"""
        try:
            position = self.get_position(symbol)
            if position and float(position['positionAmt']) != 0:
                params = {
                    'symbol': symbol,
                    'side': 'SELL' if float(position['positionAmt']) > 0 else 'BUY',
                    'type': 'MARKET',
                    'quantity': abs(float(position['positionAmt'])),
                    'reduceOnly': True
                }
                response = self.rest_client.new_order(**params)
                self.message_queue.put(
                    f"✅ 平仓成功\n"
                    f"交易对: {symbol}\n"
                    f"数量: {abs(float(position['positionAmt']))}"
                )
                return response
            return None
        except Exception as e:
            self.logger.error(f"平仓失败: {e}")
            raise

    def set_leverage(self, symbol: str, leverage: int):
        """设置杠杆倍数"""
        try:
            response = self.rest_client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            self.logger.info(f"设置杠杆响应: {response}")
            return response
        except Exception as e:
            self.logger.error(f"设置杠杆失败: {e}")
            raise

    def round_price(self, price: float, symbol: str) -> float:
            """按照交易对精度四舍五入价格"""
            try:
                self.logger.debug(self.symbols_info[symbol])
                pf = next(filter for filter in self.symbols_info[symbol]['filters'] if filter['filterType'] == 'PRICE_FILTER')
                min_price = float(pf['minPrice'])
                max_price = float(pf['maxPrice'])
                tick_size= float(pf['tickSize'])
                # 计算小数位数
                decimal_places = len(str(tick_size).split('.')[-1])
                # 检查价格范围
                if price < min_price:
                    raise ValueError(f"价格 {price} 小于最小价格 {min_price}")
                if price > max_price:
                    raise ValueError(f"价格 {price} 大于最大价格 {max_price}")
                    
                # 根据 tick_size 四舍五入
                rounded_price = round(price / tick_size) * tick_size
                
                # 使用格式化字符串确保精确的小数位数
                rounded_price = float(f"%.{decimal_places}f" % rounded_price)
                
                # 确保结果仍在范围内
                rounded_price = max(min_price, min(rounded_price, max_price))   
                return rounded_price

            except Exception as e:
                self.logger.error(f"处理价格时出错: {e}")
            raise

    def get_price_precision(self, symbol: str) -> int:
        """获取价格精度"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            price_filter = next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
            tick_size = float(price_filter['tickSize'])
            return len(str(tick_size).rstrip('0').split('.')[-1])
        except Exception as e:
            self.logger.error(f"获取价格精度失败: {e}")
            raise

    def limit_open_long_with_tp_sl(self, symbol: str, usdt_amount: float, 
                                tp_percent: float = None, sl_percent: float = None):
            """市价开多并设置止盈止损"""
            try:
                
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                
                price = self.round_price(current_price * 0.97, symbol)

                self.logger.info(f"当前市价: {current_price}, 下单价格: {price}")

                quantity = self.calculate_quantity(symbol, usdt_amount, price=price)
                self.logger.info(f"下单数量: {quantity}")
                
                # 4. 执行市价开多订单
                open_params = {
                    'symbol': symbol,
                    'side': 'BUY',
                    'type': 'LIMIT',
                    'price': price,
                    'quantity': quantity,
                    'timeInForce': 'GTC',
                }
                
                response = self.rest_client.new_order(**open_params)
                self.logger.info(f"开仓订单响应: {response}")
                
                # 5. 设置止盈单
                if tp_percent:
                    tp_price = self.round_price(current_price * (1 + tp_percent/100), symbol)
                    self.logger.info(f"止盈价格: {tp_price}")
                    tp_params = {
                        'symbol': symbol,
                        'side': 'SELL',
                        'type': 'TAKE_PROFIT_MARKET',
                        'quantity': quantity,
                        'stopPrice': tp_price,
                        'workingType': 'MARK_PRICE',
                        'reduceOnly': True
                    }
                    tp_response = self.rest_client.new_order(**tp_params)
                    self.logger.info(f"止盈订单响应: {tp_response}")

                # 6. 设置止损单
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 - sl_percent/100), symbol)
                    self.logger.info(f"止损价格: {sl_price}")
                    sl_params = {
                        'symbol': symbol,
                        'side': 'SELL',
                        'type': 'STOP_MARKET',
                        'quantity': quantity,
                        'stopPrice': sl_price,
                        'workingType': 'MARK_PRICE',
                        'reduceOnly': True
                    }
                    sl_response = self.rest_client.new_order(**sl_params)
                    self.logger.info(f"止损订单响应: {sl_response}")

                # 7. 设置追踪止损单
                if sl_percent:
                    sl_params = {
                        'symbol': symbol,
                        'side': 'SELL',
                        'type': 'TRAILING_STOP_MARKET',
                        'quantity': quantity,
                        'callbackRate': 5,
                        'reduceOnly': True
                    }
                    sl_response = self.rest_client.new_order(**sl_params)
                    self.logger.info(f"追踪止损订单响应: {sl_response}")
                
                return {
                    'open_order': response,
                    'tp_order': tp_response if tp_percent else None,
                    'sl_order': sl_response if sl_percent else None
                }
                
            except Exception as e:
                self.logger.error(f"开仓设置止盈止损失败: {e}")
                # 如果开仓成功但设置止盈止损失败，尝试关闭仓位
                try:
                    self.close_position(symbol)
                    self.logger.info("已关闭仓位")
                except:
                    self.logger.error("关闭仓位失败，请手动处理")
                raise
    
    def market_open_long_with_tp_sl(self, symbol: str, usdt_amount: float, 
                                tp_percent: float = None, sl_percent: float = None):
            """市价开多并设置止盈止损"""
            try:
                # 2. 计算下单数量
                quantity = self.calculate_quantity(symbol, usdt_amount)
                self.logger.info(f"下单数量: {quantity}")
                
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                self.logger.info(f"当前市价: {current_price}")
                
                # 4. 执行市价开多订单
                open_params = {
                    'symbol': symbol,
                    'side': 'BUY',
                    'type': 'MARKET',
                    'quantity': quantity
                }
                
                response = self.rest_client.new_order(**open_params)
                self.logger.info(f"开仓订单响应: {response}")
                
                # 5. 设置止盈单
                if tp_percent:
                    tp_price = self.round_price(current_price * (1 + tp_percent/100), symbol)
                    self.logger.info(f"止盈价格: {tp_price}")
                    tp_params = {
                        'symbol': symbol,
                        'side': 'SELL',
                        'type': 'TAKE_PROFIT_MARKET',
                        'quantity': quantity,
                        'stopPrice': tp_price,
                        'workingType': 'MARK_PRICE',
                        'reduceOnly': True
                    }
                    tp_response = self.rest_client.new_order(**tp_params)
                    self.logger.info(f"止盈订单响应: {tp_response}")
                
                # 6. 设置止损单
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 - sl_percent/100), symbol)
                    self.logger.info(f"止损价格: {sl_price}")
                    sl_params = {
                        'symbol': symbol,
                        'side': 'SELL',
                        'type': 'TRAILING_STOP_MARKET',
                        'quantity': quantity,
                        'callbackRate': 5,
                        'reduceOnly': True
                    }
                    sl_response = self.rest_client.new_order(**sl_params)
                    self.logger.info(f"追踪止损订单响应: {sl_response}")
                
                return {
                    'open_order': response,
                    'tp_order': tp_response if tp_percent else None,
                    'sl_order': sl_response if sl_percent else None
                }
                
            except Exception as e:
                self.logger.error(f"开仓设置止盈止损失败: {e}")
                # 如果开仓成功但设置止盈止损失败，尝试关闭仓位
                try:
                    self.close_position(symbol)
                    self.logger.info("已关闭仓位")
                except:
                    self.logger.error("关闭仓位失败，请手动处理")
                raise

    def market_open_short_with_tp_sl(self, symbol: str, usdt_amount: float,
                                    tp_percent: float = None, sl_percent: float = None):
            """市价开空并设置止盈止损"""
            try:
                # 2. 计算下单数量
                quantity = self.calculate_quantity(symbol, usdt_amount)
                self.logger.info(f"下单数量: {quantity}")
                
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                self.logger.info(f"当前市价: {current_price}")
                
                # 4. 执行市价开空订单
                open_params = {
                    'symbol': symbol,
                    'side': 'SELL',
                    'type': 'MARKET',
                    'quantity': quantity
                }
                
                response = self.rest_client.new_order(**open_params)
                self.logger.info(f"开仓订单响应: {response}")
                
                # 5. 设置止盈单
                if tp_percent:
                    tp_price = self.round_price(current_price * (1 - tp_percent/100), symbol)
                    self.logger.info(f"止盈价格: {tp_price}")
                    tp_params = {
                        'symbol': symbol,
                        'side': 'BUY',
                        'type': 'TAKE_PROFIT_MARKET',
                        'quantity': quantity,
                        'stopPrice': tp_price,
                        'workingType': 'MARK_PRICE',
                        'reduceOnly': True
                    }
                    tp_response = self.rest_client.new_order(**tp_params)
                    self.logger.info(f"止盈订单响应: {tp_response}")
                
                # 6. 设置止损单
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 + sl_percent/100), symbol)
                    self.logger.info(f"止损价格: {sl_price}")
                    sl_params = {
                        'symbol': symbol,
                        'side': 'BUY',
                        'type': 'STOP_MARKET',
                        'quantity': quantity,
                        'stopPrice': sl_price,
                        'workingType': 'MARK_PRICE',
                        'reduceOnly': True
                    }
                    sl_response = self.rest_client.new_order(**sl_params)
                    self.logger.info(f"止损订单响应: {sl_response}")
                
                return {
                    'open_order': response,
                    'tp_order': tp_response if tp_percent else None,
                    'sl_order': sl_response if sl_percent else None
                }
                
            except Exception as e:
                self.logger.error(f"开仓设置止盈止损失败: {e}")
                # 如果开仓成功但设置止盈止损失败，尝试关闭仓位
                try:
                    self.close_position(symbol)
                    self.logger.info("已关闭仓位")
                except:
                    self.logger.error("关闭仓位失败，请手动处理")
                raise

    def get_position(self, symbol: str):
        """获取单个交易对持仓信息"""
        try:
            positions = self.rest_client.get_position_risk()
            return next((p for p in positions if p['symbol'] == symbol), None)
        except Exception as e:
            self.logger.error(f"获取持仓信息失败: {e}")
            raise

    def get_all_positions(self):
        try:
            positions = self.rest_client.get_position_risk()
            return positions
        except Exception as e:
            self.logger.error(f"获取持仓信息失败: {e}")
            raise
    
    def format_position_risk(positions):
        if not positions:
            return "No open positions"
        
        # 对positions按未实现盈亏排序(从大到小)
        sorted_positions = sorted(
            positions,
            key=lambda x: float(x['unRealizedProfit']),
            reverse=True
        )
        
        # 计算总未实现盈亏
        total_pnl = sum(float(p['unRealizedProfit']) for p in positions)
        
        # 格式化每个持仓的信息
        formatted_positions = []
        for pos in sorted_positions:
            if float(pos['positionAmt']) == 0:
                continue
                
            entry_price = float(pos['entryPrice'])
            mark_price = float(pos['markPrice'])
            pnl = float(pos['unRealizedProfit'])
            
            # 计算价格变动百分比
            price_change_pct = ((mark_price - entry_price) / entry_price) * 100
            
            # 使用箭头表示盈亏状态
            arrow = "🟢" if pnl > 0 else "🔴"
            
            position_str = (
                f"{arrow} {pos['symbol']}\n"
                f"持仓: {float(pos['positionAmt']):,.0f}\n"
                f"入场价: {entry_price:.8f}\n"
                f"当前价: {mark_price:.8f} ({price_change_pct:+.2f}%)\n"
                f"未实现盈亏: {pnl:+.2f} USDT\n"
                f"清算价: {float(pos['liquidationPrice']):.8f}\n"
                f"──────────────"
            )
            formatted_positions.append(position_str)
        
        # 组合所有信息
        header = "📊 当前持仓状况\n══════════════\n"
        footer = f"\n💰 总计盈亏: {total_pnl:+.2f} USDT"
        
        return header + "\n".join(formatted_positions) + footer

    def get_active_positions(self) -> Dict[str, Dict]:
        """获取所有活跃持仓"""
        try:
            positions = self.rest_client.get_position_risk()
            active_positions = {}
            for position in positions:
                amount = Decimal(position['positionAmt'])
                if amount != 0:
                    symbol = position['symbol']
                    entry_price = Decimal(position['entryPrice'])
                    active_positions[symbol] = {
                        'amount': amount,
                        'entry_price': entry_price,
                        'current_stop_loss': entry_price * Decimal('0.95'),
                        'unrealized_profit': Decimal(position['unRealizedProfit'])
                    }
            return active_positions
        except Exception as e:
            self.logger.error(f"获取活跃持仓失败: {e}")
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
                self.logger.error(f"处理消息队列失败: {e}")
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
            self.logger.error(f"发送Telegram消息失败: {e}")

# 在程序开始处添加日志配置
# self.logger.basicConfig(
    # level=self.logger.DEBUG,
    # format='%(asctime)s - %(levelname)s - %(message)s'
# )
# config = ConfigLoader.load_from_env()
# TELEGRAM_BOT_TOKEN = config['TELEGRAM_BOT_TOKEN']
# TELEGRAM_CHAT_ID = config['TELEGRAM_CHAT_ID']
# TELEGRAM_CHAT_ID_SELF = config['TELEGRAM_CHAT_ID_SELF']


# trader = BinanceUSDTFuturesTraderManager(
    # api_key=config['api_key'],
    # api_secret=config['api_secret'],
    # bot_token=TELEGRAM_BOT_TOKEN,
    # chat_id=TELEGRAM_CHAT_ID_SELF
# )
# symbol = "ACTUSDT"
# while (1):
    # if trader.has_position("ACTUSDT"):
        # self.logger.info("有持仓")
    # else:
        # self.logger.info("没持仓")
        # trader.limit_open_long_with_tp_sl(
            # symbol=symbol, 
            # usdt_amount=100,
            # tp_percent=50,
            # sl_percent=3
            # )
    # time.sleep(10)