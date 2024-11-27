from typing import List, Dict

class ExchangeHandler:
    def __init__(self):
        """初始化交易所优先级顺序"""
        self.exchange_order = {
            'binance': 1,
            'bybit': 2,
            'okx': 3,
            'coinbase': 4,
            'kraken': 5,
            'kucoin': 6,
            'gateio': 7,
            'bitget': 8,
            'htx': 9,
            'bingx': 10,
            'bitmart': 11,
            'mexc': 12
        }

    def sort_exchanges(self, exchanges: List[str]) -> List[str]:
        """按预定义顺序排序交易所"""
        return sorted(exchanges, key=lambda x: self.exchange_order.get(x, float('inf')))

    def get_preferred_exchange(self, available_exchanges: List[str]) -> str:
        """获取优先级最高的交易所"""
        if not available_exchanges:
            return None
            
        sorted_exchanges = self.sort_exchanges(available_exchanges)
        return sorted_exchanges[0] if sorted_exchanges else None

    def is_major_exchange(self, exchange: str) -> bool:
        """检查是否为主要交易所"""
        return self.exchange_order.get(exchange, float('inf')) <= 3

    def get_exchange_tier(self, exchange: str) -> int:
        """获取交易所等级"""
        return self.exchange_order.get(exchange, float('inf'))

    @property
    def major_exchanges(self) -> List[str]:
        """获取所有主要交易所列表"""
        return [ex for ex, order in self.exchange_order.items() if order <= 3]

    def get_exchange_info(self, exchange: str) -> Dict:
        """获取交易所详细信息"""
        return {
            'name': exchange,
            'tier': self.get_exchange_tier(exchange),
            'is_major': self.is_major_exchange(exchange),
            'order': self.exchange_order.get(exchange, float('inf'))
        }