import base64
import logging
from io import BytesIO
from datetime import datetime
from typing import Dict, List, Optional

from matplotlib import rcParams
import matplotlib.dates as mdates
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

import numpy as np
from pandas.core.frame import DataFrame, Series

"""
前年と比較した気象データ画像のbase64エンコードテキストデータを出力する
※投稿の説明用ソース (直値を定数・変数に定義しない)
"""

rcParams['font.family'] = "sans-serif"
rcParams['font.sans-serif'] = ["IPAexGothic"]

# pandas.DataFrameのインデックス列
COL_TIME: str = 'measurement_time'
# 前年DataFrameの年月日+1年
COL_PREV_PLOT_TIME: str = 'prev_plot_measurement_time'
# 観測データ列
COL_TEMP_OUT: str = 'temp_out'
COL_HUMID: str = "humid"
COL_PRESSURE: str = 'pressure'


def datetime_plus_1_year(prev_datetime: datetime) -> datetime:
    """
    前年のdatetimeオブジェクトに1年プラスしたdatetimeオブジェクトを取得する
    :param prev_datetime: 前年のdatetimeオブジェクト
    @return: 1年プラスしたdatetimeオブジェクト
    """
    next_val: datetime = datetime(prev_datetime.year + 1,
                                  prev_datetime.month,
                                  prev_datetime.day,
                                  prev_datetime.hour,
                                  prev_datetime.minute,
                                  prev_datetime.second
                                  )
    return next_val


def make_legend_label(s_year_month: str) -> str:
    """
    凡例用ラベル生成
    :param s_year_month: 年月文字列
    @return: 凡例用ラベル
    """
    parts: List[str] = s_year_month.split('-')
    return "{year}年{month}月".format(year=parts[0], month=parts[1])


def make_average_patch(plot_label, f_ave: float, s_color: str, dict_ave: Dict) -> Patch:
    """
    平均値パッチ生成
    :param plot_label:
    :param f_ave:
    :param s_color
    :param dict_ave:
    @return:
    """

    def make_average_text(jp_year_month: str, value: float, data_dict: Dict) -> str:
        """
        平均値用の文字列生成
        :param jp_year_month: 日本語年月文字列
        :param value: 平均値
        :param data_dict: データ型ごとの置換用辞書オブジェクト
        :return: 平均値用の文字列
        """
        data_dict['jp_year_month'] = jp_year_month
        data_dict['value'] = value
        return "{jp_year_month} 平均{type} {value:#.1f} {unit}".format(**data_dict)

    average_label = make_average_text(plot_label, f_ave, dict_ave)
    return Patch(color=s_color, label=average_label)


def set_ylim_with_axes(plot_axes: Axes, curr_ser: Series, prev_ser: Series) -> None:
    """
    各データの最大値・最小値を設定する
    :param plot_axes: プロット領域
    :param curr_ser: 最新データ
    :param prev_ser: 前年データ
    """
    val_min: float = np.min([curr_ser.min(), prev_ser.min()])
    val_max: float = np.max([curr_ser.max(), prev_ser.max()])
    val_min = np.floor(val_min / 10.) * 10.
    val_max = np.ceil(val_max / 10.) * 10.
    plot_axes.set_ylim(val_min, val_max)


