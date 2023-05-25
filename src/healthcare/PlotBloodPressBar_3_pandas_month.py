import argparse
import enum
import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.patches import Rectangle

import pandas as pd
from pandas.core.frame import DataFrame, Series

from util.file_util import gen_imgname

"""
健康管理DBからエクスポートした月間の血圧測定データ(欠損値あり)を棒グラフでプロット
[使用ライブラリ] pandas
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# ISO8601フォーマット
FMT_DATE: str = '%Y-%m-%d'

# 文字列定数定義
Y_PRESSURE_LABEL: str = "血圧値(mmHg)"
Y_PULSE_LABEL: str = "脈拍(回/分)"
LEGEND_PULSE_LABEL: str = "脈拍"

# 棒グラフの幅倍率
BAR_WIDTH: float = 0.7
# 最高血圧の基準値
STD_BLOOD_PRESS_MAX: float = 130.
# 最低血圧の基準値
STD_BLOOD_PRESS_MIN: float = 85.
# 脈拍の軸の最大値
LIM_MAX_PULSE: float = 100.
# x軸の左右マージン ※でーた1件を1としてその半分
X_LIM_MARGIN: float = -0.5
Y_LIM_MARGIN: float = 10.0
DRAW_POS_MARGIN: float = 0.5
# 血圧データの午前と午後の背景色リスト
BAR_COLORS: List = ['limegreen', 'darkorange']
COLOR_PULSE_RATE: str = 'blue'
COLOR_PRESS_MIN: str = 'white'

# スタイル辞書定数定義
# 棒の線スタイル
BAR_LINE_STYLE: Dict = {'edgecolor': 'black', 'linewidth': 0.7}
# X軸のラベル(日+曜日)スタイル
X_TICKS_STYLE: Dict = {'fontsize': 8, 'fontweight': 'bold', 'rotation': 90}
# 棒上端に表示するの線スタイル
BAR_LABEL_STYLE: Dict = {'fontsize': 8}
# 血圧の基準線の線スタイル
STD_LINE_STYLE: Dict = {'color': 'red', 'linestyle': 'dashed', 'linewidth': 1.0}
# 基準値を超えた値の表示文字列スタイル
DRAW_TEXT_BASE_STYLE: Dict = {'color': 'red', 'fontsize': 8, 'fontweight': 'demibold',
                              'horizontalalignment': 'center'}
#  (1) 縦揃え: 下段 ※棒の上
DRAW_TEXT_STYLE: Dict = {**DRAW_TEXT_BASE_STYLE, 'verticalalignment': 'bottom'}
#  (2) 縦揃え: 上段 ※棒の下
DRAW_TEXT_TOP_STYLE: Dict = {**DRAW_TEXT_BASE_STYLE, 'verticalalignment': 'top'}
# 描画領域のグリッド線スタイル: Y方向のグリッド線のみ表示
AXES_GRID_STYLE: Dict = {'axis': 'y', 'linestyle': 'dashed', 'linewidth': 0.7,
                         'alpha': 0.75}
# タイトルフォントスタイル
TITLE_FONT_STYLE: Dict = {'fontsize': 10, 'fontweight': 'medium'}
# 棒グラフ用凡例ラベルスタイル
BAR_LEGEND_LABEL_STYLE: Dict = {
    'fontsize': 10, 'horizontalalignment': 'left', 'verticalalignment': 'bottom'
}
# 凡例の位置は下右 ※領域の下限は超過値が表示されない
LEGEND_LOC: str = 'lower right'
# タイトルフォーマット
FMT_MEASUREMENT_RANGE: str = "【表示期間】{}〜{}"
# 日本語の曜日
JP_WEEK_DAY_NAMES: List[str] = ["月", "火", "水", "木", "金", "土", "日"]

# スマートフォンの描画領域サイズ (ピクセル): Google pixel 4a
PHONE_PX_WIDTH: int = 1064
PHONE_PX_HEIGHT: int = 1704
# 同上: 密度
PHONE_DENSITY: float = 2.75

# 血圧測定テーブルで利用するカラム
# "pid", 可視化に関係しない "morning_measurement_time", "evening_measurement_time"も除外
USE_COLS: List[str] = [
    "measurement_day",
    "morning_max", "morning_min", "morning_pulse_rate",
    "evening_max", "evening_min", "evening_pulse_rate"
]


class DrawPosition(enum.Enum):
    """ テキスト表示位置 """
    BOTTOM = 0
    TOP = 1


def calcEndOfMonth(str_year_month: str) -> int:
    """
    年月(文字列)の末日を計算する
    :param str_year_month: 年月(文字列, "-"区切り)
    :return: 末日
    """
    yearMonths = str_year_month.split("-")
    valYear, valMonth = int(yearMonths[0]), int(yearMonths[1])
    if valMonth == 12:
        valYear += 1
        valMonth = 1
    else:
        valMonth += 1
    # 月末日の翌月の1日
    valNextYearMonth = date(valYear, valMonth, 1)
    # 月末日の計算: 次の月-1日
    valLastDayOfMonth = valNextYearMonth - timedelta(days=1)
    return valLastDayOfMonth.day


def makeDateLabel(strIsoDay: str) -> str:
    """
    X軸の日付ラベル文字列を生成する\n
    [形式] "日 (曜日)"
    :param strIsoDay: ISO8601 日付文字列
    :return: 日付ラベル文字列
    """
    val_date: datetime = datetime.strptime(strIsoDay, FMT_DATE)
    weekday_name = JP_WEEK_DAY_NAMES[val_date.weekday()]
    return f"{val_date.day} ({weekday_name})"


def makeTitleWithMonthRange(str_yearMonth: str, val_endDay: int) -> str:
    def to_japanese_date(iso_date: str) -> str:
        """
        ISO8601フォーマット日付文字列を日本語の西暦("年","月","日")に置換する
        :param iso_date: ISO8601フォーマット日付文字列
        :return: 日本語の西暦
        """
        dates: List[str] = iso_date.split("-")
        return f"{dates[0]}年{dates[1]}月{dates[2]}日"

    # 指定年月の１日
    startDate: str = f"{str_yearMonth}-01"
    endDate: str = f"{str_yearMonth}-{val_endDay}"
    # 表示期間 (タイトル用)
    startJpDay: str = to_japanese_date(startDate)
    endJpDay: str = to_japanese_date(endDate)
    return FMT_MEASUREMENT_RANGE.format(startJpDay, endJpDay)


def makeColListForPlotting(df: DataFrame) ->\
        Tuple[List[str], np.ndarray, np.ndarray, np.ndarray]:
    """
    X軸用ラベルリスト、AM/PM毎の測定値をマージしたnp.ndarrayを生成する
    :param df:
    :return: X軸用ラベルリスト, 最高血圧値ndarray, 最低血圧値ndarray, 脈拍値ndarray
    """
    x_ticklers: List[str] = []
    pressMaxes: List[np.float] = []
    pressMines: List[np.float] = []
    pulseRates: List[np.float] = []
    # 月間(１日〜末日)の日付リスト
    indexes: Series = df.index
    mMaxSer: Series = df['morning_max']
    mMinSer: Series = df['morning_min']
    mPulseSer: Series = df['morning_pulse_rate']
    eMaxSer: Series = df['evening_max']
    eMinSer: Series = df['evening_min']
    ePulseSer: Series = df['evening_pulse_rate']
    for day, mMax, mMin, mPulse, eMax, eMin, ePulse in zip(
            indexes, mMaxSer, mMinSer, mPulseSer, eMaxSer, eMinSer, ePulseSer):
        x_ticklers.append(makeDateLabel(day.strftime(FMT_DATE)))  # AM軸
        x_ticklers.append("")  # PM軸 ※常に空文字
        pressMaxes.append(mMax)  # AM
        pressMaxes.append(eMax)  # PM
        pressMines.append(mMin)
        pressMines.append(eMin)
        pulseRates.append(mPulse)
        pulseRates.append(ePulse)
    # 測定値リストを np.ndarryに変換
    np_pressMaxes = np.array(pressMaxes)
    np_pressMines = np.array(pressMines)
    np_pulseRates = np.array(pulseRates)
    return x_ticklers, np_pressMaxes, np_pressMines, np_pulseRates


def pixelToInch(width_px: int, height_px: int, density: float) -> Tuple[float, float]:
    """
    携帯用の描画領域サイズ(ピクセル)をインチに変換する
    :param width_px: 幅(ピクセル)
    :param height_px: 高さ(ピクセル)
    :param density: 密度
    :return: 幅(インチ), 高さ(インチ)
    """
    px: float = 1 / rcParams["figure.dpi"]
    app_logger.info(f"figure.dpi[px]: {px}")
    px = px / (2.0 if density > 2.0 else density)
    app_logger.info(f"px[{density}]: {px}")
    inch_width = width_px * px
    inch_height = height_px * px
    app_logger.info(f"fig_width_inch: {inch_width}, fig_height_inch: {inch_height}")
    return inch_width, inch_height


def compute_y_lim_range(npPressMinValues: np.ndarray,
                        npPulseRateValues: np.ndarray,
                        npPressMaxValues: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Y軸の下限値(最低血圧値リストと脈拍値リストの比較)と上限値を計算する\n
      (1) 下限値 = floor(下限値/10)*10 - 10(マージン)\n
      (2) 上限値 = ceil(上限値/10)*10 + 10(マージン)\n
    :param npPressMinValues: 最低血圧値Numpyリスト (NaNを含む)
    :param npPulseRateValues: 脈拍値Numpyリスト (NaNを含む)
    :param npPressMaxValues: 最高血圧値Numpyリスト (NaNを含む)
    :return: Y軸の下限値, Y軸の上限値
    """
    # Y軸の下限値: 最低血圧値Numpyリスト + 脈拍値Numpyリスト
    npPressMinValues = np.append(npPressMinValues, npPulseRateValues)
    # NaNを含むNumpyリストの最小値
    np_y_lim_min = np.nanmin(npPressMinValues)
    # 10で割った値を切り捨てしたあとに10倍し-10
    np_y_lim_min = np.floor(np_y_lim_min / Y_LIM_MARGIN) * Y_LIM_MARGIN - Y_LIM_MARGIN
    # NaNを含むNumpyリストの最大値
    np_y_lim_max = np.nanmax(npPressMaxValues)
    # 10で割った値を切り上げしたあとに10倍し+10
    np_y_lim_max = np.ceil(np_y_lim_max / Y_LIM_MARGIN) * Y_LIM_MARGIN + Y_LIM_MARGIN
    return np_y_lim_min, np_y_lim_max


