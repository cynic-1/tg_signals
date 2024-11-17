import os
import json
import yaml
import logging
from dotenv import load_dotenv


class ConfigLoader:
    @staticmethod
    def load_from_env():
        """从环境变量加载配置"""
        load_dotenv()  # 加载 .env 文件
        return {
            'api_key': os.getenv('BINANCE_API_KEY'),
            'api_secret': os.getenv('BINANCE_API_SECRET'),
            'ct_api_key': os.getenv('COPY_TRADE_API_KEY'),
            'ct_api_secret': os.getenv('COPY_TRADE_API_SECRET'),
            'TELEGRAM_BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN'),
            'TELEGRAM_CHAT_ID': os.getenv('TELEGRAM_CHAT_ID'),
            'TELEGRAM_CHAT_ID_SELF': os.getenv('TELEGRAM_CHAT_ID_SELF')
        }

    @staticmethod
    def load_from_json(file_path='config.json'):
        """从JSON文件加载配置"""
        try:
            with open(file_path, 'r') as f:
                config = json.load(f)
            return config
        except Exception as e:
            logging.error(f"加载JSON配置文件错误: {e}")
            return None

    @staticmethod
    def load_from_yaml(file_path='config.yaml'):
        """从YAML文件加载配置"""
        try:
            with open(file_path, 'r') as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e:
            logging.error(f"加载YAML配置文件错误: {e}")
            return None