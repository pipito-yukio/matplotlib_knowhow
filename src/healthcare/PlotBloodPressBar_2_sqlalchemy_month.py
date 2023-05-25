import argparse
import enum
import logging
import json
import os
import socket
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.patches import Rectangle

import sqlalchemy
from sqlalchemy.engine.url import URL
from sqlalchemy import create_engine
from sqlalchemy.engine import Result
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import text

from util.file_util import gen_imgname

"""
データベースから取得した月間の血圧測定データ(欠損値あり)を棒グラフでプロット
(1) sqlalchemyモジュール使用
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 健康管理データベース接続情報
DB_HEALTHCARE_CONF: str = os.path.join("conf", "db_healthcare.json")
# 血圧測定テーブルデータ取得クエリ
QUERY_BLOOD_PRESS = """
SELECT
  to_char(measurement_day,'YYYY-MM-DD') as measurement_day
  ,to_char(morning_measurement_time,'HH24:MI') as morning_measurement_time
  ,morning_max
  ,morning_min
  ,morning_pulse_rate
  ,to_char(evening_measurement_time, 'HH24:MI') as evening_measurement_time
  ,evening_max
  ,evening_min
  ,evening_pulse_rate
FROM
  bodyhealth.person p
  INNER JOIN bodyhealth.blood_pressure bp ON p.id = bp.pid
WHERE
  email=:emailAddress
  AND
  measurement_day BETWEEN :startDay AND :endDay
  ORDER BY measurement_day
