# -*- coding: utf-8 -*-
"""
src/screener.py - ASX 潜力股雷达 (机构风控终极版)
核心策略：Minervini 趋势模板 + 相对强度(RS) + 板块熔断风控 + 自动追加报告
"""
import yfinance as yf
import pandas as pd
import datetime
import os
import sys

# === 1. 股票池与行业映射 (用于风控) ===
SECTOR_MAP = {
    # --- 🏦 金融银行 ---
    "CBA.AX": "金融", "WBC.AX": "金融", "NAB.AX": "金融", "ANZ.AX": "金融", "MQG.AX": "金融", 
    "QBE.AX": "保险", "SUN.AX": "保险", "ZIP.AX": "金融科技", "TYR.AX": "金融科技", "HUB.AX": "金融科技", "NWL.AX": "金融科技",
    
    # --- ⛏️ 矿产能源 ---
    "BHP.AX": "铁矿", "RIO.AX": "铁矿", "FMG.AX": "铁矿", "WDS.AX": "能源", "STO.AX": "能源", 
    "PLS.AX": "锂矿", "MIN.AX": "锂矿", "NST.AX": "黄金", "EVN.AX": "黄金", "LYC.AX": "稀土", 
    "PDN.AX": "铀矿", "BOE.AX": "铀矿", "NXG.AX": "铀矿", "CU6.AX": "铜矿", "WA1.AX": "稀有金属",
    
    # --- 💻 科技成长 ---
    "XRO.AX": "SaaS", "WTC.AX": "物流科技", "PME.AX": "医疗AI", "ALU.AX": "软件", "NXT.AX": "数据中心", 
    "TNE.AX": "科技", "CAR.AX": "平台", "REA.AX": "平台", "SEK.AX": "平台", "LOV.AX": "零售科技",
    "DRO.AX": "军工", "SDR.AX": "电子", "MP1.AX": "网络",
    
    # --- 🛒 消费医疗 ---
    "WES.AX": "零售", "WOW.AX": "零售", "COL.AX": "零售", "JBH.AX": "消费电子", "HVN.AX": "消费",
    "CSL.AX": "生物医药", "COH.AX": "医疗器械", "RMD.AX": "呼吸机", "FPH.AX": "医疗", "SHL.AX": "医疗", "TLX.AX": "放射药",
    "WEB.AX": "旅游", "FLT.AX": "旅游",
    
    # --- 🏭 工业公用 ---
    "TLS.AX": "通讯", "TCL.AX": "基建", "GMG.AX": "地产", "SCG.AX": "地产", "QAN.AX": "航空", 
    "BXB.AX": "物流", "ORG.AX": "电力", "AGL.AX": "电力", "GUD.AX": "工业"
}

# 提取代码列表用于下载
ASX_WATCHLIST = list(SECTOR_MAP.keys())

def get_report_path():
    """获取今日报告路径"""
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    # 假设脚本在 src/ 下，往上两级找到 reports/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_dir = os.path.join(base_dir, "reports")
    
    # 优先找大盘复盘报告，其次找个股分析报告
    for prefix in ["market_review_", "report_"]:
        filename = f"{prefix}{today_str}.md"
        path = os.path.join(report_dir, filename)
        if os.path.exists(path): return path
        
    # 如果都找不到，返回一个默认路径防止报错（会在 logs 里打印）
    return os.path.join(report_dir, f"market_review_{today_str}.md")

def calculate_rs_rating(data_df):
    """计算相对强度 (RS Rating)"""
    try:
        p_now = data_df['Close'].iloc[-1]
        # 如果数据不够长，就用最早的数据代替
        p_3m = data_df['Close'].iloc[-63] if len(data_df) > 63 else data_df['Close'].iloc[0]
        p_6m = data_df['Close'].iloc[-126] if len(data_df) > 126 else data_df['Close'].iloc[0]
        
        # 权重：近3个月权重更高 (40%)，近6个月次之 (20%)
        rs_score = 0.4 * (p_now/p_3m) + 0.2 * (p_now/p_6m)
        return rs_score * 100
    except:
        return 0

