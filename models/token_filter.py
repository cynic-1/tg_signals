from typing import Dict, List, Tuple, Set
import logging
import pandas as pd
from pathlib import Path
from utils import setup_logger, SignalTracker

class TokenFilter:
    def __init__(self):
        self.logger = setup_logger('Token Filter')
        self.major_exchanges: Set[str] = {'bybit', 'binance', 'okx'}
        self.change_threshold_5min: float = 5
        self.change_threshold_1min: float = 2
        self.token_tags = self._load_token_tags()
                
        # 初始化信号追踪器
        self.signal_tracker = SignalTracker(expiry_minutes=30)

    def _load_token_tags(self) -> Dict[str, str]:
        """
        从CSV文件加载token的tags
        
        Returns:
            Dict[str, str]: token symbol到tags的映射
        """
        try:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent
            csv_path = project_root / 'data' / 'crypto_data.csv'
            
            # 读取CSV文件
            df = pd.read_csv(csv_path)
            
            # 确保Tags列中的NaN值被替换为空字符串
            df['Tags'] = df['Tags'].fillna('').astype(str)
            
            # 创建symbol到tags的映射
            tags_dict = dict(zip(df['symbol'], df['Tags']))
            self.logger.info(f"Successfully loaded {len(tags_dict)} token tags")
            return tags_dict
            
        except Exception as e:
            self.logger.error(f"Error loading token tags: {e}")
            return {} 
            
    def check_exchange_requirement(self, token: Dict) -> bool:
        """检查交易所要求"""
        token_exchanges = set(token['symbols'].keys()) if 'symbols' in token else set()
        return bool(token_exchanges.intersection(self.major_exchanges))
        
    def check_price_change(self, token: Dict) -> bool:
        """检查价格变化要求"""
        if 'performance' in token and 'min5' in token['performance'] and 'min1' in token['performance']:
            min5_change = token['performance']['min5']
            min1_change = token['performance']['min1']
            return abs(min5_change) > self.change_threshold_5min or abs(min1_change) > self.change_threshold_1min
        return False
        
    def check_volume_change(self, token: Dict) -> bool:
        """检查交易量要求"""
        return token['volume'] > 5000000
    
        
    def apply_filters(self, token: Dict) -> bool:
        """应用所有筛选条件"""
        filters = [
            self.check_exchange_requirement,
            self.check_price_change,
            self.check_volume_change
        ]
        
        return all(f(token) for f in filters)
        
    def filter_tokens_by_conditions(self, data: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """主筛选函数"""
        gainers = []
        losers = []
        
        if not data:
            return [], []
            
        for token in data:
            if self.apply_filters(token):
                token_info = self._prepare_token_info(token)
                min5_change = token['performance']['min5']

                if self.signal_tracker.has_recent_signal(token['symbol']):
                    self.signal_tracker.add_signal(token['symbol'])
                    self.logger.info(f"跳过 {token['symbol']} - 30分钟内有信号")
                    continue

                if min5_change > 0:
                    gainers.append(token_info)
                else:
                    losers.append(token_info)
                self.signal_tracker.add_signal(token['symbol'])
                    
        gainers.sort(key=lambda x: x['performance']['min5'], reverse=True)
        losers.sort(key=lambda x: x['performance']['min5'])
        
        return gainers, losers
        
    def _prepare_token_info(self, token: Dict) -> Dict:
        """准备token信息"""
        symbol = self._get_symbol_from_dict(token)
        return {
            'name': token['name'],
            'symbol': symbol,
            'rank': token['rank'],
            'price': token['price'],
            'marketcap': "{:,}".format(token['marketcap']),
            'volume': "{:,}".format(token['volume']),
            'performance': token['performance'],
            'exchanges': list(token['symbols'].keys()) if 'symbols' in token else [],
            'tags': self.token_tags.get(token['symbol'], '')
        }
        
    def _get_symbol_from_dict(self, token_data: Dict) -> str:
        """获取交易对符号"""
        symbols = token_data.get('symbols', {})
        
        if not symbols:
            return ""
            
        symbol = (
            symbols.get('binance') or
            next(iter(symbols.values()))
        )
        
        return symbol.replace('_', '').replace('USDT', '').replace('-', '').replace('/', '').replace('USD', '')
