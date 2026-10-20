# -*- coding: utf-8 -*-
"""
cold_stats.py
独立测算全历史、按年、按月特码开奖前遗漏（冷号）分布
增加：每期各区间冷号池深度（号码数量）统计
"""
import pandas as pd
from core.draws import get_all_draws

def get_bin(om):
    if 64 <= om <= 110: return "64-110期"
    elif 111 <= om <= 142: return "111-142期"
    elif 143 <= om <= 194: return "143-194期"
    elif om >= 195: return ">=195期"
    else: return "其他"

def run_analysis():
    print("正在从 Turso 拉取全量数据...")
    df = get_all_draws()
    if df.empty:
        print("数据库为空！")
        return
    
    df = df.sort_values("期数").reset_index(drop=True)
    numbers = df["特码"].tolist()
    issues = df["期数"].tolist()
    
    total = len(numbers)
    print(f"数据加载完成，共 {total} 期。开始计算遗漏与冷号池深度...\n")

    last_pos = {}
    history_records = []
    
    for i, n in enumerate(numbers):
        # 1. 计算当期开奖号码的遗漏
        if n in last_pos:
            omission = i - last_pos[n] - 1
        else:
            omission = i
            
        # 2. 计算开奖前，全场49个号码的冷号池深度（数量）
        pool_counts = {"64-110期": 0, "111-142期": 0, "143-194期": 0, ">=195期": 0}
        for num in range(1, 50):
            if num in last_pos:
                om = i - last_pos[num] - 1
            else:
                om = i
            b = get_bin(om)
            if b != "其他":
                pool_counts[b] += 1
                
        history_records.append({
            "期数": issues[i],
            "特码": n,
            "遗漏": omission,
            "区间": get_bin(omission),
            "池_64_110": pool_counts["64-110期"],
            "池_111_142": pool_counts["111-142期"],
            "池_143_194": pool_counts["143-194期"],
            "池_195": pool_counts[">=195期"]
        })
        last_pos[n] = i

    hist_df = pd.DataFrame(history_records)
    
    # 提取年份和模拟月份
    hist_df["年份"] = hist_df["期数"] // 1000
    hist_df["年内序号"] = hist_df["期数"] % 1000
    hist_df["月份"] = (hist_df["年内序号"] - 1) // 30 + 1
    hist_df["月份"] = hist_df["月份"].apply(lambda x: 12 if x > 12 else x)
    
    cold_df = hist_df[hist_df["区间"] != "其他"].copy()
    bins_order = ["64-110期", "111-142期", "143-194期", ">=195期"]
    
    # ================= 汇总一：全历史统计 =================
    print("=" * 70)
    print("【一、全历史不同区间冷号开出数量统计】")
    print("=" * 70)
    
    total_cold = len(cold_df)
    print(f"全历史总开奖期数: {total} 期")
    print(f"冷号区间开出总期数: {total_cold} 期 (占比 {(total_cold/total)*100:.2f}%)\n")
    
    for b in bins_order:
        cnt = len(cold_df[cold_df["区间"] == b])
        pct = (cnt / total) * 100
        print(f"  {b:<10}: 开出 {cnt:<4} 次 | 占比 {pct:>5.2f}%")
        
    # ================= 汇总二：按年度统计 =================
    print("\n" + "=" * 70)
    print("【二、按年份统计】")
    print("=" * 70)
    
    for year in sorted(hist_df["年份"].unique()):
        year_df = hist_df[hist_df["年份"] == year]
        year_cold = cold_df[cold_df["年份"] == year]
        year_total = len(year_df)
        if year_total == 0: continue
        
        print(f"\n▶ {year} 年 (共计 {year_total} 期):")
        for b in bins_order:
            cnt = len(year_cold[year_cold["区间"] == b])
            pct = (cnt / year_total) * 100
            print(f"  [{b:<8}] 开出 {cnt:<3} 次 | 占比 {pct:>5.2f}%")

    # ================= 汇总三：按月统计 =================
    print("\n" + "=" * 70)
    print("【三、按月份统计明细 (仅列出有冷号的月份)】")
    print("=" * 70)
    
    for year in sorted(hist_df["年份"].unique()):
        print(f"\n▶ {year} 年:")
        for month in range(1, 13):
            month_df = hist_df[(hist_df["年份"] == year) & (hist_df["月份"] == month)]
            month_cold = cold_df[(cold_df["年份"] == year) & (cold_df["月份"] == month)]
            month_total = len(month_df)
            
            if month_total == 0: continue
            
            if len(month_cold) > 0:
                summary_strs = []
                for b in bins_order:
                    cnt = len(month_cold[month_cold["区间"] == b])
                    if cnt > 0:
                        summary_strs.append(f"{b}: {cnt}次")
                
                print(f"  {month}月 ({month_total}期): " + " | ".join(summary_strs))

    # ================= 汇总四：每 10 期为一个周期 (含冷号池深度) =================
    print("\n" + "=" * 70)
    print("【四、每 10 期为一个周期的分布 (含平均冷号池深度)】")
    print("=" * 70)
    print("注：池深度是指当期全场有多少个号码处于该遗漏区间。")
    
    hist_df["周期块"] = hist_df.index // 10
    
    for block_idx in range(len(hist_df) // 10 + 1):
        block_data = hist_df[hist_df["周期块"] == block_idx]
        if block_data.empty: continue
        
        start_issue = block_data.iloc[0]["期数"]
        end_issue = block_data.iloc[-1]["期数"]
        block_len = len(block_data)
        
        block_cold = block_data[block_data["区间"] != "其他"]
        
        # 计算该周期内的平均池子深度
        avg_64 = block_data["池_64_110"].mean()
        avg_111 = block_data["池_111_142"].mean()
        avg_143 = block_data["池_143_194"].mean()
        avg_195 = block_data["池_195"].mean()
        
        # 如果这个周期完全没有冷号开出，且池子也全空，就不打印了
        if block_cold.empty and (avg_64==0 and avg_111==0 and avg_143==0 and avg_195==0):
            continue
            
        print(f"\n▶ 周期 {block_idx+1} ({start_issue} - {end_issue}) 共计 {block_len} 期:")
        print(f"  [池深度] 64-110均{avg_64:.1f}个 | 111-142均{avg_111:.1f}个 | 143-194均{avg_143:.1f}个 | >=195均{avg_195:.1f}个")
        
        for b in bins_order:
            b_count = len(block_cold[block_cold["区间"] == b])
            if b_count > 0:
                b_pct = (b_count / block_len) * 100
                details = block_cold[block_cold["区间"] == b][["期数", "遗漏"]]
                detail_str = ", ".join([f"{r['期数']}(遗漏{r['遗漏']})" for _, r in details.iterrows()])
                print(f"  [{b:<8}] 开出 {b_count} 次 (占比 {b_pct:>5.1f}%) | 明细: {detail_str}")

if __name__ == "__main__":
    run_analysis()