def drawTextOverValue(axes: matplotlib.pyplot.Axes, values: np.ndarray, std_value: float,
                      drawPos: DrawPosition = DrawPosition.BOTTOM) -> None:
    """
    基準値を超えた値を対応グラフの上部に表示する
    :param axes: プロット領域
    :param values: 値のnp.ndarray
    :param std_value: 基準値
    :param drawPos: 描画位置 (BOTTOM|TOP)
    """
    for x_idx, val in enumerate(values):
        if not np.isnan(val) and val > std_value:
            draw_margin: float
            draw_style: Dict
            if drawPos == DrawPosition.BOTTOM:
                draw_margin = val + DRAW_POS_MARGIN
                draw_style = DRAW_TEXT_STYLE
            else:
                draw_margin = val - DRAW_POS_MARGIN
                draw_style = DRAW_TEXT_TOP_STYLE
            axes.text(x_idx, draw_margin, str(val), **draw_style)


def drawCustomRectWithText(axes: matplotlib.pyplot.Axes,
                           label: str, rect_color: str,
                           x_rect_pos: float, y_rect_bottom: float,
                           rect_width: float, rect_height: float, x_text_pos) -> None:
    """
    カスタム矩形とその後ろにラベルを出力する
    :param axes: 描画対象
    :param label: ラベル
    :param rect_color: 矩形カラー
    :param x_rect_pos: カスタム矩形のX位置
    :param y_rect_bottom: カスタム矩形のY位置
    :param rect_width: カスタム矩形の幅
    :param rect_height: カスタム矩形の高さ
    :param x_text_pos: ラベルの出力位置
    """
    # 矩形を追加する
    axes.add_patch(
        Rectangle(
            xy=(x_rect_pos, y_rect_bottom), width=rect_width,
            height=rect_height, facecolor=rect_color, edgecolor='0.7')
    )
    # ラベル出力
    axes.text(x_text_pos, y_rect_bottom, label, **BAR_LEGEND_LABEL_STYLE)


