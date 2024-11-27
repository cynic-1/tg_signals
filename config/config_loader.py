import os
from dotenv import load_dotenv
from typing import Dict

class ConfigLoader:
    @staticmethod
    def load_from_env() -> Dict[str, str]:
        """从.env文件加载配置"""
        load_dotenv()
        
        required_keys = [
            'TELEGRAM_BOT_TOKEN',
            'TELEGRAM_CHAT_ID',
            'TELEGRAM_CHAT_ID_SELF',
            'BINANCE_API_KEY',
            'BINANCE_API_SECRET',
            'BYBIT_API_KEY',
            'BYBIT_API_SECRET'
        ]
        
        config = {}
        for key in required_keys:
            value = os.getenv(key)
            if value is None:
                raise ValueError(f"Missing required environment variable: {key}")
            config[key] = value
            
        return config