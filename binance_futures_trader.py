import logging
import json
import queue
import asyncio
from decimal import Decimal
from typing import Dict, Set
import telegram
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from config import ConfigLoader
from timer import PerformanceTimer

class USDTFuturesTraderManager:
    def __init__(self, api_key, api_secret, bot_token, chat_id):
        self.rest_client = UMFutures(key=api_key, secret=api_secret)
        self.ws_client = None
        self.active_positions = {}  # 当前活跃持仓
        self.monitored_symbols = set()  # 监控的交易对
        self.message_queue = queue.Queue()  # 消息队列
        self.performance_timer = PerformanceTimer()
        self.TELEGRAM_BOT_TOKEN = bot_token
        self.TELEGRAM_CHAT_ID = chat_id
        # 初始化时获取所有交易对信息并存储
        self.symbols_info = {}
        self._init_symbols_info()
    
    def _init_symbols_info(self):
        """初始化所有交易对信息"""
        try:
            exchange_info = self.rest_client.exchange_info()
            # 将交易对信息转换为字典格式，便于快速查询
            self.symbols_info = {
                s['symbol']: s for s in exchange_info['symbols']
            }
            logging.info(f"已加载 {len(self.symbols_info)} 个交易对信息")
        except Exception as e:
            logging.error(f"初始化交易对信息失败: {e}")
            raise

    def start_ws_monitor(self):
        """启动WebSocket监控"""
        self.ws_client = UMFuturesWebsocketClient(
            on_message=self.handle_ws_message,
            is_combined=True
        )
        # 订阅账户更新
        listen_key = self.rest_client.new_listen_key()['listenKey']
        self.ws_client.user_data(listen_key=listen_key)
        # 初始化持仓和订阅
        self.active_positions = self.get_active_positions()
        self.update_price_subscriptions()

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
            logging.error(f"更新价格订阅失败: {e}")

    def handle_ws_message(self, _, message):
        """处理WebSocket消息"""
        try:
            if isinstance(message, str):
                message = json.loads(message)
            
            logging.debug(f"message: {message}")
            # 处理账户更新消息
            if 'e' in message['data'] and message['data']['e'] == 'ACCOUNT_UPDATE':
                self.handle_account_update(message['data'])
            
            # 处理标记价格更新
            elif 'stream' in message and 'markPrice' in message['stream']:
                self.handle_price_update(message['data'])
                
        except Exception as e:
            logging.error(f"处理WebSocket消息失败: {e}")

    def handle_account_update(self, message):
        """处理账户更新消息"""
        logging.debug("处理账户更新")
        try:
            update_data = message['a']
            position_updates = []
            
            # 处理持仓更新
            if 'P' in update_data:
                for position in update_data['P']:
                    symbol = position['s']
                    amount = Decimal(position['pa'])
                    entry_price = Decimal(position['ep'])
                    
                    position_info = {
                        'symbol': symbol,
                        'amount': amount,
                        'entry_price': entry_price
                    }
                    position_updates.append(position_info)
                position_updates.append(self.format_position_risk(self.get_all_positions))
            
            # 格式化更新信息并发送到Telegram
            if position_updates:
                update_message = "🎯 成交:\n\n"
                for pos in position_updates:
                    update_message += (
                        f"交易对: {pos['symbol']}\n"
                        f"持仓量: {pos['amount']}\n"
                        f"入场价: {pos['entry_price']}\n"
                        f"---------------\n"
                    )
                self.message_queue.put(update_message)
                
        except Exception as e:
            logging.error(f"处理账户更新失败: {e}")

    def handle_price_update(self, data):
        """处理价格更新,更新止损"""
        try:
            symbol = data['s']
            current_price = Decimal(data['p'])
            
            if symbol in self.active_positions:
                position = self.active_positions[symbol]
                entry_price = position['entry_price']
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
            logging.error(f"处理价格更新失败: {e}")

    def update_stop_loss_order(self, symbol: str, stop_price: float):
        try:
            position = self.active_positions[symbol]

            self.rest_client.cancel_open_orders(symbol=symbol)
            logging.debug("创建新止损前")
            response = self.rest_client.new_order(
                symbol=symbol,
                side="SELL" if position['amount'] > 0 else "BUY",
                type="STOP_MARKET",
                stopPrice=self.round_price(stop_price, symbol),
                quantity=abs(position['amount']),
                timeInForce="GTC"
            )
            logging.debug("创建新止损后")

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
            ticker = self.rest_client.ticker_price(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logging.error(f"获取价格失败: {e}")
            raise

    def calculate_quantity(self, symbol: str, usdt_amount: float) -> float:
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
            
            price = self.get_symbol_price(symbol)
            quantity = round(usdt_amount / price, quantity_precision)
            
            if quantity < min_qty:
                raise ValueError(f"计算得到的数量 {quantity} 小于最小下单量 {min_qty}")
                
            return quantity
        except Exception as e:
            logging.error(f"计算下单数量失败: {e}")
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
            logging.error(f"平仓失败: {e}")
            raise

    def set_leverage(self, symbol: str, leverage: int):
        """设置杠杆倍数"""
        try:
            response = self.rest_client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logging.info(f"设置杠杆响应: {response}")
            return response
        except Exception as e:
            logging.error(f"设置杠杆失败: {e}")
            raise

    def round_price(self, price: float, symbol: str) -> float:
        """按照交易对精度四舍五入价格"""
        precision = self.symbols_info[symbol]['pricePrecision']
        logging.debug(f"{symbol} precision: {precision}")
        return round(price, precision)

    def get_price_precision(self, symbol: str) -> int:
        """获取价格精度"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            price_filter = next(filter(lambda x: x['filterType'] == 'PRICE_FILTER', symbol_info['filters']))
            tick_size = float(price_filter['tickSize'])
            return len(str(tick_size).rstrip('0').split('.')[-1])
        except Exception as e:
            logging.error(f"获取价格精度失败: {e}")
            raise

    def market_open_long_with_tp_sl(self, symbol: str, usdt_amount: float, 
                                tp_percent: float = None, sl_percent: float = None):
            """市价开多并设置止盈止损"""
            try:
                # 2. 计算下单数量
                quantity = self.calculate_quantity(symbol, usdt_amount)
                logging.info(f"下单数量: {quantity}")
                
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                logging.info(f"当前市价: {current_price}")
                
                # 4. 执行市价开多订单
                open_params = {
                    'symbol': symbol,
                    'side': 'BUY',
                    'type': 'MARKET',
                    'quantity': quantity
                }
                
                response = self.rest_client.new_order(**open_params)
                logging.info(f"开仓订单响应: {response}")
                
                # 5. 设置止盈单
                if tp_percent:
                    tp_price = self.round_price(current_price * (1 + tp_percent/100), symbol)
                    logging.info(f"止盈价格: {tp_price}")
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
                    logging.info(f"止盈订单响应: {tp_response}")
                
                # 6. 设置止损单
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 - sl_percent/100), symbol)
                    logging.info(f"止损价格: {sl_price}")
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
                    logging.info(f"止损订单响应: {sl_response}")
                
                return {
                    'open_order': response,
                    'tp_order': tp_response if tp_percent else None,
                    'sl_order': sl_response if sl_percent else None
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

    def market_open_short_with_tp_sl(self, symbol: str, usdt_amount: float,
                                    tp_percent: float = None, sl_percent: float = None):
            """市价开空并设置止盈止损"""
            try:
                # 2. 计算下单数量
                quantity = self.calculate_quantity(symbol, usdt_amount)
                logging.info(f"下单数量: {quantity}")
                
                # 3. 获取当前市价
                current_price = self.get_symbol_price(symbol)
                logging.info(f"当前市价: {current_price}")
                
                # 4. 执行市价开空订单
                open_params = {
                    'symbol': symbol,
                    'side': 'SELL',
                    'type': 'MARKET',
                    'quantity': quantity
                }
                
                response = self.rest_client.new_order(**open_params)
                logging.info(f"开仓订单响应: {response}")
                
                # 5. 设置止盈单
                if tp_percent:
                    tp_price = self.round_price(current_price * (1 - tp_percent/100), symbol)
                    logging.info(f"止盈价格: {tp_price}")
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
                    logging.info(f"止盈订单响应: {tp_response}")
                
                # 6. 设置止损单
                if sl_percent:
                    sl_price = self.round_price(current_price * (1 + sl_percent/100), symbol)
                    logging.info(f"止损价格: {sl_price}")
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
                    logging.info(f"止损订单响应: {sl_response}")
                
                return {
                    'open_order': response,
                    'tp_order': tp_response if tp_percent else None,
                    'sl_order': sl_response if sl_percent else None
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

    def get_position(self, symbol: str):
        """获取单个交易对持仓信息"""
        try:
            positions = self.rest_client.get_position_risk()
            return next((p for p in positions if p['symbol'] == symbol), None)
        except Exception as e:
            logging.error(f"获取持仓信息失败: {e}")
            raise

    def get_all_positions(self):
        try:
            positions = self.rest_client.get_position_risk()
            return positions
        except Exception as e:
            logging.error(f"获取持仓信息失败: {e}")
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
        except Exception as e:
            logging.error(f"发送Telegram消息失败: {e}")

async def main():
    try:
        # 从配置获取API密钥
        config = ConfigLoader()
        api_key = config.get('binance_api_key')
        api_secret = config.get('binance_api_secret')

        # 初始化交易器
        trader = USDTFuturesTraderManager(api_key, api_secret)
        
        # 启动WebSocket监控
        trader.start_ws_monitor()
        
        # 发送启动消息
        await trader.send_telegram_message("🤖 交易机器人启动\n监控开始！")
        
        # 启动消息处理任务
        message_processor = asyncio.create_task(trader.process_message_queue())
        
        # 保持程序运行
        await asyncio.gather(message_processor)
        
    except KeyboardInterrupt:
        logging.info("程序已手动停止")
    except Exception as e:
        logging.error(f"程序发生错误: {e}")
        logging.exception(e)
    finally:
        if trader.ws_client:
            trader.ws_client.stop()
