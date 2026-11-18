from pathlib import Path

import numpy as np
import pandas as pd


PERIODS = ["尖", "峰", "平", "谷"]


def hourly_frame(year, tariff_path):
    if pd.Timestamp(year, 12, 31).is_leap_year:
        raise ValueError("标准 8760 输出需要非闰年")
    hours = pd.date_range(f"{year}-01-01", periods=8760, freq="h", name="时间")
    tariff = pd.read_excel(tariff_path)[["月份", "小时", "电价类型", "电价"]]
    tariff["电价"] = pd.to_numeric(tariff["电价"], errors="raise")
    keys = pd.MultiIndex.from_product([range(1, 13), range(24)])
    actual = pd.MultiIndex.from_frame(tariff[["月份", "小时"]])
    if actual.has_duplicates or set(actual) != set(keys):
        raise ValueError("电价表须覆盖每个月 0–23 时，每个月份和小时组合只填一次")
    if not tariff["电价类型"].isin(PERIODS).all() or not np.isfinite(tariff["电价"]).all():
        raise ValueError("检查电价类型和电价")
    frame = pd.DataFrame({"日期": hours.strftime("%Y-%m-%d"), "小时": hours.hour,
                          "月份": hours.month}, index=hours)
    return frame.join(tariff.set_index(["月份", "小时"]), on=["月份", "小时"])


def fill_meter_gaps(hourly, hours):
    """按手册填补零散缺失和大段缺失，并记录来源。"""
    load = hourly.reindex(hours)
    missing = load.isna()
    if missing.all():
        raise ValueError("目标年无有效读数")
    source = pd.Series("实测", index=hours)
    source.loc[missing] = "待填"
    daily_count = missing.groupby(hours.normalize()).transform("sum")
    for ts in hours[missing & (daily_count >= 8)]:
        for lag in range(1, 8):
            previous = ts - pd.Timedelta(days=lag)
            value = load.get(previous, np.nan)
            if pd.notna(value) and source.get(previous) == "实测":
                load.loc[ts] = value
                source.loc[ts] = f"补:前{lag}天同小时"
                break
    remaining = load.isna()
    source.loc[remaining & load.ffill().notna()] = "补:前一小时"
    source.loc[remaining & load.ffill().isna()] = "补:后续首个有效小时"
    return load.ffill().bfill(), source


def export(frame, output_path, audit=None):
    if len(frame) != 8760 or not np.isfinite(frame["负载"]).all():
        raise ValueError("负载必须是 8760 条有效数值")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="负载曲线", index=False)
        if audit is not None:
            audit.to_excel(writer, sheet_name="校核", index=False)
    print(path, len(frame), "行")