def drawCustomBarLegend(axes: matplotlib.pyplot.Axes,
                        xPosStart: float, yPosBottom: float) -> None:
    """
    棒グラフの凡例(カラー付き矩形 + ラベル)出力
    :param axes: 描画領域
    :param xPosStart: X軸の出力開始位置 (左側)
    :param yPosBottom Y軸の出力開始位置 (下端)
    """
    sizeRatio: float = 0.1
    rectXStart: float = xPosStart + 20. * sizeRatio
    rectYBottom: float = yPosBottom + 20. * sizeRatio
    rectWidth: float = 42. * sizeRatio
    rectHeight: float = 28. * sizeRatio
    textXStart: float = rectXStart + rectWidth + 2.
    # 測定時刻 PMのカラーと見出し (下段)
    drawCustomRectWithText(axes, "PM 測定", BAR_COLORS[1],
                           rectXStart, rectYBottom, rectWidth, rectHeight,
                           textXStart)
    # 測定時刻 AMのカラーと見出し (上段)
    rectYBottom += rectHeight + 1
    drawCustomRectWithText(axes, "AM 測定", BAR_COLORS[0],
                           rectXStart, rectYBottom, rectWidth, rectHeight,
                           textXStart)


if __name__ == '__main__':
    logging.basicConfig(format=LOG_FMT)
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(level=logging.DEBUG)

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    # プロット対象年月
    parser.add_argument("--year-month", type=str, required=True,
                        help="年月 (例) 2023-04")
    # 血圧測定CSVデータファイルパス: 年月のみか、複数月
    parser.add_argument("--blood-press", type=str, required=True,
                        help="datas/csv/blood_pressure.csv")
    args: argparse.Namespace = parser.parse_args()
    app_logger.info(args)

    # CSVファイルの存在チェック
    path_csv: str = os.path.expanduser(args.blood_press)
    # スクリプト直下の相対ファイルか、ユーザホームのCSV格納ディレクトリのファイル
    if not os.path.exists(path_csv):
        app_logger.warning("CSV not found.")
        exit(1)

    year_month: str = args.year_month
    # 指定年月の開始日
    start_date: str = f"{year_month}-01"
    # 指定年月の月末日
    endDay: int = calcEndOfMonth(year_month)
    # 指定年月の終了日
    end_date: str = f"{year_month}-{endDay:#02d}"
    # グラフタイトル (月間範囲)
    titleDateRange: str = makeTitleWithMonthRange(year_month, endDay)

    # CSVファイル読み込み
    df_main: DataFrame = pd.read_csv(
        path_csv, header=0,
        parse_dates=['measurement_day'], date_format=FMT_DATE,
        usecols=USE_COLS
    )
    # 測定日をインデックスに設定
    df_main.index = df_main['measurement_day']
    app_logger.info(df_main.index)

    # 当該年月の期間に欠損値があればインデックス振り直す
    org_dataSize: int = df_main.index.shape[0]
    app_logger.info(f"org_dataSize:{org_dataSize}")
    if org_dataSize < endDay:
        # 単月データで欠損値有り (測定日未登録)
        app_logger.info(f"{org_dataSize} < endDay: {endDay}")
        df_main = df_main.reindex(
            pd.date_range(start=start_date, end=end_date, name='measurement_day')
        )
    else:
        # 複数月にまたがるCSV
        app_logger.info(f"filter[{start_date} : {end_date}]")
        # 月間データを取り出す [月の1日:末日]
        df_main = df_main.loc[start_date:end_date]
        filtered_dataSize: int = df_main.shape[0]
        app_logger.info(f"filtered_dataSize: {filtered_dataSize}")
        # 月間データに欠損データが有る場合は埋める
        if filtered_dataSize < endDay:
            df_main = df_main.reindex(
                pd.date_range(start=start_date, end=end_date, name='measurement_day')
            )
    app_logger.info(df_main.shape)
    app_logger.info(df_main)

    # 血圧測定データは日当たりAM/PMの各測定値があるためマージする
    # Pandasで読み込んだ場合、データはnp.ndarrayになっており欠損値はNaNに設定されている
    # 月間のプロット用項目(X軸ラベル, 最高血圧, 最低血圧, 脈拍)リスト生成
    #  pressMaxValues, pressMinValues, pulseRateValues: ndarrayで欠損値は np.nanに設定済み
    xTicksLabels, pressMaxValues, pressMinValues, pulseValues = makeColListForPlotting(
        df_main
    )

    # データ件数(月間: 1〜末日までの日数)
    dateRangeSize: int = df_main.shape[0]
    # 棒のカラー配列を作成: AM/PM毎にデータ件数分
    barColors: List[str] = BAR_COLORS * dateRangeSize
    app_logger.info(f"xTicksLabels:\n{xTicksLabels}")
    app_logger.info(f"pressMaxValues:\n{pressMaxValues}")
    app_logger.info(f"pressMinValues:\n{pressMinValues}")
    app_logger.info(f"pulseRateValues:\n{pulseValues}")
    # 最高血圧棒グラフ用差分
    barMaxDiffValues: np.ndarray = pressMaxValues - pressMinValues

    # Y軸の最小値と最大値を計算
    yLimMin: float
    yLimMax: float
    yLimMin, yLimMax = compute_y_lim_range(
        pressMinValues, pulseValues, pressMaxValues
    )
    app_logger.info(f"yLimMin={yLimMin}, yLimMax={yLimMax}")

    # 携帯用の描画領域サイズ(ピクセル)をインチに変換
    figWidthInch, figHeightInch = pixelToInch(
        PHONE_PX_WIDTH, PHONE_PX_HEIGHT, PHONE_DENSITY
    )

    # 描画領域作成
    fig: Figure
    ax: Axes
    fig, ax = plt.subplots(figsize=(figWidthInch, figHeightInch), layout='constrained')
    # Y方向のグリッド線のみ表示
    ax.grid(**AXES_GRID_STYLE)
    app_logger.info(f"fig: {fig}, axes: {ax}")

    # X軸の作成: データ件数 * 2 (AM + PM)
    xIndexes = np.arange(dateRangeSize * 2)
    # 最低血圧値の棒グラフ: 描画領域色(白色)にして見えないようにする
    ax.bar(xIndexes, pressMinValues, BAR_WIDTH, color=COLOR_PRESS_MIN)
    # 最大血圧値(最低血圧値との差分): 棒のカラー(AMカラー/PMカラー交互)
    ax.bar(
        xIndexes, barMaxDiffValues, BAR_WIDTH,
        bottom=pressMinValues, color=barColors, **BAR_LINE_STYLE
    )
    # 最高血圧の基準値
    ax.axhline(y=STD_BLOOD_PRESS_MAX, **STD_LINE_STYLE)
    # 最低血圧の基準
    ax.axhline(y=STD_BLOOD_PRESS_MIN, **STD_LINE_STYLE)
    ax.set_ylabel(Y_PRESSURE_LABEL)
    ax.set_title(titleDateRange, fontdict=TITLE_FONT_STYLE)
    # 最大値を+1することにより最大値が表示される
    ax.set_yticks(np.arange(yLimMin, yLimMax + 1, Y_LIM_MARGIN))
    ax.set_ylim(yLimMin, yLimMax)
    ax.set_xticks(np.arange(dateRangeSize * 2), xTicksLabels, **X_TICKS_STYLE)
    ax.set_xlim(X_LIM_MARGIN, (dateRangeSize * 2 + X_LIM_MARGIN))
    # 最高血圧: 基準値を超えた値のみを上端に表示
    drawTextOverValue(ax, pressMaxValues, STD_BLOOD_PRESS_MAX)
    # 棒グラフ(AM/PM毎のカラー)の凡例を描画
    drawCustomBarLegend(ax, X_LIM_MARGIN, yLimMin)

    # 右側軸: 脈拍は折れ線グラフ
    ax_pulseRate: Axes = ax.twinx()
    ax_pulseRate.set_ylabel(Y_PULSE_LABEL)
    ax_pulseRate.plot(xIndexes, pulseValues, color=COLOR_PULSE_RATE,
                      label=LEGEND_PULSE_LABEL)
    # 脈拍の軸ラベルは脈拍の軸の最大値+1まで表示
    ax_pulseRate.set_yticks(np.arange(yLimMin, LIM_MAX_PULSE + 1, Y_LIM_MARGIN))
    ax_pulseRate.set_ylim(yLimMin, yLimMax)
    ax_pulseRate.legend(loc=LEGEND_LOC)

    # プロット画像をファイル-族
    save_name = gen_imgname(script_name)
    save_path = os.path.join("screen_shots", save_name)
    app_logger.info(save_path)
    fig.savefig(save_path, format="png", bbox_inches="tight")
