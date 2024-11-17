import logging
from binance.um_futures import UMFutures
from config import ConfigLoader
from timer import PerformanceTimer


class USDTFuturesTrader:
    def __init__(self, api_key, api_secret):
        self.client = UMFutures(
            key=api_key,
            secret=api_secret
        )

        self.performance_timer = PerformanceTimer()

    def get_symbol_info(self, symbol: str) -> dict:
        """获取交易对信息（包含精度等）"""
        try:
            exchange_info = self.client.exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            if not symbol_info:
                raise ValueError(f"未找到交易对 {symbol} 的信息")
            return symbol_info
        except Exception as e:
            logging.error(f"获取交易对信息失败: {e}")
            raise

    def get_symbol_price(self, symbol: str) -> float:
        """获取当前市价"""
        try:
            ticker = self.client.ticker_price(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logging.error(f"获取价格失败: {e}")
            raise

    def calculate_quantity(self, symbol: str, usdt_amount: float) -> float:
        """计算下单数量"""
        try:
            # 获取交易对信息
            symbol_info = self.get_symbol_info(symbol)
            
            # 获取数量精度
            quantity_precision = next(
                (int(filter['stepSize'].find('1') - 1)
                 for filter in symbol_info['filters']
                 if filter['filterType'] == 'LOT_SIZE'),
                4  # 默认精度
            )
            
            # 获取最小下单量
            min_qty = float(next(
                (filter['minQty']
                 for filter in symbol_info['filters']
                 if filter['filterType'] == 'LOT_SIZE'),
                0
            ))

            # 获取当前价格
            price = self.get_symbol_price(symbol)
            logging.info(f"现价: {price}")
            
            # 计算数量
            quantity = usdt_amount / price
            logging.info(f"下单量: {quantity}")
            
            # 根据精度截断
            quantity = round(quantity, quantity_precision)
            
            # 确保大于最小下单量
            if quantity < min_qty:
                raise ValueError(f"计算得到的数量 {quantity} 小于最小下单量 {min_qty}")
                
            return quantity

        except Exception as e:
            logging.error(f"计算下单数量失败: {e}")
            raise

    def market_open_long(self, symbol: str, usdt_amount: float):
        """市价开多（使用USDT金额）"""
        try:
            # 计算下单数量
            quantity = self.calculate_quantity(symbol, usdt_amount)
            logging.info(f"下单数量: {quantity}")
            
            # 下单
            params = {
                'symbol': symbol,
                'side': 'BUY',
                'type': 'MARKET',
                'quantity': quantity
            }
            response = self.client.new_order(**params)
            logging.info(f"市价开多响应: {response}")
            return response
        except Exception as e:
            logging.error(f"市价开多失败: {e}")
            raise

    def market_open_short(self, symbol: str, usdt_amount: float):
        """市价开空（使用USDT金额）"""
        try:
            # 计算下单数量
            quantity = self.calculate_quantity(symbol, usdt_amount)
            logging.info(f"下单数量: {quantity}")
            
            # 下单
            params = {
                'symbol': symbol,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': quantity
            }
            response = self.client.new_order(**params)
            logging.info(f"市价开空响应: {response}")
            return response
        except Exception as e:
            logging.error(f"市价开空失败: {e}")
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
                response = self.client.new_order(**params)
                logging.info(f"平仓响应: {response}")
                return response
            else:
                logging.info("没有持仓，无需平仓")
                return None
        except Exception as e:
            logging.error(f"平仓失败: {e}")
            raise

    def get_position(self, symbol: str):
        """获取持仓信息"""
        try:
            positions = self.client.get_position_risk()
            for position in positions:
                if position['symbol'] == symbol:
                    return position
            return None
        except Exception as e:
            logging.error(f"获取持仓信息失败: {e}")
            raise

    def get_all_positions(self):
        try:
            positions = self.client.get_position_risk()
            return positions
        except Exception as e:
            logging.error(f"获取持仓信息失败: {e}")
            raise

    def get_account_details(self):
        """获取账户信息"""
        try:
            account = self.client.account()
            logging.info("账户信息:")
            logging.info(f"总钱包余额: {account['totalWalletBalance']} USDT")
            logging.info(f"可用余额: {account['availableBalance']} USDT")
            
            # 显示各个资产的余额
            for asset in account['assets']:
                if float(asset['walletBalance']) > 0:
                    logging.info(f"{asset['asset']} 余额: {asset['walletBalance']}")
            
            return account
        except Exception as e:
            logging.error(f"获取账户信息失败: {e}")
            raise

    def set_leverage(self, symbol: str, leverage: int):
        """设置杠杆倍数"""
        try:
            response = self.client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logging.info(f"设置杠杆响应: {response}")
            return response
        except Exception as e:
            logging.error(f"设置杠杆失败: {e}")
            raise

    def get_symbol_info(self, symbol: str) -> dict:
        """获取交易对信息（包含精度等）"""
        try:
            exchange_info = self.client.exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            if not symbol_info:
                raise ValueError(f"未找到交易对 {symbol} 的信息")
            return symbol_info
        except Exception as e:
            logging.error(f"获取交易对信息失败: {e}")
            raise

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

    def round_price(self, price: float, symbol: str) -> float:
        """按照交易对精度四舍五入价格"""
        precision = self.get_price_precision(symbol)
        return round(price, precision)

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
                
                response = self.client.new_order(**open_params)
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
                    tp_response = self.client.new_order(**tp_params)
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
                    sl_response = self.client.new_order(**sl_params)
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
                
                response = self.client.new_order(**open_params)
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
                    tp_response = self.client.new_order(**tp_params)
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
                    sl_response = self.client.new_order(**sl_params)
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

# 使用示例
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        trader = USDTFuturesTrader()
        symbol = 'BTCUSDT'
        
        # 设置杠杆
        trader.set_leverage(symbol, 10)
        
        # 使用100 USDT开多，设置10%止盈，5%止损
        response = trader.market_open_long_with_tp_sl(
            symbol=symbol,
            usdt_amount=200,
            tp_percent=10.0,  # 10%止盈
            sl_percent=5.0   # 5%止损
        )
        logging.info(f"开仓及止盈止损订单: {response}")
        
        # 查看持仓
        position = trader.get_position(symbol)
        logging.info(f"当前持仓: {position}")
        
    except Exception as e:
        logging.error(f"交易错误: {e}")
