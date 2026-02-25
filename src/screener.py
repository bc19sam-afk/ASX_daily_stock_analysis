# -*- coding: utf-8 -*-
"""
src/screener.py - 首席量化分析模块 (机构专用版)
职责：只负责执行复杂的 Minervini 筛选与风控，返回分析结果供主程序调用。
"""
import yfinance as yf
import pandas as pd

# === 1. 机构级股票池与行业映射 ===
SECTOR_MAP = {
    # 银行金融
    "CBA.AX": "金融", "WBC.AX": "金融", "NAB.AX": "金融", "ANZ.AX": "金融", "MQG.AX": "投行", "QBE.AX": "保险", "SUN.AX": "保险", 
    # 矿业能源
    "BHP.AX": "铁矿", "RIO.AX": "铁矿", "FMG.AX": "铁矿", "WDS.AX": "油气", "STO.AX": "油气", "PLS.AX": "锂矿", "MIN.AX": "锂矿", "NST.AX": "黄金", "EVN.AX": "黄金",
    # 科技成长
    "XRO.AX": "SaaS", "WTC.AX": "物流科技", "PME.AX": "医疗AI", "NXT.AX": "数据中心", "TNE.AX": "科技", "CAR.AX": "平台", 
    # 消费医疗
    "WES.AX": "零售", "WOW.AX": "零售", "COL.AX": "零售", "JBH.AX": "消费", "CSL.AX": "医药", "COH.AX": "器械", "RMD.AX": "呼吸机",
    # 蓝筹公用
    "TLS.AX": "通讯", "TCL.AX": "基建", "GMG.AX": "地产", "QAN.AX": "航空", "ORG.AX": "电力"
}
ASX_WATCHLIST = list(SECTOR_MAP.keys())

def run_screener_analysis():
    """
    执行机构级筛选逻辑
    返回: Markdown 格式的分析报告字符串
    """
    print("🚀 [Screener] 正在启动量化筛选模型...")
    candidates = []
    
    try:
        # 下载数据
        data = yf.download(ASX_WATCHLIST, period="1y", interval="1d", group_by='ticker', progress=False)
        
        for code in ASX_WATCHLIST:
            try:
                df = data[code]
                if len(df) < 200: continue
                
                # 提取核心数据
                closes = df['Close']
                curr = float(closes.iloc[-1])
                ma50 = closes.rolling(50).mean().iloc[-1]
                ma150 = closes.rolling(150).mean().iloc[-1]
                ma200 = closes.rolling(200).mean().iloc[-1]
                
                # === 核心策略: Minervini 趋势模板 ===
                # 必须满足多头排列，且处于长期上升通道
                if curr > ma50 > ma150 > ma200:
                    
                    # 动能指标
                    vol_ratio = float(df['Volume'].iloc[-1]) / df['Volume'].rolling(20).mean().iloc[-1]
                    pct_chg = (curr - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100
                    year_high = float(df['High'].rolling(250).max().iloc[-1])
                    
                    # 信号捕捉
                    signals = []
                    if vol_ratio > 1.5 and pct_chg > 1.0: signals.append("🔥机构抢筹")
                    if curr >= year_high * 0.98: signals.append("🚀逼近新高")
                    if abs(pct_chg) < 1.0 and vol_ratio < 0.6 and curr > ma50: signals.append("👀缩量洗盘")
                    
                    # 只有出现信号才入选
                    if signals:
                        rs_rating = (curr / float(closes.iloc[-60])) * 100 # 相对强度简算
                        candidates.append({
                            "code": code,
                            "name": SECTOR_MAP.get(code, "其他"),
                            "p": curr,
                            "chg": pct_chg,
                            "s": " ".join(signals),
                            "rs": rs_rating
                        })
            except: continue
            
    except Exception as e:
        return f"\n\n**筛选器运行错误:** {str(e)}\n"

    # === 生成专业报告 ===
    md = "\n\n---\n\n## 🦅 猎手雷达：明日潜力股\n"
    md += "> **筛选模型**：Minervini 趋势模板 + 机构异动信号 + 行业分散风控\n\n"
    
    if not candidates:
        md += "今日市场情绪低迷，模型未扫描到高置信度标的。\n"
    else:
        # 1. 强者恒强排序 (RS Rating)
        candidates.sort(key=lambda x: x['rs'], reverse=True)
        
        # 2. 行业风控 (熔断机制: 同板块最多2只)
        final_list = []
        sector_count = {}
        
        for c in candidates:
            sec = c['name']
            if sector_count.get(sec, 0) >= 2: continue # 触发熔断，跳过
            final_list.append(c)
            sector_count[sec] = sector_count.get(sec, 0) + 1
            if len(final_list) >= 8: break # 每日精选不超过8只
            
        md += "| 代码 | 板块 | 现价 | 涨跌 | 信号 |\n|---|---|---|---|---|\n"
        for c in final_list:
            md += f"| **{c['code']}** | {c['name']} | {c['p']:.2f} | {c['chg']:+.2f}% | {c['s']} |\n"
            
    print(f"✅ [Screener] 模型计算完成，选出 {len(final_list) if candidates else 0} 只标的")
    return md