def scan_market():
    print(f"🚀 [ASX Hunter Pro] 启动风控扫描 | 监控标的: {len(ASX_WATCHLIST)} 只")
    print("-" * 75)
    
    candidates = []
    
    # 批量下载数据 (最近1年)
    try:
        data = yf.download(ASX_WATCHLIST, period="1y", interval="1d", group_by='ticker', progress=False)
    except Exception as e:
        print(f"❌ 数据下载失败: {e}")
        return

    for code in ASX_WATCHLIST:
        try:
            df = data[code]
            if df.empty or len(df) < 200: continue
            
            # 提取关键列
            closes = df['Close']
            volumes = df['Volume']
            highs = df['High']
            lows = df['Low']
            
            curr_p = float(closes.iloc[-1])
            curr_v = float(volumes.iloc[-1])
            
            # --- 1. 趋势过滤 (Minervini Template) ---
            ma50 = closes.rolling(50).mean().iloc[-1]
            ma150 = closes.rolling(150).mean().iloc[-1]
            ma200 = closes.rolling(200).mean().iloc[-1]
            
            year_low = lows.rolling(250).min().iloc[-1] if len(lows) > 250 else lows.min()
            year_high = highs.rolling(250).max().iloc[-1] if len(highs) > 250 else highs.max()
            
            # 趋势条件：MA50 > MA150 > MA200 (多头排列)
            trend_ok = (curr_p > ma50) and (ma50 > ma150) and (ma150 > ma200)
            
            # 底部条件：离一年低点至少涨了 25% (摆脱底部)
            base_ok = curr_p > year_low * 1.25
            
            # 攻击条件：离一年高点不远，在 25% 以内 (处于攻击形态)
            attack_ok = curr_p > year_high * 0.75
            
            if not (trend_ok and base_ok and attack_ok):
                continue
            
            # --- 2. 信号扫描 ---
            signals = []
            vol_ma20 = volumes.rolling(20).mean().iloc[-1]
            vol_ratio = curr_v / vol_ma20 if vol_ma20 > 0 else 0
            pct_chg = (curr_p - closes.iloc[-2]) / closes.iloc[-2] * 100
            
            # 信号A: 机构抢筹 (放量 > 1.5倍 且 大涨 > 1%)
            if vol_ratio > 1.5 and pct_chg > 1.0:
                signals.append("🔥机构抢筹")
            
            # 信号B: 逼近新高 (距离新高不到 2%)
            if curr_p >= year_high * 0.98:
                signals.append("🚀逼近新高")
            
            # 信号C: 缩量洗盘 (量极缩 < 0.6 且 价格稳住) - 适合低吸
            if abs(pct_chg) < 1.0 and vol_ratio < 0.6 and curr_p > ma50:
                signals.append("👀缩量洗盘")

            # 只要有信号，或者趋势极强，就加入候选
            if signals:
                candidates.append({
                    "code": code,
                    "name": SECTOR_MAP.get(code, "其他"),
                    "price": curr_p,
                    "change": pct_chg,
                    "vol_ratio": vol_ratio,
                    "signal": " ".join(signals),
                    "rs": calculate_rs_rating(df)
                })
        except: continue

    # 按 RS 强度排序 (强者恒强)
    candidates.sort(key=lambda x: x['rs'], reverse=True)
    
    # --- 3. 板块熔断 (风控核心) ---
    final_list = []
    sector_count = {} # 计数器
    
    for stock in candidates:
        sector = stock['name']
        # 初始化计数
        if sector not in sector_count: sector_count[sector] = 0
        
        # 熔断阈值：同板块最多只选 2 只
        if sector_count[sector] >= 2:
            continue
            
        final_list.append(stock)
        sector_count[sector] += 1
        
        # 最多只展示前 10 只
        if len(final_list) >= 10:
            break
            
    # --- 4. 生成报告 ---
    print(f"\n✅ 扫描完成: 初选 {len(candidates)} 只 -> 风控后精选 {len(final_list)} 只\n")
    
    markdown = "\n\n---\n\n## 🦅 猎手雷达 (风控版)：机构潜力股\n"
    markdown += "> **筛选逻辑**：Minervini 趋势模板 + 机构异动信号 + **行业分散风控(Max 2)**。\n\n"
    
    if not final_list:
        markdown += "今日市场分化，未发现符合风控模型的高质量标的。\n"
    else:
        markdown += "| 代码 | 板块 | 现价 | 涨跌 | 量比 | 信号 | 强度(RS) |\n"
        markdown += "|---|---|---|---|---|---|---|\n"
        for r in final_list:
            markdown += f"| **{r['code']}** | {r['name']} | {r['price']:.2f} | {r['change']:+.2f}% | {r['vol_ratio']:.1f}x | {r['signal']} | {r['rs']:.0f} |\n"

    print(markdown)
    
    # 追加到报告
    path = get_report_path()
    if os.path.exists(path):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(markdown)
            print(f"✅ 已追加到报告: {path}")
        except Exception as e:
            print(f"❌ 写入失败: {e}")
    else:
        print("⚠️ 未找到今日报告文件，仅打印结果。")

if __name__ == "__main__":
    scan_market()