"""

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


class DrawPosition(enum.Enum):
    """ テキスト表示位置 """
    BOTTOM = 0
    TOP = 1


@dataclass
class BloodPressure:
    """ 血圧測定レコードを保持するデータクラス """
    morningMeasurementTime: str
    morningMax: int
    morningMin: int
    morningPulseRate: int
    eveningMeasurementTime: str
    eveningMax: int
    eveningMin: int
    eveningPulseRate: int


def getDBConnectionWithDict(filePath: str) -> dict:
    """
    SQLAlchemyの接続URL用の辞書オブジェクトを取得する
    :param filePath: 接続設定ファイルパス (JSON形式)
    :return: SQLAlchemyのURL用辞書オブジェクト
    """
    with open(filePath, 'r') as fp:
        db_conf: json = json.load(fp)
        hostname = socket.gethostname()
        # host in /etc/hostname: "hostname.local"
        db_conf["host"] = db_conf["host"].format(hostname=hostname)
    return db_conf


def getRecordsWithDict(DbSession: sqlalchemy.orm.scoping.scoped_session,
                       mailAddress: str, startDate: str, endDate: str
                       ) -> Dict[str, BloodPressure]:
    """
    血圧測定テーブルから月間の血圧測定データを取得する
    :param DbSession: 健康管理データベースセッションクラス
    :param mailAddress: メールアドレス (主キー)
    :param startDate: 開祖日
    :param endDate: 終了日
    :return: 月間の血圧測定データ(日付をキーとする辞書オブジェクト)
    """
    params: Dict = {
        "emailAddress": mailAddress, "startDay": startDate, "endDay": endDate}
    rows = None
    try:
        with DbSession() as sess:
            rs: Result = sess.execute(text(QUERY_BLOOD_PRESS), params)
            if rs:
                rows = rs.fetchall()
    except SQLAlchemyError as err:
        app_logger.warning(err.args)
        raise err

    result: Dict[str, BloodPressure] = {}
    if rows:
        for (measurement_day,
             morning_measurement_time, morning_max, morning_min, morning_pulse_rate,
             evening_measurement_time, evening_max, evening_min, evening_pulse_rate
             ) in rows:
            rec_data: BloodPressure = BloodPressure(*(
                morning_measurement_time, morning_max, morning_min, morning_pulse_rate,
                evening_measurement_time, evening_max, evening_min, evening_pulse_rate
            ))
            result[measurement_day] = rec_data
    return result


def makeColListForPlotting(pPlotDateRanges: List[str],
                           pRecordsWithDict: Dict[str, BloodPressure]) -> Tuple:
    """
    月間のプロット用項目別(X軸ラベル, 最高血圧, 最低血圧, 脈拍)リスト生成\n
      測定データはレコードデータが存在すればレコードからそのまま代入\n
      存在しない場合は Noneを設定
    :param pPlotDateRanges: 月間日付リスト
    :param pRecordsWithDict: 月間の血圧測定データ(日付をキーとする辞書オブジェクト)
    :return: 月間のプロット用項目別(X軸ラベル, 最高血圧, 最低血圧, 脈拍)リスト
    """
    # X軸ラベル (AM/PM)
    rawTicksLabels: List[str] = []
    # 最高血圧値 (AM/PM)
    rawPressMaxes: List[Optional[int]] = []
    # 最低血圧値 (AM/PM)
    rawPressMines: List[Optional[int]] = []
    # 脈拍 (AM/PM)
    rawPulseRates: List[Optional[int]] = []
    # 月間の日付範囲と取得レコードの日付をマッチング
    for row_idx, str_date in enumerate(pPlotDateRanges):
        # 月間の血圧データの場合はX軸ラベルは日付のみとする ※PM軸はブランクのみ
        rawTicksLabels.append(makeDateLabel(str_date))
        if str_date in recordsWithDict.keys():
            # レコードを取り出す
            data: BloodPressure = pRecordsWithDict[str_date]
            # PM用ラベルは設定しない
            rawTicksLabels.append("")
            # 最高血圧(AM/PM)
            rawPressMaxes.append(data.morningMax)
            rawPressMaxes.append(data.eveningMax)
            # 最低血圧(AM/PM)
            rawPressMines.append(data.morningMin)
            rawPressMines.append(data.eveningMin)
            # 脈拍(AM/PM)
            rawPulseRates.append(data.morningPulseRate)
            rawPulseRates.append(data.eveningPulseRate)
        else:
            rawTicksLabels.append("")
            rawPressMaxes.append(None)
            rawPressMaxes.append(None)
            rawPressMines.append(None)
            rawPressMines.append(None)
            rawPulseRates.append(None)
            rawPulseRates.append(None)
    return rawTicksLabels, rawPressMaxes, rawPressMines, rawPulseRates


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
    val_date: datetime = datetime.strptime(strIsoDay, "%Y-%m-%d")
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


def convertBarValues(pressMaxes: List[Optional[int]],
                     pressMines: List[Optional[int]]) -> Tuple[np.ndarray, np.ndarray]:
    """
    最高血圧値リスト、最低血圧値リストからそれぞれの描画(棒)オブジェクトを生成する\n
    リストの中にNoneが含まれていた場合は np.NaN に置き換える\n
    (データの性質) 最高血圧値が存在すれば最低血圧も存在する、存在しなけれは他の値も全て存在しない
    :param pressMaxes: 最高血圧値リスト(欠損値 Noneを含む)
    :param pressMines: 最低血圧値リスト(欠損値 Noneを含む)
    :return: 最高血圧棒グラフ用Numpyリスト (最低血圧値を差し引き), 最低血圧棒グラフ用Numpyリスト
    """
    max_diff_values: List[Any] = []
    min_values: List[Any] = []
    for val_max, val_min in zip(pressMaxes, pressMines):
        if val_max is not None and val_min is not None:
            # 最高血圧値の棒は積み上げ式にするために最低血圧値との差分
            max_diff_values.append((val_max - val_min))
            # 最低血圧値
            min_values.append(val_min)
        else:
            # 両方NaN(未設定)
            max_diff_values.append(np.NaN)
            min_values.append(np.NaN)
    return np.array(max_diff_values), np.array(min_values)


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


def drawTextOverValue(axes: matplotlib.pyplot.Axes, valList: List, std_value: float,
                      drawPos: DrawPosition = DrawPosition.BOTTOM) -> None:
    """
    基準値を超えた値を対応グラフの上部に表示する
    :param axes: プロット領域
    :param valList: 値リスト
    :param std_value: 基準値
    :param drawPos: 描画位置 (BOTTOM|TOP)
    """
    for x_idx, val in enumerate(valList):
        if val is not None and val > std_value:
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
    # メールアドレス (例) user1@examples.com
    parser.add_argument("--mail-address", type=str, required=True,
                        help="Healthcare Database Person mailAddress.")
    # 年月
    parser.add_argument("--year-month", type=str, required=True,
                        help="年月 (例) 2023-04")
    args: argparse.Namespace = parser.parse_args()
    app_logger.info(args)

    # 選択クエリーの主キー: メールアドレス
    mail_address: str = args.mail_address
    year_month: str = args.year_month
    # 選択クエリーのパラメータ: 指定年月の開始日
    start_date: str = f"{year_month}-01"
    # 指定年月の月末日
    endDay: int = calcEndOfMonth(year_month)
    # 選択クエリーのパラメータ: 指定年月の終了日
    end_date: str = f"{year_month}-{endDay:#02d}"
    # 月間タイトル
    titleDateRange: str = makeTitleWithMonthRange(year_month, endDay)
    # 当該年月の期間(文字列): 当該年月の1日〜末日
    plotDateRanges: List[str] = [
        "{}-{:#02d}".format(year_month, day) for day in range(1, endDay + 1)
    ]
    app_logger.info(plotDateRanges)

    # 健康管理データベース
    # SQLAlchemyデータベース接続URL用辞書オブジェクト取得
    connDict: dict = getDBConnectionWithDict(DB_HEALTHCARE_CONF)
    connUrl: URL = URL.create(**connDict)
    engineHealthcare: sqlalchemy.Engine = create_engine(connUrl, echo=False)
    # Flaskアプリで使うscoped_sessionに合わせるためバッチでもscoped_sessionクラスを生成する
    Cls_sess_healthcare: sqlalchemy.orm.scoping.scoped_session = scoped_session(
        sessionmaker(bind=engineHealthcare)
    )
    app_logger.info(f"Cls_sess_healthcare: {Cls_sess_healthcare}")

    # 血圧測定テーブルから月間レコードを日付と血圧データの辞書オブジェクトとして取得
    recordsWithDict: Dict[str, BloodPressure] = getRecordsWithDict(
        Cls_sess_healthcare, mail_address, start_date, end_date
    )

    # 月間のプロット用項目別(X軸ラベル, 最高血圧, 最低血圧, 脈拍)リスト生成
    xTicksLabels, pressMaxList, pressMinList, pulseRateList = makeColListForPlotting(
        plotDateRanges, recordsWithDict
    )

    # データ件数(月間: 1〜末日までの日数)
    dateRangeSize: int = len(plotDateRanges)
    # 棒のカラー配列を作成: AM/PM毎にデータ件数分
    barColors: List[str] = BAR_COLORS * dateRangeSize
    # 血圧値(最高,最低)棒グラフ用Numpyリスト作成
    barMaxDiffValues, barMinValues = convertBarValues(pressMaxList, pressMinList)
    # Y軸の最大値計算用Numpyリスト (Noneを np.NaNに変換)
    yLimMaxValues: np.ndarray = np.array([
        (val if val is not None else np.NaN) for val in pressMaxList]
    )
    # 折れ線グラフ(脈拍)用Numpyリスト (Noneを np.NaNに変換)
    pulseValues: np.ndarray = np.array([
        (val if val is not None else np.NaN) for val in pulseRateList]
    )
    app_logger.info(f"barMaxDiffValues:\n{barMaxDiffValues}")
    app_logger.info(f"barMinValues:\n{barMinValues}")
    app_logger.info(f"linePulseRateValues:\n{pulseValues}")
    app_logger.info(f"yLimMaxValues:\n{yLimMaxValues}")

    # Y軸の最小値と最大値を計算
    yLimMin: float
    yLimMax: float
    yLimMin, yLimMax = compute_y_lim_range(
        barMinValues, pulseValues, yLimMaxValues
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
    # グリッド線
    ax.grid(**AXES_GRID_STYLE)
    app_logger.info(f"fig: {fig}, axes: {ax}")

    # X軸の作成: データ件数 * 2 (AM + PM)
    xIndexes = np.arange(dateRangeSize * 2)
    # 最低血圧値の棒グラフ: 描画領域色(白色)にして見えないようにする
    ax.bar(xIndexes, barMinValues, BAR_WIDTH, color=COLOR_PRESS_MIN)
    # 最大血圧値(最低血圧値との差分): 棒のカラー(AMカラー/PMカラー交互)
    ax.bar(
        xIndexes, barMaxDiffValues, BAR_WIDTH,
        bottom=barMinValues, color=barColors, **BAR_LINE_STYLE
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
    drawTextOverValue(ax, pressMaxList, STD_BLOOD_PRESS_MAX)
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
