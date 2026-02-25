# -*- coding: utf-8 -*-
"""
src/screener.py - ASX 200 全市场扫描器 (真·量化版)
职责：遍历 ASX 200 成分股，基于纯数据(价格/成交量)筛选出强势股。
"""
import yfinance as yf
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# === ASX 200 成分股名单 (覆盖全市场核心流动性) ===
# 这是一个纯粹的扫描范围，不代表推荐，系统会从中筛选
ASX_200_LIST = [
    "360.AX", "A2M.AX", "ABC.AX", "ABP.AX", "AGL.AX", "ALD.AX", "ALL.AX", "ALQ.AX", "ALX.AX", "AMC.AX",
    "AMP.AX", "ANN.AX", "ANZ.AX", "APA.AX", "APE.AX", "ARB.AX", "ARF.AX", "ARG.AX", "ASX.AX", "AUB.AX",
    "AWC.AX", "AZJ.AX", "BAP.AX", "BEN.AX", "BGA.AX", "BHP.AX", "BKL.AX", "BKW.AX", "BLD.AX", "BOE.AX",
    "BPT.AX", "BRG.AX", "BSL.AX", "BWP.AX", "BXB.AX", "CAR.AX", "CBA.AX", "CCP.AX", "CDR.AX", "CGF.AX",
    "CHC.AX", "CHN.AX", "CIA.AX", "CIP.AX", "CLW.AX", "CNEW.AX", "COH.AX", "COL.AX", "CPU.AX", "CQR.AX",
    "CSL.AX", "CSR.AX", "CTD.AX", "CU6.AX", "CWY.AX", "CXL.AX", "DEG.AX", "DJW.AX", "DMP.AX", "DOW.AX",
    "DRR.AX", "DXI.AX", "DXS.AX", "EBO.AX", "EDV.AX", "ELD.AX", "EMR.AX", "EVN.AX", "EVT.AX", "FBU.AX",
    "FCL.AX", "FLT.AX", "FMG.AX", "FPH.AX", "GEM.AX", "GNC.AX", "GOZ.AX", "GPT.AX", "GUD.AX", "GWA.AX",
    "HCLS.AX", "HDN.AX", "HLS.AX", "HUB.AX", "HVN.AX", "IAG.AX", "IEL.AX", "IFL.AX", "IFT.AX", "IGO.AX",
    "ILU.AX", "INA.AX", "ING.AX", "IPH.AX", "IPL.AX", "IRE.AX", "IVC.AX", "JBH.AX", "JDO.AX", "JHX.AX",
    "KAR.AX", "KLS.AX", "LIC.AX", "LIN.AX", "LLC.AX", "LNK.AX", "LOV.AX", "LTR.AX", "LYC.AX", "MFG.AX",
    "MGR.AX", "MIN.AX", "MND.AX", "MP1.AX", "MPL.AX", "MQG.AX", "MTS.AX", "MYX.AX", "NAB.AX", "NAN.AX",
    "NCM.AX", "NEC.AX", "NHC.AX", "NHF.AX", "NIC.AX", "NSR.AX", "NST.AX", "NUF.AX", "NWL.AX", "NXT.AX",
    "ORA.AX", "ORG.AX", "ORI.AX", "OSH.AX", "OZL.AX", "PBH.AX", "PDN.AX", "PLS.AX", "PME.AX", "PMV.AX",
    "PNI.AX", "PPC.AX", "PPT.AX", "PRN.AX", "PRU.AX", "PXA.AX", "QAN.AX", "QBE.AX", "QUB.AX", "REA.AX",
    "RHC.AX", "RIO.AX", "RMD.AX", "RRL.AX", "RWC.AX", "S32.AX", "SCG.AX", "SCP.AX", "SDF.AX", "SEK.AX",
    "SGM.AX", "SGP.AX", "SGR.AX", "SHL.AX", "SIQ.AX", "SKC.AX", "SKI.AX", "SLR.AX", "SNZ.AX", "SOL.AX",
    "SPK.AX", "STO.AX", "STX.AX", "SUN.AX", "SVW.AX", "SYA.AX", "SYD.AX", "TAH.AX", "TCL.AX", "THO.AX",
    "TLX.AX", "TNE.AX", "TPG.AX", "TWE.AX", "TYR.AX", "UNI.AX", "VCX.AX", "VEA.AX", "VNT.AX", "VUK.AX",
    "WBC.AX", "WEB.AX", "WES.AX", "WGX.AX", "WHC.AX", "WOR.AX", "WOW.AX", "WPR.AX", "WTC.AX", "XRO.AX",
    "YAL.AX", "ZIM.AX", "ZIP.AX"
]

