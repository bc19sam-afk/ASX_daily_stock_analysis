# -*- coding: utf-8 -*-
"""
src/screener.py - ASX 潜力股猎手 (自动追加报告版)
"""
import yfinance as yf
import pandas as pd
import datetime
import os
import sys

# === 核心关注名单 (流动性好的热门股) ===
ASX_WATCHLIST = [
    # 银行/金融
    "CBA.AX", "WBC.AX", "NAB.AX", "ANZ.AX", "MQG.AX", "QBE.AX", "SUN.AX",
    # 矿业/能源
    "BHP.AX", "RIO.AX", "FMG.AX", "WDS.AX", "STO.AX", "PLS.AX", "MIN.AX", "NST.AX", "EVN.AX", "LYC.AX",
    # 科技/成长
    "WTC.AX", "XRO.AX", "CPU.AX", "REA.AX", "CAR.AX", "NXT.AX", "TNE.AX", "360.AX",
    # 消费/零售
    "WES.AX", "WOW.AX", "COL.AX", "JBH.AX", "DMP.AX", "HVN.AX",
    # 医疗
    "CSL.AX", "COH.AX", "RMD.AX", "FPH.AX", "SHL.AX", "PME.AX",
    # 其他蓝筹
    "TLS.AX", "TCL.AX", "GMG.AX", "SCG.AX", "ALL.AX", "QAN.AX", "BXB.AX"
]

def get_report_path():
    """找到今天的大盘复盘报告路径"""
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    # 假设报告在 reports 目录下，文件名格式为 market_review_YYYYMMDD.md
    # 根据你的日志，路径是 reports/market_review_20260224.md
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_dir = os.path.join(base_dir, "reports")
    filename = f"market_review_{today_str}.md"
    return os.path.join(report_dir, filename)

def scan_and_append():
    print(f"🚀 [ASX Hunter] 开始扫描 {len(ASX_WATCHLIST)} 只热门股票...")
    
    results = []
    
    # 批量下载数据 (最近30天)
    try:
        data = yf.download(ASX_WATCHLIST, period="30d", interval="1d", group_by='ticker', progress=False)
    except Exception as e:
        print(f"数据下载失败: {e}")
        return

    for code in ASX_WATCHLIST:
        try:
            df = data[code]
            if df.empty or len(df) < 20: continue
            
            # 提取数据
            closes = df['Close']
            volumes = df['Volume']
            
            curr_p = float(closes.iloc[-1])
            prev_p = float(closes.iloc[-2])
            pct = (curr_p - prev_p) / prev_p * 100
            
            ma5 = closes.rolling(5).mean().iloc[-1]
            ma20 = closes.rolling(20).mean().iloc[-1]
            
            curr_v = float(volumes.iloc[-1])
            avg_v = volumes.rolling(5).mean().iloc[-1]
            v_ratio = curr_v / avg_v if avg_v > 0 else 0
            
            # === 筛选逻辑 ===
            reasons = []
            
            # 1. 趋势多头 (价格 > 月线)
            if curr_p > ma20:
                # 2. 资金进场 (放量 > 1.3倍 且 上涨)
                if v_ratio > 1.3 and pct > 0.5:
                    reasons.append("🔥放量抢筹")
                
                # 3. 均线金叉 (MA5 上穿 MA20)
                ma5_prev = closes.rolling(5).mean().iloc[-2]
                ma20_prev = closes.rolling(20).mean().iloc[-2]
                if ma5 > ma20 and ma5_prev <= ma20_prev:
                    reasons.append("📈金叉启动")
            
            # 收集结果
            if reasons:
                results.append({
                    "code": code,
                    "price": curr_p,
                    "pct": pct,
                    "vol_ratio": v_ratio,
                    "signal": " ".join(reasons)
                })
                
        except: continue

    # === 生成 Markdown 内容 ===
    markdown_output = "\n\n---\n\n## 🎯 猎手雷达：明日潜力股扫描\n"
    markdown_output += "> 以下股票呈现【放量】或【突破】形态，建议加入自选观察。\n\n"
    
    if not results:
        markdown_output += "今天市场平静，未扫描到明显异动股票。\n"
    else:
        markdown_output += "| 代码 | 现价 | 涨跌幅 | 量比 | 信号 |\n"
        markdown_output += "|---|---|---|---|---|\n"
        for res in results:
            markdown_output += f"| **{res['code']}** | {res['price']:.2f} | {res['pct']:+.2f}% | {res['vol_ratio']:.1f}x | {res['signal']} |\n"

    print("-" * 65)
    print(f"✅ 扫描结束: 发现 {len(results)} 只潜力股")
    
    # === 追加到报告文件 ===
    report_path = get_report_path()
    if os.path.exists(report_path):
        try:
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(markdown_output)
            print(f"✅ 已成功追加到报告: {report_path}")
        except Exception as e:
            print(f"❌ 写入报告失败: {e}")
    else:
        print(f"⚠️ 未找到今日报告文件: {report_path}，无法追加。")
        # 如果找不到文件（比如单跑测试），就打印出来
        print(markdown_output)

if __name__ == "__main__":
    scan_and_append()
