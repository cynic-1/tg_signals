import telegram
import logging

class TelegramService:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        
    async def send_message(self, message: str):
        try:
            bot = telegram.Bot(token=self.bot_token)
            max_length = 4096
            
            for i in range(0, len(message), max_length):
                chunk = message[i:i + max_length]
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=chunk,
                    parse_mode='HTML'
                )
        except Exception as e:
            logging.error(f"发送Telegram消息时出错: {e}")