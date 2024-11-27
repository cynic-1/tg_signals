import logging
from typing import Dict
import asyncio

from traders.binance_futures_trader import BinanceUSDTFuturesTraderManager
from traders.bybit_futures_trader import BybitUSDTFuturesTraderManager
from utils.logger import setup_logger

class TradingExecutor:
    def __init__(self, 
                 api_key_bn: str, 
                 api_secret_bn: str, 
                 api_key_bb: str, 
                 api_secret_bb: str, 
                 leverage: int, 
                 usdt_amount: float, 
                 tp_percent: float, 
                 sl_percent: float, 
                 bot_token: str, 
                 chat_id: str):
        """
        初始化交易执行器
        
        Args:
            api_key_bn: Binance API key
            api_secret_bn: Binance API secret
            api_key_bb: Bybit API key
            api_secret_bb: Bybit API secret
            leverage: 杠杆倍数
            usdt_amount: 交易金额(USDT)
            tp_percent: 止盈百分比
            sl_percent: 止损百分比
            bot_token: Telegram bot token
            chat_id: Telegram chat ID
        """
        self.logger = setup_logger('trading_executor')
        
        # 初始化交易所管理器
        self.binance_trader = BinanceUSDTFuturesTraderManager(
            api_key=api_key_bn, 
            api_secret=api_secret_bn, 
            bot_token=bot_token, 
            chat_id=chat_id
        )
        self.bybit_trader = BybitUSDTFuturesTraderManager(
            testnet=False,
            api_key=api_key_bb,
            api_secret=api_secret_bb,
            bot_token=bot_token,
            chat_id=chat_id
        )
        
        # 交易参数
        self.leverage = leverage
        self.usdt_amount = usdt_amount
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent

    async def send_trading_message(self, message: str):
        """
        发送Telegram消息
        
        Args:
            message: 消息内容
        """
        try:
            positions_info = self.get_positions_info()
            full_message = f"{message}\n\n📊 当前持仓信息:\n{positions_info}"
            
            await self.binance_trader.send_telegram_message(
                message=full_message,
            )
            self.logger.info(f"已发送Telegram消息: {full_message}")
        except Exception as e:
            self.logger.error(f"发送Telegram消息失败: {e}")

    async def execute_long(self, token: Dict) -> None:
        """
        执行做多交易
        
        Args:
            token: 代币信息
        """
        try:
            # 检查必要的字段
            if 'symbol' not in token:
                self.logger.error("Token missing symbol field")
                return
                
            symbol = f"{token['symbol']}USDT"

            # 尝试在Binance开仓
            if self.binance_trader.has_trade_pair(symbol=symbol):
                if self.binance_trader.has_position(symbol=symbol):
                    self.logger.debug(f"Binance 已有持仓 {symbol}")
                    return
                
                self.binance_trader.new_order(
                    leverage=self.leverage,
                    symbol=symbol,
                    usdt_amount=self.usdt_amount,
                    tp_percent=self.tp_percent,
                    sl_percent=self.sl_percent,
                    long=True
                )
                return
            
            self.logger.debug(f"Binance 无交易对 {symbol}")

            # 尝试在Bybit开仓
            if self.bybit_trader.has_trade_pair(symbol=symbol):
                if self.bybit_trader.has_position(symbol=symbol):
                    self.logger.debug(f"Bybit 已有持仓 {symbol}")
                    return
        
                self.bybit_trader.new_order(
                    leverage=self.leverage,
                    symbol=symbol,
                    usdt_amount=self.usdt_amount,
                    tp_percent=self.tp_percent,
                    sl_percent=self.sl_percent,
                    long=True
                )
                return
            
            self.logger.debug(f"Bybit 无交易对 {symbol}")
        
        except Exception as e:
            self.logger.error(f"做多开仓失败 {symbol if 'symbol' in locals() else 'unknown'}: {e}")


    async def stop(self):
        """停止交易执行器"""
        if self.binance_trader.ws_client:
            self.binance_trader.ws_client.stop()
        if self.bybit_trader.ws_client:
            self.bybit_trader.ws_client.stop()