def gen_plot_image(df_curr: DataFrame, df_prev: DataFrame,
                   year_month: str, prev_year_month: str,
                   logger: Optional[logging.Logger] = None) -> str:
    """
    指定年月とその前年の観測データをプロットした画像のBase64エンコード済み文字列を生成する
    :param df_curr: 指定年月の観測データのDataFrame
    :param df_prev: 前年の年月の観測データのDataFrame
    :param year_month: 指定年月 (形式: "%Y-%m")
    :param prev_year_month: 前年の年月 (形式: "%Y-%m")
    :param logger: application logger
    :return: 画像のBase64エンコード済み文字列
    """

    # 凡例用ラベル
    # 今年の年月
    curr_plot_label = make_legend_label(year_month)
    # 前年の年月
    prev_plot_label = make_legend_label(prev_year_month)
    # グラフタイトル
    title: str = "{} − {} データ比較".format(curr_plot_label, prev_plot_label)

    # 前年データをX軸にプロットするために測定時刻列にを1年プラスする
    df_prev[COL_PREV_PLOT_TIME] = df_prev[COL_TIME].apply(datetime_plus_1_year)
    if logger is not None:
        logger.debug(f"{df_prev}")

    fig: Figure
    ax_temp: Axes
    ax_humid: Axes
    ax_pressure: Axes
    # PCブラウザはinch指定でdpi=72
    fig = Figure(figsize=(9.8, 6.4), constrained_layout=True)
    # x軸を共有する3行1列のサブプロット生成
    (ax_temp, ax_humid, ax_pressure) = fig.subplots(nrows=3, ncols=1, sharex=True)
    # Y方向のグリッド線のみ表示
    for ax in [ax_temp, ax_humid, ax_pressure]:
        ax.grid(axis='y', linestyle='dashed', linewidth=0.7, alpha=0.75)

    # (1) 外気温領域のプロット
    # 最低・最高
    set_ylim_with_axes(ax_temp, df_curr[COL_TEMP_OUT], df_prev[COL_TEMP_OUT])
    # 最新年の凡例
    curr_patch: Patch
    # 前年の凡例
    prev_patch: Patch
    # 最新年月の外気温
    ax_temp.plot(df_curr[COL_TIME], df_curr[COL_TEMP_OUT], color="C0", marker="")
    curr_patch = make_average_patch(curr_plot_label, df_curr[COL_TEMP_OUT].mean(),
                                    "C0", {'type': '気温', 'unit': '℃'})
    ax_temp.axhline(df_curr[COL_TEMP_OUT].mean(),
                    color="C0", linestyle='dashdot', linewidth=1.)
    # 前年月の外気温
    ax_temp.plot(df_prev[COL_PREV_PLOT_TIME], df_prev[COL_TEMP_OUT], color='C1', marker="")
    prev_patch = make_average_patch(prev_plot_label, df_prev[COL_TEMP_OUT].mean(),
                                    'C1', {'type': '気温', 'unit': '℃'})
    ax_temp.axhline(df_prev[COL_TEMP_OUT].mean(),
                    color='C1', linestyle='dashdot', linewidth=1.)
    ax_temp.set_ylabel("外気温 (℃)", fontsize=10)
    # 凡例
    ax_temp.legend(handles=[curr_patch, prev_patch], fontsize=10)
    ax_temp.set_title(title, fontsize=11)
    # X軸ラベルを隠す
    ax_temp.label_outer()

    # (2) 湿度領域のプロット
    ax_humid.set_ylim(ymin=0., ymax=100.)
    # 最新年月
    ax_humid.plot(df_curr[COL_TIME], df_curr[COL_HUMID], color="C0", marker="")
    curr_patch = make_average_patch(curr_plot_label, df_curr[COL_HUMID].mean(),
                                    "C0", {'type': '湿度', 'unit': '％'})
    ax_humid.axhline(df_curr[COL_HUMID].mean(),
                     color="C0", linestyle='dashdot', linewidth=1.)
    # 前年月
    ax_humid.plot(df_prev[COL_PREV_PLOT_TIME], df_prev[COL_HUMID], color='C1', marker="")
    prev_patch = make_average_patch(prev_plot_label, df_prev[COL_HUMID].mean(),
                                    'C1', {'type': '湿度', 'unit': '％'})
    ax_humid.axhline(df_prev[COL_HUMID].mean(),
                     color='C1', linestyle='dashdot', linewidth=1.)
    ax_humid.set_ylabel("室内湿度 (％)", fontsize=10)
    # 凡例
    ax_humid.legend(handles=[curr_patch, prev_patch], fontsize=10)
    ax_humid.label_outer()

    # (3) 気圧領域のプロット
    set_ylim_with_axes(ax_pressure, df_curr[COL_PRESSURE], df_prev[COL_PRESSURE])
    # 最新年月
    ax_pressure.plot(df_curr[COL_TIME], df_curr[COL_PRESSURE], color="C0", marker="")
    curr_patch = make_average_patch(curr_plot_label, df_curr[COL_PRESSURE].mean(),
                                    "C0", {'type': '気圧', 'unit': 'hPa'})
    ax_pressure.axhline(df_curr[COL_PRESSURE].mean(),
                        color="C0", linestyle='dashdot', linewidth=1.)
    # 前年月
    ax_pressure.plot(df_prev[COL_PREV_PLOT_TIME], df_prev[COL_PRESSURE], color='C1', marker="")
    prev_patch = make_average_patch(prev_plot_label, df_prev[COL_PRESSURE].mean(),
                                    'C1', {'type': '気圧', 'unit': 'hPa'})
    ax_pressure.axhline(df_prev[COL_PRESSURE].mean(),
                        color='C1', linestyle='dashdot', linewidth=1.)
    ax_pressure.set_ylabel("気　圧 (hPa)", fontsize=10)
    # 凡例
    ax_pressure.legend(handles=[curr_patch, prev_patch], fontsize=10)
    # X軸ラベル
    ax_pressure.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    # 画像をバイトストリームに溜め込みそれをbase64エンコードしてレスポンスとして返す
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    # base64エンコード文字列
    return "data:image/png;base64," + data
