from typing import Dict, List
from datetime import datetime
from models.exchange_handler import ExchangeHandler
import logging

class MessageFormatter:
    def __init__(self):
        self.exchange_handler = ExchangeHandler()
    
    def format_performance(self, perf: Dict) -> str:
        """格式化性能数据"""
        periods = [
            ('min1', '1分钟'),
            ('min5', '5分钟'),
            ('min15', '15分钟'),
            ('hour', '1小时'),
            ('day', '24小时'),
            ('week', '7天'),
            ('month', '30天'),
            ('year', '1年')
        ]
        
        perf_str = []
        for period_key, period_name in periods:
            if period_key in perf and perf[period_key] is not None:
                value = perf[period_key]
                try:
                    value = float(value)
                    sign = '+' if value > 0 else ''
                    perf_str.append(f"{period_name}: {sign}{value:.2f}%")
                except (ValueError, TypeError):
                    perf_str.append(f"{period_name}: N/A")
                    
        return ' | '.join(perf_str)
    
    def format_message(self, gainers: List[Dict], losers: List[Dict]) -> str:
        """格式化完整消息"""
        if not (gainers or losers):
            return None
            
        message = []
        
        # 上涨币种摘要
        if gainers:
            gainer_summary = "🟢 " + ", ".join([
                f"{token['symbol']}(+{token['performance']['min5']:.2f}%)" 
                for token in gainers
            ])
            message.append(gainer_summary)
        
        # 下跌币种摘要
        if losers:
            loser_summary = "🔴 " + ", ".join([
                f"{token['symbol']}({token['performance']['min5']:.2f}%)" 
                for token in losers
            ])
            message.append(loser_summary)
            
        message.append("\n" + "=" * 30 + "\n")
        
        # 详细信息
        if gainers:
            message.append("🟢 详细信息:")
            for token in gainers:
                message.extend(self._format_token_details(token))
                
        if losers:
            message.append('\n🔴 详细信息:')
            for token in losers:
                message.extend(self._format_token_details(token))
                
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message.append(f"\n更新时间: {current_time}")
        
        return '\n'.join(message)
    
    def _format_token_details(self, token: Dict) -> List[str]:
        """
        格式化单个代币详细信息
        
        Args:
            token: 代币信息
            
        Returns:
            List[str]: 格式化后的详细信息列表
        """
        exchanges = token.get('exchanges', [])
        sorted_exchanges = self.exchange_handler.sort_exchanges(exchanges)
        
        # 处理标签
        tags = token.get('tags', '')
        tags_display = ''
        
        # 确保tags是字符串类型且不是空值
        if isinstance(tags, str) and tags.strip():
            try:
                # 分割标签并添加#号
                tag_list = [f"#{tag.strip()}" for tag in tags.split(',') if tag.strip()]
                if tag_list:
                    tags_display = f'<b>标签:</b> {" ".join(tag_list)}'
            except Exception as e:
                logging.error(f"处理标签时出错: {e}, tags: {tags}")
        
        details = [
            f'\n<b>{token["symbol"]}</b> (#{token["rank"]} {token["name"]})',
            f'<b>价格:</b> {token["price"]}',
            f'<b>市值:</b> {token["marketcap"]}',
            f'<b>交易量:</b> {token["volume"]}',
            f'<b>涨跌幅:</b> {self.format_performance(token["performance"])}',
            f'<b>交易所:</b> {", ".join(sorted_exchanges)}'
        ]
        
        if tags_display:
            details.append(tags_display)
            
        details.append('')
        return details

    @staticmethod
    def _format_balance(balance: dict) -> str:
        """格式化单个资产余额信息"""
        return (
            f"💰 {balance['a']}\n"
            f"总余额: {balance['wb']}\n"
            f"全仓余额: {balance['cw']}\n"
            f"变动: {balance.get('bc', '0')}"
        )

    @staticmethod
    def _format_position(position: dict) -> str:
        """格式化单个持仓信息"""
        # 如果没有持仓量，返回简单信息
        if float(position['pa']) == 0:
            return f"📊 {position['s']}: 当前无持仓"

        # 确定持仓方向的emoji
        side_emoji = {
            "LONG": "🟢",
            "SHORT": "🔴",
            "BOTH": "⚪️"
        }.get(position['ps'], "⚪️")

        # 计算ROE（回报率）
        try:
            position_value = abs(float(position['pa']) * float(position['ep']))
            roe = (float(position['up']) / float(position['iw'])) * 100 if float(position['iw']) != 0 else 0
        except (ValueError, ZeroDivisionError):
            roe = 0

        message = (
            f"{side_emoji} {position['s']}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📈 方向: {position['ps']}\n"
            f"📊 数量: {position['pa']}\n"
            f"💰 开仓价: {position['ep']}\n"
            f"💵 损益平衡价: {position['bep']}\n"
            f"📈 已实现盈亏: {position['cr']}\n"
            f"📊 未实现盈亏: {position['up']}\n"
            f"💹 ROE: {roe:.2f}%\n"
            f"🏦 保证金类型: {position['mt']}\n"
        )
        
        # 如果是逐仓，添加逐仓保证金信息
        if position['mt'] == 'isolated':
            message += f"💎 逐仓保证金: {position['iw']}\n"
            
        return message

    @staticmethod
    def _get_event_reason(reason: str) -> str:
        """获取事件原因的描述"""
        reasons = {
            "DEPOSIT": "充值",
            "WITHDRAW": "提现",
            "ORDER": "订单",
            "FUNDING_FEE": "资金费用",
            "WITHDRAW_REJECT": "提现拒绝",
            "ADJUSTMENT": "调整",
            "INSURANCE_CLEAR": "保险基金清算",
            "ADMIN_DEPOSIT": "管理员充值",
            "ADMIN_WITHDRAW": "管理员提现",
            "MARGIN_TRANSFER": "保证金划转",
            "MARGIN_TYPE_CHANGE": "保证金类型变更",
            "ASSET_TRANSFER": "资产划转",
            "OPTIONS_PREMIUM_FEE": "期权权利金",
            "OPTIONS_SETTLE_PROFIT": "期权结算收益",
            "AUTO_EXCHANGE": "自动兑换",
            "COIN_SWAP_DEPOSIT": "币币兑换入金",
            "COIN_SWAP_WITHDRAW": "币币兑换出金"
        }
        return reasons.get(reason, reason)

    @classmethod
    def format_account_update(cls, data: dict) -> str:
        """格式化完整的账户更新信息"""
        try:
            account_data = data['a']
            event_time = datetime.fromtimestamp(data['E'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            # 构建消息头部
            message_parts = [
                f"📡 账户更新\n"
                f"⏰ 时间: {event_time}\n"
                f"📝 原因: {cls._get_event_reason(account_data['m'])}\n"
                f"━━━━━━━━━━━━━━\n"
            ]

            # 添加余额信息
            if account_data.get('B'):
                message_parts.append("💰 余额更新")
                for balance in account_data['B']:
                    message_parts.append(cls._format_balance(balance))

            # 添加持仓信息
            if account_data.get('P'):
                message_parts.append("\n📊 持仓更新")
                
                # 计算总计
                total_realized_pnl = sum(float(p['cr']) for p in account_data['P'])
                total_unrealized_pnl = sum(float(p['up']) for p in account_data['P'])
                
                # 添加每个持仓的信息
                for position in account_data['P']:
                    if float(position['pa']) != 0:  # 只显示有持仓的
                        message_parts.append(cls._format_position(position))
                
                # 添加汇总信息
                message_parts.append(
                    f"\n📊 总计\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"💰 总已实现盈亏: {total_realized_pnl:.2f}\n"
                    f"💵 总未实现盈亏: {total_unrealized_pnl:.2f}\n"
                )

            return "\n".join(message_parts)

        except Exception as e:
            logging.error(f"格式化账户更新信息失败: {e}")
            return f"❌ 格式化消息失败: {str(e)}"
    
    @classmethod
    def format_bybit_trades(cls, trades_data: list[dict]) -> str:
        """格式化Bybit交易数据"""
        def format_single_trade(trade_data: dict) -> str:
            """格式化单个交易数据"""
            # 时间转换
            exec_time = datetime.fromtimestamp(int(trade_data['execTime']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            # 计算成交金额
            total_value = float(trade_data['execValue'])
            
            # 确定交易方向的emoji
            side_emoji = "🔴 卖出" if trade_data['side'] == "Sell" else "🟢 买入"
            
            # 判断是否为做市商
            maker_taker = "做市商" if trade_data['isMaker'] else "吃单"
            
            return (
                f"⏰ 时间: {exec_time}\n"
                f"📍 方向: {side_emoji}\n"
                f"💰 价格: {trade_data['execPrice']}\n"
                f"📊 数量: {trade_data['execQty']}\n"
                f"💵 价值: {total_value:.2f} USDT\n"
                f"📋 类型: {maker_taker}\n"
                f"💸 手续费: {trade_data['execFee']}\n"
                f"🔖 订单号: {trade_data['orderId'][:8]}...\n"
            )

        try:
            # 检查是否有交易数据
            if not trades_data:
                return "没有交易数据"
            
            symbol = trades_data[0]['symbol']
            
            # 构建完整消息
            message_parts = [
                f"💫 {symbol} 成交通知",
                f"━━━━━━━━━━━━━━"
            ]
            
            # 添加每个交易的详情
            for i, trade in enumerate(trades_data, 1):
                if len(trades_data) > 1:
                    message_parts.append(f"🔄 交易 {i}/{len(trades_data)}")
                message_parts.append(format_single_trade(trade))
                message_parts.append("━━━━━━━━━━━━━━")
            
            return "\n".join(message_parts)

        except Exception as e:
            logging.error(f"格式化Bybit交易数据失败: {e}")
            return f"❌ 格式化消息失败: {str(e)}"
