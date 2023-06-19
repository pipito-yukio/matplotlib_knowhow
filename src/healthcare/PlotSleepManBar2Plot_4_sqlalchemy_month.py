import argparse
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
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

import sqlalchemy
from sqlalchemy.engine.url import URL
from sqlalchemy import create_engine
from sqlalchemy.engine import Result
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import text

import util.date_util as du
from util.file_util import gen_imgname

"""
健康管理DBから取得した月間の睡眠管理データ(夜間頻尿要因データの一部を結合)を棒グラフでプロット
[使用ライブラリ] sqlalchemy
(1) 睡眠管理テーブル: 全ての項目
    [下段領域(メイン)] 睡眠管理グラフ [X軸] 日付(曜日)+起床時刻
(2) 夜間頻尿要因テーブル: 夜間トイレ回数のみ
    [上段領域] 夜間トイレ回数 [X軸] 就寝時刻
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 健康管理データベース接続情報
DB_HEALTHCARE_CONF: str = os.path.join("conf", "db_healthcare.json")

# ISO8601フォーマット
FMT_DATE: str = '%Y-%m-%d'
# datetime変換フォーマット ※ SQLで "%H:%M"にフォーマット済み
FMT_DATETIME: str = '%Y-%m-%d %H:%M'

# 棒グラフの幅倍率
BAR_WIDTH: float = 0.7
# 睡眠スコアの最大値
SCORE_MAX: float = 100
# 睡眠スコアステップ
SCORE_STEP: float = 10
# 睡眠時間(単位:分)の最小値
SLEEP_TIME_MIN: int = 0
# 睡眠時間(単位:分)の最大値: 12時間
SLEEP_TIME_MAX: int = 12 * 60
# Y軸(睡眠時間): 30分間隔で水平線を描画
SLEEP_TIME_STEP: int = 30
# X軸のマージン
X_LIM_MARGIN: float = -0.5
# 睡眠スコア(下限): 非常に良い (90〜100)
RATE_SCORE_BEST: float = 0.9
# 睡眠スコア(下限): 良い (80〜89)
RATE_SCORE_GOOD: float = 0.8
# 睡眠スコア(下限): やや低い (60〜79)
# 睡眠スコア(下限): 低い (60未満)
RATE_SCORE_BAD: float = 0.6
# 睡眠スコアの背景色
#  非常に良い (90〜100)
COLOR_SCORE_BEST: str = 'gold'
#  良い (80〜89)
COLOR_SCORE_GOOD: str = 'lime'
#  やや低い (60〜79)
COLOR_SCORE_WORNING: str = 'red'
#  低い (60未満)
COLOR_SCORE_BAD: str = 'gray'
# 睡眠スコアが基準値以上の場合に描画するマーカー色
#   非常に良い(90)以上
MARKER_COLOR_SCORE_BEST: str = 'red'
#   良い(80)以上
MARKER_COLOR_SCORE_GOOD: str = 'green'
#   悪い
MARKER_COLOR_SCORE_BAD: str = 'gray'
# 折れ線の色: 睡眠スコア
SCORE_LINE_COLOR: str = 'black'
# 棒グラフの色: 睡眠時間
COLOR_BAR_SLEEPING: str = 'gold'
# 棒グラフの色: 深い睡眠時間
COLOR_BAR_DEEP_SLEEPING: str = 'violet'
# 凡例ラベル
LABEL_SLEEPING: str = '睡眠時間 (時:分)'
LABEL_DEEP_SLEEPING: str = '深い睡眠 (分)'
LABEL_SLEEP_SCORE: str = '睡眠スコア'
# 上端領域Y軸ラベル
TOP_AXES_LABEL: str = '夜間トイレ回数'
TOILET_VISITS_MIN: int = 0
TOILET_VISITS_MAX: int = 6

# スタイル辞書定数定義
# 睡眠スコア折れ線グラフスタイル
SCORE_LINE_STYLE: Dict = {'color': SCORE_LINE_COLOR, 'linewidth': 1.0}
# 睡眠スコア折れ線グラフスタイル
SCORE_TICKS_STYLE: Dict = {'color': SCORE_LINE_COLOR, 'fontsize': 9,
                           'fontweight': 'demibold'}
# 棒グラフの外郭線スタイル
BAR_LINE_STYLE: Dict = {'edgecolor': 'black', 'linewidth': 0.7}
# X軸のラベル(日+曜日)スタイル
X_TICKS_STYLE: Dict = {'fontsize': 9, 'fontweight': 'heavy', 'rotation': 90}
# 上段: X軸のラベル(起床時間)スタイル
TOP_X_TICKS_STYLE: Dict = {'fontsize': 8, 'fontweight': 'heavy', 'rotation': 90}
# 棒グラフの上部に出力する睡眠時間(時:分)のフォントスタイル
TIME_TICKS_STYLE: Dict = {'fontsize': 9}
# 深い睡眠用(分)スタイル: 赤
BAR_LABEL_STYLE: Dict = {'color': 'red', 'fontsize': 8, 'fontweight': 'heavy'}
# 睡眠時間用(時:分)スタイル: 黒
PLOT_TEXT_STYLE: Dict = {'fontsize': 8, 'fontweight': 'demibold',
                         'horizontalalignment': 'center', 'verticalalignment': 'bottom'}
# タイトルフォントスタイル
TITLE_FONT_DICT: Dict = {'fontsize': 9, 'fontweight': 'medium'}
# スキャッターマーカースタイル
MARKER_SIZE_WITH_MONTH: float = 9.
# https://matplotlib.org/stable/gallery/shapes_and_collections/scatter.html
# matplotlib.pyplot.scatter
#  #sphx-glr-gallery-shapes-and-collections-scatter-py
SCATTER_SCORE_BEST_STYLE: Dict = {
    'color': MARKER_COLOR_SCORE_BEST, 's': MARKER_SIZE_WITH_MONTH}
SCATTER_SCORE_GOOD_STYLE: Dict = {
    'color': MARKER_COLOR_SCORE_GOOD, 's': MARKER_SIZE_WITH_MONTH}
SCATTER_SCORE_NORMAL_STYLE: Dict = {
    'color': SCORE_LINE_COLOR, 's': MARKER_SIZE_WITH_MONTH}
SCATTER_SCORE_BAD_STYLE: Dict = {
    'color': MARKER_COLOR_SCORE_BAD, 's': MARKER_SIZE_WITH_MONTH}
# 上段: 夜間トイレ回数マーカースタイル ※一回り小さく
SCATTER_TOILET_VISITS_STYLE: Dict = {'color': 'blue', 's': 8.}

# 描画領域のグリッド線スタイル: Y方向のグリッド線のみ表示
AXES_GRID_STYLE: Dict = {'axis': 'y', 'linestyle': 'dashed', 'linewidth': 0.7,
                         'alpha': 0.75}
# 上段プロット領域:下段プロット領域比
GRID_SPEC_HEIGHT_RATIO: List[int] = [1, 5]
# 凡例位置 (上端,右側) ※睡眠スコア値が上端にプロットされることはまれのためプロットが隠れることが無い
LEGEND_LOC: str = 'upper right'
# タイトルフォーマット
FMT_MEASUREMENT_RANGE: str = "【表示期間】{}〜{}"
# 日本語の曜日
JP_WEEK_DAY_NAMES: List[str] = ["月", "火", "水", "木", "金", "土", "日"]

# スマートフォンの描画領域サイズ (ピクセル): Google pixel 4a
PHONE_PX_WIDTH: int = 1064
PHONE_PX_HEIGHT: int = 1704
# 同上: 密度
PHONE_DENSITY: float = 2.75

# 睡眠管理テーブルデータ取得クエリ
QUERY_SLEEP_MAN = """
SELECT
  to_char(sm.measurement_day,'YYYY-MM-DD') as measurement_day
  ,to_char(wakeup_time,'HH24:MI') as wakeup_time
  ,sleep_score
  ,to_char(sleeping_time, 'HH24:MI') as sleeping_time
  ,to_char(deep_sleeping_time, 'HH24:MI') as deep_sleeping_time
  ,midnight_toilet_visits
