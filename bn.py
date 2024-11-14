import logging
from binance.um_futures import UMFutures
from config import ConfigLoader


class USDTFuturesTrader:
    def __init__(self, config=None):
        """
        初始化交易器
        config: 包含API配置的字典，如果为None则从环境变量加载
        """
        if config is None:
            config = ConfigLoader.load_from_env()

        if not config or 'api_key' not in config or 'api_secret' not in config:
            raise ValueError("未找到有效的API配置")

        self.client = UMFutures(
            key=config['api_key'],
            secret=config['api_secret']
        )

    def open_position_with_sl_tp(self, symbol: str, side: str, quantity: float,
                                 stop_loss_price: float, take_profit_price: float,
                                 order_type: str = 'MARKET', price: float = None) -> dict:
        """
        开仓同时设置止盈止损

        参数:
            symbol (str): 交易对名称，如 'BTCUSDT'
            side (str): 交易方向，'BUY' 或 'SELL'
            quantity (float): 交易数量
            stop_loss_price (float): 止损价格
            take_profit_price (float): 止盈价格
            order_type (str): 订单类型，'MARKET' 或 'LIMIT'
            price (float): 限价单价格，市价单时为None

        返回:
            dict: 交易所返回的订单信息
        """
        try:
            if side == 'BUY':
                stop_loss_params = {
                    'stopPrice': stop_loss_price,
                    'type': 'STOP_MARKET',
                    'side': 'SELL',
                    'quantity': quantity,
                    'workingType': 'CONTRACT_PRICE'
                }
                take_profit_params = {
                    'stopPrice': take_profit_price,
                    'type': 'TAKE_PROFIT_MARKET',
                    'side': 'SELL',
                    'quantity': quantity,
                    'workingType': 'CONTRACT_PRICE'
                }
            else:
                stop_loss_params = {
                    'stopPrice': stop_loss_price,
                    'type': 'STOP_MARKET',
                    'side': 'BUY',
                    'quantity': quantity,
                    'workingType': 'CONTRACT_PRICE'
                }
                take_profit_params = {
                    'stopPrice': take_profit_price,
                    'type': 'TAKE_PROFIT_MARKET',
                    'side': 'BUY',
                    'quantity': quantity,
                    'workingType': 'CONTRACT_PRICE'
                }

            params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity,
                'reduceOnly': False,
                'stopLoss': stop_loss_params,
                'takeProfit': take_profit_params
            }

            if order_type == 'LIMIT':
                params['price'] = price
                params['timeInForce'] = 'GTC'

            response = self.client.new_order(**params)
            return response

        except Exception as e:
            logging.error(f"下单错误: {e}")
            raise

    def market_order(self, symbol: str, side: str, quantity: float, reduce_only: bool = False) -> dict:
        """
        市价单交易

        参数:
            symbol (str): 交易对名称
            side (str): 交易方向，'BUY' 或 'SELL'
            quantity (float): 交易数量
            reduce_only (bool): 是否只减仓
        """
        try:
            params = {
                'symbol': symbol,
                'side': side,
                'type': 'MARKET',
                'quantity': quantity,
                'reduceOnly': reduce_only
            }
            return self.client.new_order(**params)
        except Exception as e:
            logging.error(f"市价单交易错误: {e}")
            raise

    def limit_order(self, symbol: str, side: str, quantity: float,
                    price: float, reduce_only: bool = False) -> dict:
        """
        限价单交易

        参数:
            symbol (str): 交易对名称
            side (str): 交易方向，'BUY' 或 'SELL'
            quantity (float): 交易数量
            price (float): 限价单价格
            reduce_only (bool): 是否只减仓
        """
        try:
            params = {
                'symbol': symbol,
                'side': side,
                'type': 'LIMIT',
                'quantity': quantity,
                'price': price,
                'timeInForce': 'GTC',
                'reduceOnly': reduce_only
            }
            return self.client.new_order(**params)
        except Exception as e:
            logging.error(f"限价单交易错误: {e}")
            raise

    def get_position(self, symbol: str) -> dict:
        """
        获取指定交易对的持仓信息

        参数:
            symbol (str): 交易对名称
        """
        try:
            positions = self.client.get_position_risk()
            for position in positions:
                if position['symbol'] == symbol:
                    return position
            return None
        except Exception as e:
            logging.error(f"获取持仓信息错误: {e}")
            raise

    def change_leverage(self, symbol: str, leverage: int) -> dict:
        """
        修改杠杆倍数

        参数:
            symbol (str): 交易对名称
            leverage (int): 目标杠杆倍数
        """
        try:
            return self.client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )
        except Exception as e:
            logging.error(f"修改杠杆倍数错误: {e}")
            raise

    def change_margin_type(self, symbol: str, margin_type: str) -> dict:
        """
        修改保证金类型

        参数:
            symbol (str): 交易对名称
            margin_type (str): 保证金类型，'ISOLATED' 或 'CROSSED'
        """
        try:
            return self.client.change_margin_type(
                symbol=symbol,
                marginType=margin_type
            )
        except Exception as e:
            logging.error(f"修改保证金类型错误: {e}")
            raise

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """
        取消订单

        参数:
            symbol (str): 交易对名称
            order_id (int): 订单ID
        """
        try:
            return self.client.cancel_order(
                symbol=symbol,
                orderId=order_id
            )
        except Exception as e:
            logging.error(f"取消订单错误: {e}")
            raise

    def get_account_info(self):
        """获取账户信息"""
        return self.client.account()


# 使用示例
if __name__ == "__main__":
    try:
        # 初始化交易器
        trader = USDTFuturesTrader()

        print("账户：", trader.get_account_info())

        # 交易参数
        symbol = 'BTCUSDT'

        position = trader.get_position(symbol)
        print("当前持仓:", position)

        # 设置杠杆
        trader.change_leverage(symbol, 3)

        # 设置逐仓模式
        trader.change_margin_type(symbol, 'ISOLATED')

        # 开仓示例（带止盈止损）
        response = trader.open_position_with_sl_tp(
            symbol=symbol,
            side='BUY',
            quantity=0.001,
            stop_loss_price=40000,
            take_profit_price=45000
        )
        print("开仓响应:", response)

        # 查看持仓
        position = trader.get_position(symbol)
        print("当前持仓:", position)

        # 市价单示例
        response = trader.market_order(
            symbol=symbol,
            side='SELL',
            quantity=0.001,
            reduce_only=True
        )
        print("市价单响应:", response)

    except Exception as e:
        print(f"交易错误: {e}")