def run_screener_analysis():
    """
    对 ASX 200 进行全量扫描
    """
    logger.info(f"🚀 [Screener] 启动全市场扫描，目标池: ASX 200 ({len(ASX_200_LIST)} 只)...")
    candidates = []
    
    try:
        # 1. 批量下载数据 (这是真正的数据获取步骤)
        # 即使下载 200 只，yfinance 也能在 10-20 秒内搞定
        data = yf.download(ASX_200_LIST, period="1y", interval="1d", group_by='ticker', progress=False)
        
        # 2. 逐个分析
        for code in ASX_200_LIST:
            try:
                # 兼容性处理：如果某只股票退市或改名，没下载到数据，直接跳过
                try:
                    df = data[code]
                except KeyError:
                    continue
                
                if df.empty or len(df) < 200: continue
                
                # --- 核心数据提取 ---
                # 处理 MultiIndex 问题
                try:
                    closes = df['Close']
                    volumes = df['Volume']
                    highs = df['High']
                except Exception:
                    continue # 数据格式不对就跳过

                curr = float(closes.iloc[-1])
                
                # --- 过滤逻辑 1: 必须是上升趋势 (价格在年线之上) ---
                # 我们放宽一点标准，只要价格站上 MA200 就算进入多头区域，不漏掉启动初期的票
                ma200 = closes.rolling(200).mean().iloc[-1]
                if curr < ma200:
                    continue # 还在走熊的股票，直接扔掉，看都不看

                # --- 过滤逻辑 2: 具体的强势形态 ---
                ma50 = closes.rolling(50).mean().iloc[-1]
                
                # 计算指标
                vol_ma20 = float(volumes.rolling(20).mean().iloc[-1])
                vol_ratio = (float(volumes.iloc[-1]) / vol_ma20) if vol_ma20 > 0 else 0
                pct_chg = (curr - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100
                year_high = float(highs.rolling(250).max().iloc[-1])
                
                signals = []
                
                # 信号 A: 突破年线/半年线 (趋势反转)
                if curr > ma200 and float(closes.iloc[-2]) < ma200 and vol_ratio > 1.2:
                    signals.append("⚡突破年线")
                
                # 信号 B: 机构抢筹 (放量大涨)
                if vol_ratio > 1.8 and pct_chg > 1.5:
                    signals.append("🔥主力进场")
                
                # 信号 C: 逼近历史新高 (最强音)
                if curr >= year_high * 0.98:
                    signals.append("🚀逼近新高")
                
                # 信号 D: 缩量回踩 (买点)
                # 价格在 MA50 之上，但是最近跌了，且成交量很小
                if curr > ma50 and -2.0 < pct_chg < 0 and vol_ratio < 0.6:
                    signals.append("👀缩量回踩")

                # 只有出现了上述明确信号的，才入选
                if signals:
                    # 计算相对强度 RS (过去3个月涨幅)
                    rs_score = (curr / float(closes.iloc[-60])) * 100
                    
                    candidates.append({
                        "code": code,
                        "p": curr,
                        "chg": pct_chg,
                        "s": " ".join(signals),
                        "rs": rs_score,
                        "vol": vol_ratio
                    })
                    
            except Exception:
                continue

    except Exception as e:
        logger.error(f"扫描过程出错: {e}")
        return f"\n\n**Screener Error:** 扫描部分失败 - {str(e)}\n"

    # === 生成报告 ===
    md = "\n\n---\n\n## 🦅 全市场猎手 (ASX 200)\n"
    md += "> **扫描范围**：ASX Top 200 | **筛选标准**：站稳年线 + 资金异动\n\n"
    
    if not candidates:
        md += "今日市场普跌，ASX 200 中未发现符合强势特征的标的。\n"
    else:
        # 按相对强度排序，只看最强的
        candidates.sort(key=lambda x: x['rs'], reverse=True)
        
        # 只展示前 10 只，贵精不贵多
        top_picks = candidates[:10]
        
        md += "| 代码 | 现价 | 涨跌幅 | 量比 | 信号 | 强度 |\n"
        md += "|---|---|---|---|---|---|\n"
        for c in top_picks:
            # 简单把信号里的空格去掉，防止表格换行
            sig_str = c['s'].replace(" ", "/")
            md += f"| **{c['code']}** | {c['p']:.2f} | {c['chg']:+.2f}% | {c['vol']:.1f}x | {sig_str} | {c['rs']:.0f} |\n"
            
    logger.info(f"✅ [Screener] 全市场扫描完成，从 {len(ASX_200_LIST)} 只中选出 {len(candidates)} 只")
    return md
