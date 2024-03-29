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
"""

rcParams['font.family'] = "sans-serif"
rcParams['font.sans-serif'] = ["IPAexGothic"]

# pandas.DataFrameのインデックス列
COL_TIME: str = 'measurement_time'
COL_PREV_PLOT_TIME: str = 'prev_plot_measurement_time'
# 観測データ列
COL_TEMP_OUT: str = 'temp_out'
COL_HUMID: str = "humid"
COL_PRESSURE: str = 'pressure'

# ラベル
Y_LABEL_HUMID: str = '室内湿度 (％)'
Y_LABEL_PRESSURE: str = '気　圧 (hPa)'
Y_LABEL_TEMP: str = '気温 (℃)'
Y_LABEL_TEMP_OUT: str = '外気温 (℃)'

# タイトルフォーマット
FMT_MEASUREMENT_RANGE: str = "{} − {} データ比較"
# 平均値文字列
FMT_JP_YEAR_MONTH: str = "{year}年{month}月"
FMT_AVEG_TEXT: str = "{jp_year_month} 平均{type} {value:#.1f} {unit}"
DICT_AVEG_TEMP: Dict = {'type': '気温', 'unit': '℃'}
DICT_AVEG_HUMID: Dict = {'type': '湿度', 'unit': '％'}
DICT_AVEG_PRESSURE: Dict = {'type': '気圧', 'unit': 'hPa'}
# 描画領域のグリッド線スタイル: Y方向のグリッド線のみ表示
GRID_STYLE: Dict = {'axis': 'y', 'linestyle': 'dashed', 'linewidth': 0.7,
                    'alpha': 0.75}
# 線カラー
# 'tab:blue'
CURR_COLOR: str = 'C0'
# 'tab:orange'
PREV_COLOR: str = 'C1'
# 平均線スタイル
AVEG_LINE_STYLE: Dict = {'linestyle': 'dashdot', 'linewidth': 1.}
CURR_AVEG_LINE_STYLE: Dict = {'color': CURR_COLOR, **AVEG_LINE_STYLE}
PREV_AVEG_LINE_STYLE: Dict = {'color': PREV_COLOR, **AVEG_LINE_STYLE}
# プロット領域のラベルスタイル
LABEL_STYLE: Dict = {'fontsize': 10, }
# 凡例スタイル
LEGEND_STYLE: Dict = {'fontsize': 10, }
# タイトルスタイル
TITLE_STYLE: Dict = {'fontsize': 11, }


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
    return FMT_JP_YEAR_MONTH.format(year=parts[0], month=parts[1])


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
        return FMT_AVEG_TEXT.format(**data_dict)

    s_ave = make_average_text(plot_label, f_ave, dict_ave)
    return Patch(color=s_color, label=s_ave)


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


def _temperature_plotting(
        ax_temp: Axes,
        df_curr: DataFrame, df_prev: DataFrame,
        curr_temp_ser: Series, prev_temp_ser: Series,
        main_title: str, curr_plot_label: str, prev_plot_label: str) -> None:
    """
    外気温領域のプロット
    :param ax_temp:外気温サブプロット(axes)
    :param df_curr:今年の年月DataFrame
    :param df_prev:前年の年月DataFrame
    :param curr_temp_ser: 現在の年月外気温データ
    :param prev_temp_ser: 前年の年月外気温データ
    :param main_title: タイトル
    :param curr_plot_label: 今年ラベル
    :param prev_plot_label: 前年ラベル
    """
    # 最低・最高
    set_ylim_with_axes(ax_temp, curr_temp_ser, prev_temp_ser)
    # 最新年月の外気温
    ax_temp.plot(df_curr[COL_TIME], curr_temp_ser, color=CURR_COLOR, marker="")
    val_ave = curr_temp_ser.mean()
    curr_patch = make_average_patch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVEG_TEMP)
    ax_temp.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月の外気温
    ax_temp.plot(df_prev[COL_PREV_PLOT_TIME], prev_temp_ser, color=PREV_COLOR, marker="")
    val_ave = prev_temp_ser.mean()
    prev_patch = make_average_patch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVEG_TEMP)
    ax_temp.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_temp.set_ylabel(Y_LABEL_TEMP_OUT, **LABEL_STYLE)
    # 凡例
    ax_temp.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)
    ax_temp.set_title(main_title, **TITLE_STYLE)
    # Hide xlabel
    ax_temp.label_outer()


def _humid_plotting(ax_humid: Axes,
                    df_curr: DataFrame, df_prev: DataFrame,
                    curr_humid_ser: Series, prev_humid_ser: Series,
                    curr_plot_label: str, prev_plot_label: str) -> None:
    """
    湿度サブプロット(axes)に軸・軸ラベルを設定し、DataFrameオプジェクトの室内湿度データをプロットする
    """
    ax_humid.set_ylim(ymin=0., ymax=100.)
    # 最新年月
    ax_humid.plot(df_curr[COL_TIME], curr_humid_ser, color=CURR_COLOR, marker="")
    val_ave = curr_humid_ser.mean()
    curr_patch = make_average_patch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVEG_HUMID)
    ax_humid.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月
    ax_humid.plot(df_prev[COL_PREV_PLOT_TIME], prev_humid_ser, color=PREV_COLOR, marker="")
    val_ave = prev_humid_ser.mean()
    prev_patch = make_average_patch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVEG_HUMID)
    ax_humid.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_humid.set_ylabel(Y_LABEL_HUMID, **LABEL_STYLE)
    # 凡例
    ax_humid.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)
    # Hide xlabel
    ax_humid.label_outer()


def _pressure_plotting(
        ax_pressure: Axes,
        df_curr: DataFrame, df_prev: DataFrame,
        curr_pressure_ser: Series, prev_pressure_ser: Series,
        curr_plot_label: str, prev_plot_label: str) -> None:
    """
    気圧サブプロット(axes)に軸・軸ラベルを設定し、DataFrameオプジェクトの気圧データをプロットする
    """
    # 最大値と最小値からY軸範囲を設定
    set_ylim_with_axes(ax_pressure, df_curr[COL_PRESSURE], df_prev[COL_PRESSURE])
    # 最新年月
    ax_pressure.plot(df_curr[COL_TIME], curr_pressure_ser, color=CURR_COLOR, marker="")
    val_ave = curr_pressure_ser.mean()
    curr_patch = make_average_patch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVEG_PRESSURE)
    ax_pressure.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月
    ax_pressure.plot(df_prev[COL_PREV_PLOT_TIME], prev_pressure_ser, color=PREV_COLOR, marker="")
    val_ave = prev_pressure_ser.mean()
    prev_patch = make_average_patch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVEG_PRESSURE)
    ax_pressure.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_pressure.set_ylabel(Y_LABEL_PRESSURE, **LABEL_STYLE)
    # 凡例
    ax_pressure.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)
    # X軸ラベル
    ax_pressure.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))


# 比較年月用の観測データの画像を生成する
def gen_plot_image(
        df_curr: DataFrame, df_prev: DataFrame, year_month: str, prev_year_month: str,
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
    # 今年年月
    curr_plot_label = make_legend_label(year_month)
    # 前年年月
    prev_plot_label = make_legend_label(prev_year_month)
    # タイトル
    title: str = FMT_MEASUREMENT_RANGE.format(curr_plot_label, prev_plot_label)

    # (1) 外気温データ(今年・前年)
    curr_temp_ser: Series = df_curr[COL_TEMP_OUT]
    prev_temp_ser: Series = df_prev[COL_TEMP_OUT]
    # (2) 湿度データ(今年・前年)
    curr_humid_ser: Series = df_curr[COL_HUMID]
    prev_humid_ser: Series = df_prev[COL_HUMID]
    # (3) 気圧データ(今年・前年)
    curr_pressure_ser: Series = df_curr[COL_PRESSURE]
    prev_pressure_ser: Series = df_prev[COL_PRESSURE]
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
    if logger is not None:
        logger.info(f"fig: {fig}")
    # x軸を共有する3行1列のサブプロット生成
    (ax_temp, ax_humid, ax_pressure) = fig.subplots(nrows=3, ncols=1, sharex=True)
    # Y方向のグリッド線のみ表示
    for ax in [ax_temp, ax_humid, ax_pressure]:
        ax.grid(**GRID_STYLE)

    # (1) 外気温領域のプロット
    _temperature_plotting(ax_temp,
                          df_curr, df_prev, curr_temp_ser, prev_temp_ser,
                          title, curr_plot_label, prev_plot_label)
    # (2) 湿度領域のプロット
    _humid_plotting(ax_humid,
                    df_curr, df_prev, curr_humid_ser, prev_humid_ser,
                    curr_plot_label, prev_plot_label)
    # (3) 気圧領域のプロット
    _pressure_plotting(ax_pressure,
                       df_curr, df_prev, curr_pressure_ser, prev_pressure_ser,
                       curr_plot_label, prev_plot_label)

    # 画像をバイトストリームに溜め込みそれをbase64エンコードしてレスポンスとして返す
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    if logger is not None:
        logger.debug(f"data.len: {len(data)}")
    # base64エンコード文字列
    return "data:image/png;base64," + data