FROM
  bodyhealth.person p
  INNER JOIN bodyhealth.sleep_management sm ON p.id = sm.pid
  INNER JOIN bodyhealth.nocturia_factors nf ON p.id = nf.pid
WHERE
  email=:emailAddress
  AND
  sm.measurement_day BETWEEN :startDay AND :endDay
  AND
  sm.measurement_day = nf.measurement_day
  ORDER BY sm.measurement_day
"""


@dataclass
class SleepManJoined:
    """ 睡眠管理レコードと夜間頻尿要因の一部を保持するデータクラス """
    wakeupTime: str
    sleepScore: int
    sleepingTime: str
    deepSleepingTime: str
    # 以下 夜間頻尿要因
    midnight_toilet_visits: int


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
                       ) -> Dict[str, SleepManJoined]:
    """
    睡眠管理テーブルから月間の睡眠管理データを取得する
    :param DbSession: 健康管理データベースセッションクラス
    :param mailAddress: メールアドレス (主キー)
    :param startDate: 開祖日
    :param endDate: 終了日
    :return: 月間の睡眠管理データ(日付をキーとする辞書オブジェクト)
    """
    params: Dict = {
        "emailAddress": mailAddress, "startDay": startDate, "endDay": endDate}
    rows = None
    try:
        with DbSession() as sess:
            rs: Result = sess.execute(text(QUERY_SLEEP_MAN), params)
            if rs:
                rows = rs.fetchall()
    except SQLAlchemyError as err:
        app_logger.warning(err.args)
        raise err

    result: Dict[str, SleepManJoined] = {}
    if rows:
        for (measurement_day,
             wakeup_time, sleep_score, sleeping_time, deep_sleeping_time,
             midnight_toilet_visits) in rows:
            rec_data: SleepManJoined = SleepManJoined(*(
                wakeup_time, sleep_score, sleeping_time, deep_sleeping_time,
                midnight_toilet_visits
            ))
            app_logger.debug(f"{measurement_day}: {rec_data}")
            result[measurement_day] = rec_data
    return result


def makeColsForPlotting(pPlotDateRanges: List[str],
                        pRecordsWithDict: Dict[str, SleepManJoined]) -> Tuple:
    """
    月間のプロット用項目別(X軸ラベル, 睡眠スコア, 睡眠時間, 深い睡眠)リスト生成\n
      測定データはレコードデータが存在すればレコードからそのまま代入\n
      存在しない場合は Noneを設定
    :param pPlotDateRanges: 月間日付リスト
    :param pRecordsWithDict: 月間の睡眠管理データ(日付をキーとする辞書オブジェクト)
    :return: 月間のプロット用項目別(X軸ラベル, 睡眠スコア, 睡眠時間, 深い睡眠)リスト
    """
    # X軸ラベル
    _ticksLabels: List[str] = []
    # 睡眠スコア
    _sleepScores: List[Optional[int]] = []
    # 睡眠時間
    _sleepingTimes: List[Optional[str]] = []
    # 深い睡眠
    _deepSleepingTimes: List[Optional[str]] = []
    # 起床時間 (計算項目)
    _betTimes: List[Optional[datetime]] = []
    # 月間の日付範囲と取得レコードの日付をマッチング
    for idx, curr_date in enumerate(pPlotDateRanges):
        if curr_date in recordsWithDict.keys():
            # レコードを取り出す
            data: SleepManJoined = pRecordsWithDict[curr_date]
            _date_tick_label: str = f"{makeDateLabel(curr_date)} {data.wakeupTime}"
            _ticksLabels.append(_date_tick_label)
            # 睡眠スコア
            _sleepScores.append(data.sleepScore)
            _sleepingTimes.append(data.sleepingTime)
            _deepSleepingTimes.append(data.deepSleepingTime)
            # 起床時間の計算
            if data.sleepingTime is not None:
                bedTime: datetime = calcBedTime(
                    curr_date, data.wakeupTime, data.sleepingTime)
                _betTimes.append(bedTime)
            else:
                _betTimes.append(None)
        else:
            _ticksLabels.append(makeDateLabel(curr_date) + "      ")
            _sleepScores.append(None)
            _sleepingTimes.append(None)
            _deepSleepingTimes.append(None)
            _betTimes.append(None)
    return _ticksLabels, _sleepScores, _sleepingTimes, _deepSleepingTimes, _betTimes


def makeNocturiaColListForPlotting(
        pPlotDateRanges: List[str],
        pRecordsWithDict: Dict[str, SleepManJoined]) -> List[Optional[int]]:
    """
    夜間トイレ回数リスト取得
    :param pPlotDateRanges: プロット用日付範囲リスト
    :param pRecordsWithDict: レコード辞書オブジェクト
    :return: 夜間トイレ回数リスト
    """
    _midnightToiletVisits: List[Optional[int]] = []
    for idx, curr_date in enumerate(pPlotDateRanges):
        if curr_date in recordsWithDict.keys():
            data: SleepManJoined = pRecordsWithDict[curr_date]
            _midnightToiletVisits.append(data.midnight_toilet_visits)
        else:
            _midnightToiletVisits.append(None)
    return _midnightToiletVisits


def toMinute(strTime: str) -> Optional[int]:
    """
    時刻文字列("時:分")を分に変換する
    :param strTime: 時刻文字列("時:分") ※欠損値有り(None)
    :return: 分(整数), NoneならNone
    """
    if strTime is None:
        return None

    times: List[str] = strTime.split(":")
    return int(times[0]) * 60 + int(times[1])


def minuteToFormatTime(val_minutes: int) -> str:
    """
    分を時刻文字列("%H:%M")に変換する
    :param val_minutes: 分
    :return: 時刻文字列("%H:%M")
    """
    return f"{val_minutes // 60:#02d}:{val_minutes % 60:#02d}"


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


def calcBedTime(strDate: datetime, strWakeupTime: str, strSleepingTime: str
                ) -> Optional[datetime]:
    """
    就寝時刻(前日)を計算する
    :param strDate: 測定日付文字列(ISO8601) ※必須
    :param strWakeupTime: 起床時刻文字列 ("%H:%M") ※必須
    :param strSleepingTime: 睡眠時間 ("%H:%M") ※任意 欠損値 None
    :return: (測定日付+起床時刻) - 睡眠時間
    """
    if strSleepingTime is None:
        return None

    wakeupDayTime: datetime = datetime.strptime(f"{strDate} {strWakeupTime}",
                                                FMT_DATETIME)
    valMinutes: int = toMinute(strSleepingTime)
    return wakeupDayTime - timedelta(minutes=valMinutes)


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


def removeTimeHeadZero(str_time: str) -> str:
    """
    時間の先頭"0"をトリムする ※棒グラフの上部に表示する時刻
    :param str_time: 時刻文字列 ("%H:%M")
    :return: 時間の先頭の"0"をトリムした時刻文字列
    """
    if str_time.startswith("0"):
        return str_time[1:]
    return str_time


def makeTitleWithMonthRange(str_yearMonth: str, val_endDay: int) -> str:
    """
    タイトル用月間日付範囲の生成
    :param str_yearMonth: 年月 ("%Y-%m")
    :param val_endDay: 年月の末日
    :return: タイトル用月間日付範囲
    """

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


def drawSleepingTime(axes: matplotlib.pyplot.Axes, time_list: List[str]) -> None:
    """
    カスタム時刻描画
    :param axes: 描画領域
    :param time_list: 睡眠時刻リスト (欠損値有り: None)
    """
    for x_idx, str_time in enumerate(time_list):
        if str_time is not None:
            minute: int = toMinute(str_time)
            # Y方向を0.5上に: val+1
            axes.text(x_idx, minute + 1, str_time, **PLOT_TEXT_STYLE)


def drawScoreWithMarker(axes: matplotlib.pyplot.Axes, scoreValues: List[Any]) -> None:
    """
    睡眠スコア値出力とマーカー描画
    (1)非常に良い (2)良い (3) (1),(2)以外に該当するスコア値とマーカー
    :param axes: 描画領域
    :param scoreValues: スコアリスト (欠損データ有り)
    """
    for x_idx, score in enumerate(scoreValues):
        if score is None:
            # 欠損データはスキップ
            continue

        # マーカースタイル
        if score >= 100 * RATE_SCORE_BEST:
            scatter_style: Dict = SCATTER_SCORE_BEST_STYLE
        elif score >= 100 * RATE_SCORE_GOOD:
            scatter_style: Dict = SCATTER_SCORE_GOOD_STYLE
        elif score < 100 * RATE_SCORE_BAD:
            scatter_style: Dict = SCATTER_SCORE_BAD_STYLE
        else:
            scatter_style: Dict = SCATTER_SCORE_NORMAL_STYLE
        # マーカープロット
        axes.scatter(x_idx, score, **scatter_style)
        axes.text(x_idx, score + 1, str(score), **PLOT_TEXT_STYLE)


def drawRectBackground(axes: matplotlib.pyplot.Axes,
                       y_pos_top: float, y_pos_bottom: float,
                       x_pos_start: float, x_pos_end: float,
                       facecolor: str, alpha: float = 0.2,
                       edgecolor: str = 'none') -> None:
    """
    睡眠スコアに応じた矩形領域を指定した背景色で描画
    :param axes: 描画領域
    :param y_pos_top: Y軸上端位置
    :param y_pos_bottom:  Y軸下端位置
    :param x_pos_start: X軸左端位置
    :param x_pos_end: X軸右端位置
    :param facecolor: 背景色
    :param alpha: アルファ値
    :param edgecolor: 矩形の線色
    """
    rect: Rectangle = Rectangle(
        xy=(x_pos_start, y_pos_bottom),
        width=(x_pos_end - x_pos_start), height=(y_pos_top - y_pos_bottom),
        facecolor=facecolor, edgecolor=edgecolor, alpha=alpha
    )
    axes.add_patch(rect)


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
    # 選択クエリーの主キー: メールアドレス
    mail_address: str = args.mail_address
    year_month: str = args.year_month
    # 選択クエリーのパラメータ: 指定年月の開始日
    start_date: str = f"{year_month}-01"
    # 日付文字列チェック
    if not du.check_str_date(start_date):
        app_logger.warning("Invalid day format!")
        exit(1)

    # 指定年月の月末日
    endDay: int = calcEndOfMonth(year_month)
    # 選択クエリーのパラメータ: 指定年月の終了日
    end_date: str = f"{year_month}-{endDay:#02d}"
    # グラフタイトル (月間範囲)
    titleDateRange: str = makeTitleWithMonthRange(year_month, endDay)
    # 当該年月の期間(文字列): 当該年月の1日〜末日
    # ※健康管理の各テーブルデータは入力不能があり得るため測定日の欠損値が
    plotDateRanges: List[str] = [
        "{}-{:#02d}".format(year_month, day) for day in range(1, endDay + 1)
    ]
    app_logger.info(plotDateRanges)

    # 健康管理データベース
    # SQLAlchemyデータベース接続URL用辞書オブジェクト取得
    connDict: dict = getDBConnectionWithDict(DB_HEALTHCARE_CONF)
    # データベース接続URL生成
    connUrl: URL = URL.create(**connDict)
    # SQLAlchemyデータベースエンジン
    engineHealthcare: sqlalchemy.Engine = create_engine(connUrl, echo=False)
    # scopedセッションクラス取得
    Cls_sess_healthcare: sqlalchemy.orm.scoping.scoped_session = scoped_session(
        sessionmaker(bind=engineHealthcare)
    )
    app_logger.info(f"Cls_sess_healthcare: {Cls_sess_healthcare}")

    # 睡眠管理テーブルから月間レコードを日付と睡眠管理データの辞書オブジェクトとして取得
    recordsWithDict: Dict[str, SleepManJoined] = getRecordsWithDict(
        Cls_sess_healthcare, mail_address, start_date, end_date
    )
    # Check record count
    app_logger.info(recordsWithDict.keys())
    if len(recordsWithDict.keys()) == 0:
        app_logger.warning(f"{mail_address}, {year_month}: Record is empty!")
        exit(0)

    # 月間のプロット用項目別(X軸ラベル, 睡眠スコア, 睡眠時間, 深い睡眠)リスト生成
    xLabels, scores, sleepingTimes, deepSleepingTimes, bedTimes = makeColsForPlotting(
        plotDateRanges, recordsWithDict
    )
    # 上段に睡眠時刻と夜間トイレ回数のサブプロット領域追加
    toiletVisits: List[Optional[SleepManJoined]] = makeNocturiaColListForPlotting(
        plotDateRanges, recordsWithDict
    )
    # 睡眠時間 (分)
    sleepingMinutes: List[Optional[int]] = [toMinute(s_time) for s_time in sleepingTimes]
    # 深い睡眠 (分)
    deepSleepingMinutes: List[Optional[int]] = [
        toMinute(s_time) for s_time in deepSleepingTimes
    ]

    app_logger.info(f"xTicksLabels:\n{xLabels}")
    app_logger.info(f"sleepScores:\n{scores}")
    app_logger.info(f"sleepingTimes:\n{sleepingTimes}")
    app_logger.info(f"deepSleepingTimes:\n{deepSleepingTimes}")
    app_logger.info(f"bedTimes:\n{bedTimes}")
    app_logger.info(f"toiletVisits:\n{toiletVisits}")

    # プロット用オブジェクトリスト
    # 睡眠スコア
    np_sleepScores: np.array = np.array(
        [val if val is not None else np.nan for val in scores]
    )
    app_logger.info(f"{np_sleepScores}")
    # 深い睡眠
    np_deepSleepingMinutes: np.ndarray = np.array([
        val if val is not None else np.nan for val in deepSleepingMinutes
    ])
    app_logger.info(np_deepSleepingMinutes)
    # 睡眠時間
    np_sleepingMinutes: np.ndarray = np.array([
        val if val is not None else np.nan for val in sleepingMinutes
    ])
    app_logger.info(np_sleepingMinutes)
    # 就寝時間 (上端のX軸): None なら 空文字, 値有りなら"HH:MM"
    topXTicks: List[str] = [
        val_dt.strftime("%H:%M") if val_dt is not None else "" for val_dt in bedTimes
    ]
    app_logger.info(f"topXTicks:\n{topXTicks}")
    # トイレ回数
    np_toiletVisits: List[np.ndarray] = [
        val if val is not None else np.nan for val in toiletVisits
    ]
    app_logger.info(f"toiletVisits:\n{np_toiletVisits}")
    # 棒グラフ用の睡眠時間 = (睡眠時間 - 深い睡眠)
    np_sleepingDiffMinutes = np_sleepingMinutes - np_deepSleepingMinutes
    app_logger.info(np_sleepingDiffMinutes)

    # プロット用ラベルデータを作成する
    # X軸: データ件数(月間: 1〜末日までの日数)
    dateRangeSize: int = len(plotDateRanges)
    xIndexes = np.arange(dateRangeSize)
    # Y軸 (0〜12時間) ["00:00","00:30","01:00", ..., "11:30","12:00"]
    sleepingTimeYTicks: List = [minuteToFormatTime(x) for x in
                                range(0, SLEEP_TIME_MAX + 1, 30)]

    # グラフ出力
    # 携帯用の描画領域サイズ(ピクセル)をインチに変換
    fig_width_inch, fig_height_inch = pixelToInch(
        PHONE_PX_WIDTH, PHONE_PX_HEIGHT, PHONE_DENSITY
    )

    # 描画領域作成
    #  (1)上段描画領域: 夜間トイレ回数 (Y軸), 就寝時間 (X軸)
    #  (2)下段描画領域: 睡眠管理データ
    fig: Figure
    ax_top: Axes
    ax_main: Axes
    # https://stackoverflow.com/questions/34268742/how-to-use-gridspec-with-subplots
    #  How to use `GridSpec()` with `subplots()`
    # 上段エリア (補助プロット): 1, 下段エリア (メインプロット): 5
    # 上段エリアのX軸に就寝時間を出力するため sharex=False (デフォルト) とする
    # https://matplotlib.org/stable/tutorials/intermediate/constrainedlayout_guide.html
    #  Constrained Layout Guide
    fig, (ax_top, ax_main) = plt.subplots(
        2, 1, gridspec_kw={'height_ratios': GRID_SPEC_HEIGHT_RATIO}, layout='constrained',
        figsize=(fig_width_inch, fig_height_inch)
    )
    app_logger.info(f"fig: {fig}, ax_top: {ax_top}, ax_main: {ax_main}")
    # Y方向のグリッド線のみ表示
    ax_main.grid(**AXES_GRID_STYLE)
    ax_top.grid(**AXES_GRID_STYLE)

    # 下段メインプロット領域
    # 深い睡眠: 棒グラフ
    ax_main.bar(xIndexes, np_deepSleepingMinutes, BAR_WIDTH,
                color=COLOR_BAR_DEEP_SLEEPING,
                label=LABEL_DEEP_SLEEPING, **BAR_LINE_STYLE)
    # 睡眠時間 (深い睡眠との差分): 棒グラフ
    ax_main.bar(xIndexes, np_sleepingDiffMinutes, BAR_WIDTH,
                color=COLOR_BAR_SLEEPING,
                bottom=np_deepSleepingMinutes,
                label=LABEL_SLEEPING, **BAR_LINE_STYLE)
    # 凡例の位置設定
    ax_main.legend(loc=LEGEND_LOC)
    ax_main.set_ylabel("睡眠時間")
    # y軸ラベル: 睡眠時間 "時:分"
    ax_main.set_yticks(np.arange(SLEEP_TIME_MIN, (SLEEP_TIME_MAX + 1), SLEEP_TIME_STEP),
                       sleepingTimeYTicks,
                       **TIME_TICKS_STYLE)
    ax_main.set_ylim(SLEEP_TIME_MIN, SLEEP_TIME_MAX)
    # x軸ラベル
    ax_main.set_xticks(xIndexes, xLabels, **X_TICKS_STYLE)
    ax_main.set_xlim(X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN)
    # 月間データの場合はラベルを出力しない ※日単位当たり幅が小さいため重なってしまう
    # ax.bar_label(ax.containers[0], label_type='edge', **BAR_LABEL_STYLE)
    # draw_sleeping_time(ax, sleeping_list)

    # 睡眠スコア領域を取得: 折れ線グラフ (ラベル軸は右側)
    ax_main_score = ax_main.twinx()
    ax_main_score.set_ylabel(LABEL_SLEEP_SCORE)
    ax_main_score.plot(xIndexes, np_sleepScores, **SCORE_LINE_STYLE)
    # 右側y軸ラベル: 100まで表示させるため+1
    ax_main_score.set_yticks(np.arange(0, (SCORE_MAX + 1), SCORE_STEP),
                             np.arange(0, (SCORE_MAX + 1), SCORE_STEP),
                             **SCORE_TICKS_STYLE)
    # 右側Y軸値(0〜100)
    ax_main_score.set_ylim(0, SCORE_MAX)
    # 睡眠スコアが良い以上の場合はスコア値を表示
    drawScoreWithMarker(ax_main_score, scores)
    # 睡眠スコア範囲の矩形描画
    # 非常に良い
    drawRectBackground(ax_main, SLEEP_TIME_MAX,
                       SLEEP_TIME_MAX * RATE_SCORE_BEST,
                       X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN,
                       facecolor=COLOR_SCORE_BEST)
    # 良い
    drawRectBackground(ax_main, SLEEP_TIME_MAX * RATE_SCORE_BEST,
                       SLEEP_TIME_MAX * RATE_SCORE_GOOD,
                       X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN,
                       facecolor=COLOR_SCORE_GOOD)
    # やや低い
    drawRectBackground(ax_main, SLEEP_TIME_MAX * RATE_SCORE_GOOD,
                       SLEEP_TIME_MAX * RATE_SCORE_BAD,
                       X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN,
                       facecolor=COLOR_SCORE_WORNING, alpha=0.1)
    # 低い
    drawRectBackground(ax_main, SLEEP_TIME_MAX * RATE_SCORE_BAD,
                       SLEEP_TIME_MIN,
                       X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN,
                       facecolor=COLOR_SCORE_BAD, alpha=0.1)

    # 上端プロット領域
    # タイトル
    ax_top.set_title(titleDateRange)
    # 夜間トイレ回数 (散布図)
    ax_top.scatter(xIndexes, np_toiletVisits, **SCATTER_TOILET_VISITS_STYLE)
    ax_top.set_ylim(TOILET_VISITS_MIN, TOILET_VISITS_MAX)
    ax_top.set_ylabel(TOP_AXES_LABEL)
    ax_top.set_yticks(range(TOILET_VISITS_MIN, TOILET_VISITS_MAX + 1))
    # 睡眠時間をX軸に表示 ※X軸数はメインプロット領域と同一
    ax_top.set_xlim(X_LIM_MARGIN, dateRangeSize + X_LIM_MARGIN)
    ax_top.set_xticks(xIndexes, topXTicks, **TOP_X_TICKS_STYLE)

    # プロット結果をPNG形式でファイル保存
    save_name = gen_imgname(script_name)
    save_path = os.path.join("screen_shots", save_name)
    app_logger.info(save_path)
    fig.savefig(save_path, format="png", bbox_inches="tight")
