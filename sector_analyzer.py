from typing import Dict, List, Tuple
import logging
from pathlib import Path
import pandas as pd
import requests
import time

def load_token_tags() -> Dict[str, str]:
    """从CSV文件加载token的tags"""
    try:
        project_root = Path(__file__).parent  # 获取项目根目录
        csv_path = project_root / 'data' / 'crypto_data.csv'
        df = pd.read_csv(csv_path)
        # 创建id到tags的映射
        return dict(zip(df['symbol'], df['Tags']))
    except Exception as e:
        logging.error(f"Error loading tags: {e}")
        return {}

def get_crypto_data() -> List[Dict]:
    url = "https://cryptobubbles.net/backend/data/bubbles1000.usd.json"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        return []

class SectorAnalyzer:
    def __init__(self):
        self.sectors = {}
        self.token_tags = load_token_tags()

    def format_symbol(self, data: List[Dict]) -> List[Dict]:
        def get_symbol_from_dict(token_data: dict) -> str:
            """
            从token数据中获取交易对符号
            1. 优先获取 binance 的交易对
            2. 如果没有 binance，则获取第一个可用的交易对
            3. 移除交易对中的下划线
            """
            symbols = token_data.get('symbols', {})
            
            # 获取交易对名称（优先binance，否则第一个）
            if not symbols:
                return ""
                
            symbol = (
                symbols.get('binance') or  # 尝试获取 binance 的交易对
                next(iter(symbols.values()))  # 如果没有 binance，获取第一个交易对
            )
            
            # 移除下划线
            return symbol.replace('_', '').replace('USDT', '').replace('-', '').replace('/', '')

        for token in data:
            token['symbol'] = get_symbol_from_dict(token_data=token)
        return data


    def analyze_sectors(self, data: List[Dict]) -> Dict:
        # 初始化板块数据结构
        sector_data = {}
        
        for token in data:
            try:
                # 获取token的tags，如果没有tags则跳过
                tags = self.token_tags.get(token['symbol'], '')
                if not tags:
                    continue
                    
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
                if not tags:  # 如果分割后没有有效的tag，也跳过
                    continue
                
                # 获取token的基础数据
                marketcap = token.get('marketcap', 0)
                if not marketcap:  # 如果没有市值数据，跳过
                    continue
                    
                performance = token.get('performance', {})
                symbol = token.get('symbol', '')
                name = token.get('name', '')
                price = token.get('price', 0)
                
                # 获取各个时间段的涨跌幅
                perf_periods = {
                    'min5': performance.get('min5', 0),
                    'hour': performance.get('hour', 0),
                    'day': performance.get('day', 0),
                    'week': performance.get('week', 0),
                    'month': performance.get('month', 0)
                }
                
                # 为每个tag更新数据
                for tag in tags:
                    if tag not in sector_data:
                        sector_data[tag] = {
                            'total_marketcap': 0,
                            'weighted_performance': {
                                'min5': 0,
                                'hour': 0,
                                'day': 0,
                                'week': 0,
                                'month': 0
                            },
                            'token_count': 0,
                            'top_performers': {  # 新增：记录每个时间段表现最好的代币
                                'min5': [],
                                'hour': [],
                                'day': [],
                                'week': [],
                                'month': []
                            }
                        }
                    
                    # 更新板块数据
                    sector_data[tag]['total_marketcap'] += marketcap
                    sector_data[tag]['token_count'] += 1
                    
                    # 更新加权涨跌幅
                    for period in perf_periods:
                        sector_data[tag]['weighted_performance'][period] += (
                            perf_periods[period] * marketcap
                        )
                        
                        # 更新top performers
                        token_info = {
                            'symbol': symbol,
                            'name': name,
                            'performance': perf_periods[period],
                            'price': price,
                            'marketcap': marketcap
                        }
                        
                        performers = sector_data[tag]['top_performers'][period]
                        performers.append(token_info)
                        # 按涨幅排序并只保留前三名
                        performers.sort(key=lambda x: x['performance'], reverse=True)
                        sector_data[tag]['top_performers'][period] = performers[:3]
                        
            except Exception as e:
                logging.warning(f"Error processing token: {token.get('symbol', 'Unknown')}, Error: {str(e)}")
                continue
        
        # 计算最终的加权平均值
        result = {}
        for sector, data in sector_data.items():
            if data['total_marketcap'] > 0:
                result[sector] = {
                    'marketcap': data['total_marketcap'],
                    'token_count': data['token_count'],
                    'performance': {
                        period: data['weighted_performance'][period] / data['total_marketcap']
                        for period in data['weighted_performance']
                    },
                    'top_performers': data['top_performers']  # 包含top performers在结果中
                }
        
        # 按总市值排序
        sorted_sectors = dict(sorted(
            result.items(),
            key=lambda x: x[1]['marketcap'],
            reverse=True
        ))
        
        return sorted_sectors
    
    def get_top_sectors(self, sector_data: Dict, period: str = 'min5', top_n: int = 3) -> Dict:
        """
        获取指定时间段涨幅最大的前N个板块
        
        Args:
            sector_data: 板块分析数据
            period: 时间段 ('min5', 'hour', 'day', 'week', 'month')
            top_n: 返回的板块数量
            
        Returns:
            Dict: 筛选后的板块数据
        """
        # 按指定时间段的涨跌幅排序
        sorted_sectors = dict(sorted(
            sector_data.items(),
            key=lambda x: x[1]['performance'][period],
            reverse=True
        ))
        
        # 只返回前N个板块
        return dict(list(sorted_sectors.items())[:top_n])
    
    def format_sector_analysis(self, sector_data: Dict, main_period: str = 'min5') -> str:
        """
        格式化板块分析结果
        
        Args:
            sector_data: 板块分析数据
            main_period: 主时间段，根据其排序
        """
        if not sector_data:
            return "没有符合条件的板块数据"
            
        output = []
        output.append("板块分析报告:")
        output.append("=" * 80)
        
        # 定义所有可能的时间段及其显示名称
        periods = {
            'min5': '5分钟',
            'min15': '15分钟',
            'hour': '1小时',
            'day': '24小时',
            'week': '7天',
            'month': '30天'
        }
               
        for sector, data in sector_data.items():
            perf = data['performance']
            output.append(f"\n【{sector}】")
            output.append(f"总市值: ${data['marketcap']:,.0f}")
            output.append(f"代币数量: {data['token_count']}")
            output.append("\n涨跌幅:")
            
            # 所有时间段涨跌幅概览
            output.append("\n涨跌幅概览:")
            perf_overview = []
            for period, period_name in periods.items():
                if period in perf:
                    perf_overview.append(f"{period_name}: {perf[period]:+.2f}%")
            output.append(" | ".join(perf_overview))
            
            # 主时间段的详细信息（包括top performers）
            output.append(f"\n{periods[main_period]}涨幅最大代币:")
            for idx, token in enumerate(data['top_performers'][main_period], 1):
                output.append(
                    f"  {idx}. {token['symbol']} ({token['name']}): "
                    f"{token['performance']:+.2f}% "
                    f"价格: ${token['price']:.4f} "
                    f"市值: ${token['marketcap']:,.0f}"
                )
            
        output.append("-" * 80)
        
        return "\n".join(output)

    def analyze_market_sectors(self, data: List[Dict], period: str = 'min5', top_n: int = 3):
        """
        市场板块分析主函数
        
        Args:
            data: 原始市场数据
            period: 分析的时间段
            top_n: 显示的板块数量
        """
        try:
            # 获取完整的板块分析
            all_sectors = self.analyze_sectors(data)
            
            # 获取涨幅最大的前N个板块
            top_sectors = self.get_top_sectors(all_sectors, period=period, top_n=top_n)
            
            # 格式化并返回结果
            return self.format_sector_analysis(top_sectors, main_period=period)
            
        except Exception as e:
            logging.error(f"Error in market sector analysis: {str(e)}")
            return f"分析过程中发生错误: {str(e)}"
        
data = get_crypto_data()
# start_time = time.time()
sa = SectorAnalyzer()
data_with_tags = sa.format_symbol(data=data)
result = sa.analyze_market_sectors(data=data_with_tags)
# execution_time = time.time() - start_time   
# print(f"本次执行耗时: {execution_time:.2f}秒")
print(result)
