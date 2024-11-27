import asyncio
import logging
from pathlib import Path
from typing import Dict

from config import ConfigLoader
from services import CryptoDataService, TelegramService, MessageFormatter
from models import TokenFilter
from trading import TradingExecutor
from utils import setup_logger

class TradingBot:
    def __init__(self, config: Dict):
        """
        初始化交易机器人
        
        Args:
            config: 配置信息
        """
        # 设置日志
        self.logger = setup_logger('trading_bot')
        
        # 初始化服务
        self.telegram_service = TelegramService(
            bot_token=config['TELEGRAM_BOT_TOKEN'],
            chat_id=config['TELEGRAM_CHAT_ID']
        )
        
        self.crypto_service = CryptoDataService()
        self.message_formatter = MessageFormatter()
        self.token_filter = TokenFilter()
        
        # 初始化交易执行器
        self.trading_executor = TradingExecutor(
            api_key_bn=config['BINANCE_API_KEY'],
            api_secret_bn=config['BINANCE_API_SECRET'],
            api_key_bb=config['BYBIT_API_KEY'],
            api_secret_bb=config['BYBIT_API_SECRET'],
            leverage=5,
            usdt_amount=100,
            tp_percent=50.0,
            sl_percent=5.0,
            bot_token=config['TELEGRAM_BOT_TOKEN'],
            chat_id=config['TELEGRAM_CHAT_ID_SELF']
        )

        # 交易设置
        self.auto_long = True
        self.auto_short = False

    async def process_market_data(self):
        """处理市场数据并执行交易"""
        try:
            # 获取市场数据
            crypto_data = self.crypto_service.get_crypto_data()
            gainers, losers = self.token_filter.filter_tokens_by_conditions(crypto_data)

            # 执行做多交易
            if self.auto_long:
                for token in gainers:
                    if token['performance']['min1'] > 5 or token['performance']['min5'] > 15:
                        continue

                    await self.trading_executor.execute_long(token)

            # 发送市场监控消息
            message = self.message_formatter.format_message(gainers, losers)
            if message:
                await self.telegram_service.send_message(message)

        except Exception as e:
            self.logger.error(f"处理市场数据时出错: {e}", exc_info=True)

    async def run(self):
        """运行交易机器人"""
        self.logger.info("启动交易机器人")
        
        try:
            # 启动消息处理任务
            message_processor = asyncio.create_task(
                self.trading_executor.binance_trader.process_message_queue()
            )
            message_processor_bybit = asyncio.create_task(
                self.trading_executor.bybit_trader.process_message_queue()
            )

            while True:
                try:
                    await self.process_market_data()
                    await asyncio.sleep(60)  # 每分钟执行一次
                except Exception as e:
                    self.logger.error(f"主循环出错: {e}", exc_info=True)
                    await asyncio.sleep(60)

        except KeyboardInterrupt:
            self.logger.info("收到停止信号，正在关闭...")
        except Exception as e:
            self.logger.error(f"运行出错: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self):
        """停止交易机器人"""
        self.logger.info("正在停止交易机器人...")
        await self.trading_executor.stop()
        self.logger.info("交易机器人已停止")

async def main():
    """主函数"""
    try:
        # 加载配置
        config = ConfigLoader.load_from_env()
        
        # 创建并运行交易机器人
        bot = TradingBot(config)
        await bot.run()
        
    except Exception as e:
        logging.error(f"程序运行出错: {e}", exc_info=True)
    finally:
        logging.info("程序已退出")

if __name__ == "__main__":
    # 运行主函数
    asyncio.run(main())