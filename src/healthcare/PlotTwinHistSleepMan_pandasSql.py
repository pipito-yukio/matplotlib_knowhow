import argparse
import logging
import json
import os
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle, Patch
from matplotlib.container import BarContainer

import pandas as pd
from pandas.core.frame import DataFrame, Series
from pandas.core.groupby import DataFrameGroupBy

import sqlalchemy
from sqlalchemy.engine.url import URL
from sqlalchemy import create_engine
from sqlalchemy.sql import text

from util.file_util import gen_imgname
from util.date_util import check_str_date

"""
特定期間の睡眠スコアが下記条件に対応する並列のヒストグラムを描画する
[結合するテーブル]
  (A) 睡眠管理テーブル
  (B) 夜間頻尿要因テーブル
[フィルター条件]
  (A) 睡眠スコア >=80
  (B) 睡眠スコア <75
[プロット列]
  (1) 夜間トイレ回数 (SQLで取得)
  (2) 睡眠時刻 (計算項目): 起床時刻(SQLで取得) - 睡眠時間(SQLで取得)
  (3) 深い睡眠時間 (SQLで取得): 分に変換
  (4) 睡眠時間 (SQLで取得)
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 健康管理データベース接続情報
DB_HEALTHCARE_CONF: str = os.path.join("conf", "db_healthcare.json")

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

# ISO8601フォーマット
FMT_DATE: str = '%Y-%m-%d'
# datetime変換フォーマット
FMT_DATETIME: str = '%Y-%m-%d %H:%M'

# スマートフォンの描画領域サイズ (ピクセル): Google pixel 4a
PHONE_PX_WIDTH: int = 1064
PHONE_PX_HEIGHT: int = 1704
# 同上: 密度
PHONE_DENSITY: float = 2.75

# 集計する睡眠スコアの基準値
# df['sleep_score'] >= EGOOD_SLEEP_SCORE
GOOD_SLEEP_SCORE: int = 80
# df['sleep_score'] < WARN_SLEEP_SCORE
WARN_SLEEP_SCORE: int = 75
# SQLで取得したカラム名
COL_WAKEUP_TIME: str = 'wakeup_time'
COL_SLEEP_SCORE: str = 'sleep_score'
COL_SLEEPING_TIME: str = 'sleeping_time'
COL_DEEP_SLEEPING_TIME: str = 'deep_sleeping_time'
COL_TOILET_VISITS: str = 'midnight_toilet_visits'
# グルービング名
GROUP_BEDTIME: str = 'bed_time'
GROUP_DEEP_SLEEPING: str = 'deep_sleeping'
GROUP_SLEEPING: str = 'sleeping'
GROUP_TOILET_VISITS: str = 'toilet_visits'

# タイトルフォーマット
FMT_MEASUREMENT_RANGE: str = "睡眠管理【期間】{}〜{}"
# プロット領域比
GRID_SPEC_HEIGHT_RATIO: List[int] = [25, 25, 25, 25]
# Y軸ラベル名 ※全領域共通
Y_LABEL_HIST: str = '度数 (回)'
# 1段目: 夜間トイレ回数
X_LABEL_TOILET_VISITS: str = '夜間トイレ回数'
TOILET_VISITS_MIN: int = 0
TOILET_VISITS_MAX: int = 7
STEP_TOILET_VISITS: int = 1
# 2段目: 就寝時刻: (前日) 20:00 〜 (当日) 1:00
X_LABEL_BED_TIME: str = '就寝時刻 (前日)'
BED_TIME_MIN: int = -240  # 前日 20:00
BED_TIME_MAX: int = 60  # 当日 01:00
STEP_BED_TIME: int = 30
# 3段目: 深い睡眠: 0〜120
X_LABEL_DEEP_SLEEPING: str = '深い睡眠時間 (分)'
DEEP_SLEEPING_MIN: int = 0
DEEP_SLEEPING_MAX: int = 120
STEP_DEEP_SLEEPING: int = 10
# 4段目: 睡眠時間: 4:00 〜 10:00
Y_LABEL_SLEEPING: str = '睡眠時間 (時:分)'
SLEEPING_MIN: int = 240  # 4:00
SLEEPING_MAX: int = 600  # 10:00
STEP_SLEEPING: int = 30

# 棒グラフの幅比率
BAR_WIDTH_RATIO: float = 0.8
# 棒カラー
BAR_COLOR_GOOD: str = 'steelblue'
BAR_COLOR_WARN: str = 'orangered'
# 描画領域のグリッド線スタイル: Y方向のグリッド線のみ表示
AXES_GRID_STYLE: Dict = {'axis': 'y', 'linestyle': 'dashed', 'linewidth': 0.7,
                         'alpha': 0.75}
# X軸のラベルスタイル
X_TICKS_STYLE: Dict = {'fontsize': 8, 'fontweight': 'heavy', 'rotation': 90}
# プロット領域のラベルスタイル
LABEL_STYLE: Dict = {'fontsize': 9}
# タイトルスタイル
TITLE_STYLE: Dict = {'fontsize': 10}
# 凡例スタイル
LEGEND_STYLE: Dict = {'fontsize': 8}
# 凡例ラベル
LEGEND_GOOD: str = f'睡眠スコア >= {GOOD_SLEEP_SCORE}'
LEGEND_WARN: str = f'睡眠スコア < {WARN_SLEEP_SCORE}'
# カスタム凡例
# https://matplotlib.org/stable/tutorials/intermediate/legend_guide.html
# Legend guide
WARN_LEGEND: Patch = Patch(color=BAR_COLOR_WARN, label=LEGEND_WARN)
GOOD_LEGEND: Patch = Patch(color=BAR_COLOR_GOOD, label=LEGEND_GOOD)


def getDBConnectionWithDict(file_path: str, hostname: str = None) -> dict:
    """
    SQLAlchemyの接続URL用の辞書オブジェクトを取得する
    :param file_path: 接続設定ファイルパス (JSON形式)
    :param hostname: ホスト名 ※未設定なら実行PCのホスト名
    :return: SQLAlchemyのURL用辞書オブジェクト
    """
    with open(file_path, 'r') as fp:
        db_conf: json = json.load(fp)
        if hostname is None:
            hostname = socket.gethostname()
        # host in /etc/hostname: "hostname.local"
        db_conf["host"] = db_conf["host"].format(hostname=hostname)
    return db_conf


def toMinute(s_time: str) -> Optional[int]:
    """
    時刻文字列("時:分")を分に変換する
    :param s_time: 時刻文字列("時:分") ※欠損値有り(None)
    :return: 分(整数), NoneならNone
    """
    if s_time is None:
        return None

    times: List[str] = s_time.split(":")
    return int(times[0]) * 60 + int(times[1])


def minuteToFormatTime(val_minutes: int, trim_hour_zero=False) -> str:
    """
    分を時刻文字列("%H:%M")に変換する
    :param val_minutes: 分
    :param trim_hour_zero: 時の先頭のゼロをトリムする
    :return: 時刻文字列("%H:%M")
    """
    if not trim_hour_zero:
        return f"{val_minutes // 60:#02d}:{val_minutes % 60:#02d}"
    else:
        return f"{val_minutes // 60:#d}:{val_minutes % 60:#02d}"


def calcBedTime(s_date: str, s_wakeup_time: str, s_sleeping_time: str
                ) -> Optional[datetime]:
    """
    就寝時刻を計算する
    :param s_date: 測定日付文字列(ISO8601) ※必須
    :param s_wakeup_time: 起床時刻文字列 ("%H:%M") ※必須
    :param s_sleeping_time: 睡眠時間 ("%H:%M") ※任意 欠損値 None
    :return: (測定日付+起床時刻) - 睡眠時間 (分)
    """
    if pd.isnull(s_sleeping_time):
        return None

    val_wakeup: datetime = datetime.strptime(f"{s_date} {s_wakeup_time}",
                                             FMT_DATETIME)
    val_minutes: int = toMinute(s_sleeping_time)
    return val_wakeup - timedelta(minutes=val_minutes)


def calcBedTimeToMinute(s_curr_date: str, s_wakeup_time: str, s_sleeping_time: str
                        ) -> Optional[int]:
    """
    当日０時を基準とした就寝時刻(分)を計算する ※前日に就寝した場合は負の分
    :param s_curr_date: 測定日付文字列(ISO8601) ※必須
    :param s_wakeup_time: 起床時刻文字列 ("%H:%M") ※必須
    :param s_sleeping_time: 睡眠時間 ("%H:%M") ※任意 欠損値 None
    :return: 前日なら24時(1440分)をマイナスした経過時間(分), 当日なら0時からの経過時間(分)
    """
    if pd.isnull(s_sleeping_time):
        return None

    bed_time: Optional[datetime] = calcBedTime(s_curr_date, s_wakeup_time, s_sleeping_time)
    if bed_time is None:
        return None

    # 時刻部分のみ取り出す
    f_time: str = bed_time.strftime("%H:%M")
    bed_time_minutes: int = toMinute(f_time)
    # 測定日
    curr_time: datetime = datetime.strptime(s_curr_date, FMT_DATE)
    result: int
    if bed_time < curr_time:
        # 前日に就寝 (負の値) ※ 1440 = 24H*60
        result = bed_time_minutes - 1440
    else:
        # 当日に就寝 (正の値) 00:00 からの経過(分)
        result = bed_time_minutes
    return result


def makeBedtimeTicksLabel(ticks_range: range) -> List[str]:
    """
    就寝時刻用のX軸ラベルを生成する\n
      (A) 分が 0なら "00:00"\n
      (B) 分が正 (当日) ならそのまま変換関数に設定\n
      (B) 分が負 (前日) なら 24時間プラスした値を変換関数に設定\n
    :param ticks_range: 就寝時刻用のrangeオブジェクト
    :return: 就寝時刻用のX軸ラベル
    """
    result: List[str] = []
    for minutes in ticks_range:
        if minutes == 0:
            result.append("00:00")
        elif minutes > 0:
            # 当日: 0時以降
            result.append(minuteToFormatTime(minutes))
        else:
            # 前日: 24時プラス
            result.append(minuteToFormatTime(1440 + minutes))
    return result


def makeTitleWithDayRange(start_day: str, end_day: str) -> str:
    """
    タイトル(期間)の生成
    :param start_day: 開始日 (ISO9601形式)
    :param end_day: 終了日 (ISO9601形式)
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

    # 表示期間 (タイトル用)
    start_jpday: str = to_japanese_date(start_day)
    end_jpday: str = to_japanese_date(end_day)
    return FMT_MEASUREMENT_RANGE.format(start_jpday, end_jpday)


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


def makeGroupingObjectsForHistogram(df_orig: DataFrame) -> Dict[str, Series]:
    """
    与えられたDataFrameからヒストグラムプロット用のグルービングオブジェクトを取得する
    :param df_orig: SQLから生成されたデータフレームを指定条件でフィルタリングされたデータフレーム
    :return: グルービングオブジェクトの辞書
    """
    # 就寝時刻の計算(分) ※起床時刻の形式("%H:%M")
    day_idx: pd.DatetimeIndex = df_orig.index
    day_array: np.ndarray = day_idx.to_pydatetime()
    bed_times: List[Optional[int]] = [
        calcBedTimeToMinute(
            day.strftime(FMT_DATE), wakeup, sleeping) for day, wakeup, sleeping in zip(
            day_array, df_orig[COL_WAKEUP_TIME], df_orig[COL_SLEEPING_TIME]
        )
    ]
    df_orig[GROUP_BEDTIME] = bed_times
    # 睡眠時間("%H:%M"): 分(整数)に変換
    df_orig[COL_SLEEPING_TIME] = df_orig[COL_SLEEPING_TIME].apply(toMinute)
    # 深い睡眠("%H:%M"): 分(整数)に変換
    df_orig[COL_DEEP_SLEEPING_TIME] = df_orig[COL_DEEP_SLEEPING_TIME].apply(toMinute)
    # グループオブジェクト
    # 就寝時刻
    ranges = range(BED_TIME_MIN, BED_TIME_MAX + 1, STEP_BED_TIME)
    grouped_bedtime: DataFrameGroupBy = df_orig.groupby(
        pd.cut(df_orig[GROUP_BEDTIME], ranges, right=False))
    # 深い睡眠
    ranges = range(DEEP_SLEEPING_MIN, DEEP_SLEEPING_MAX + 1, STEP_DEEP_SLEEPING)
    grouped_deep_sleeping: DataFrameGroupBy = df_orig.groupby(
        pd.cut(df_orig[COL_DEEP_SLEEPING_TIME], ranges, right=False))
    # 睡眠時間
    ranges = range(SLEEPING_MIN, SLEEPING_MAX + 1, STEP_SLEEPING)
    grouped_sleeping: DataFrameGroupBy = df_orig.groupby(
        pd.cut(df_orig[COL_SLEEPING_TIME], ranges, right=False))
    # 夜間トイレ回数
    ranges = range(TOILET_VISITS_MIN, TOILET_VISITS_MAX + 1, STEP_TOILET_VISITS)
    grouped_visits: DataFrameGroupBy = df_orig.groupby(
        pd.cut(df_orig[COL_TOILET_VISITS], ranges, right=False))

    # グルービングしたそれぞれの度数の辞書オブジェクト
    result: Dict[str, Series] = {
        GROUP_BEDTIME: grouped_bedtime[COL_SLEEP_SCORE].count(),
        GROUP_DEEP_SLEEPING: grouped_deep_sleeping[COL_SLEEP_SCORE].count(),
        GROUP_SLEEPING: grouped_sleeping[COL_SLEEP_SCORE].count(),
        GROUP_TOILET_VISITS: grouped_visits[COL_SLEEP_SCORE].count()
    }
    return result


def _makeBar(x_start: float, y_bottom: float, width: float, height: float,
             facecolor: str = 'blue', alpha: float = 1.,
             edgecolor: Optional[str] = None) -> Rectangle:
    """
    棒グラフの矩形を生成する
    :param x_start:  X軸左端位置
    :param y_bottom: Y軸下端位置
    :param width: 棒幅
    :param facecolor: 背景色
    :param alpha: アルファ値
    :param edgecolor: 矩形の線色
    :return: 矩形オブジェクト
    """
    rect: Rectangle = Rectangle(
        xy=(x_start, y_bottom), width=width, height=height,
        facecolor=facecolor, edgecolor=edgecolor, alpha=alpha
    )
    return rect


def plotBedtimeTwinBar(ax: Axes, grp_left: Series, grp_right: Series) -> None:
    """
    就寝時刻の度数をプロット (高さに対応する長方形を描画)
    :param ax: プロット領域
    :param grp_left: 左側描画用グルービングオブジェクト
    :param grp_right: 右側描画用グルービングオブジェクト
    """
    # 度数に対応する矩形を領域に追加する
    hist_max: np.int64 = np.max([grp_left.values.max(), grp_right.values.max()])
    # X軸初期位置: X軸開始位置 (2つの棒の中心) - Xステップ
    half_step: float = 1.0 * STEP_BED_TIME / 2.
    half_width: float = (BAR_WIDTH_RATIO * STEP_BED_TIME) / 2.
    x_center: float = BED_TIME_MIN - half_step
    x_start: float
    for left_hist, right_hist in zip(grp_left.values, grp_right.values):
        x_center += STEP_BED_TIME
        # 左側の棒: 中心から左側に半幅が開始点
        if left_hist > 0:
            x_start = x_center - half_width
            bar: Rectangle = _makeBar(x_start, 0, half_width, left_hist, facecolor=BAR_COLOR_WARN)
            ax.add_patch(bar)
        # 右側の棒: 中心が開始点
        if right_hist > 0:
            x_start = x_center
            bar: Rectangle = _makeBar(x_start, 0, half_width, right_hist, facecolor=BAR_COLOR_GOOD)
            ax.add_patch(bar)
    # Y軸設定
    ax.set_ylim(0, hist_max + 1)
    ax.set_ylabel(Y_LABEL_HIST, **LABEL_STYLE)
    # X軸範囲
    ax.set_xlim(BED_TIME_MIN, BED_TIME_MAX)
    # X軸ラベルは時刻文字列
    x_range: range = range(BED_TIME_MIN, BED_TIME_MAX + 1, STEP_BED_TIME)
    time_ticks: List[str] = makeBedtimeTicksLabel(x_range)
    ax.set_xticks(x_range, labels=time_ticks, **X_TICKS_STYLE)
    ax.set_xlabel(X_LABEL_BED_TIME, **LABEL_STYLE)


def plotDeepSleepingTwinBar(ax: Axes, grp_left: Series, grp_right: Series) -> None:
    """
    深い睡眠の度数をプロット (高さに対応する長方形を描画)
    :param ax: 深い睡眠度数プロット領域
    :param grp_left: 左側描画用グルービングオブジェクト
    :param grp_right: 右側描画用グルービングオブジェクト
    """
    hist_max: np.int64 = np.max([grp_left.values.max(), grp_right.values.max()])
    half_step: float = 1.0 * STEP_DEEP_SLEEPING / 2.
    half_width: float = (BAR_WIDTH_RATIO * STEP_DEEP_SLEEPING) / 2.
    x_center: float = DEEP_SLEEPING_MIN - half_step
    x_start: float
    for left_hist, right_hist in zip(grp_left.values, grp_right.values):
        x_center += STEP_DEEP_SLEEPING
        # 左側の棒: 中心から左側に半幅が開始点
        if left_hist > 0:
            x_start = x_center - half_width
            bar: Rectangle = _makeBar(x_start, 0, half_width, left_hist, facecolor=BAR_COLOR_WARN)
            ax.add_patch(bar)
        # 右側の棒: 中心が開始点
        if right_hist > 0:
            x_start = x_center
            bar: Rectangle = _makeBar(x_start, 0, half_width, right_hist, facecolor=BAR_COLOR_GOOD)
            ax.add_patch(bar)
    # Y軸設定
    ax.set_ylim(0, hist_max + 1)
    ax.set_ylabel(Y_LABEL_HIST, **LABEL_STYLE)
    # X軸範囲
    ax.set_xlim(DEEP_SLEEPING_MIN, DEEP_SLEEPING_MAX)
    # X軸の単位は分
    x_indexes: range = range(DEEP_SLEEPING_MIN, DEEP_SLEEPING_MAX + 1, STEP_DEEP_SLEEPING)
    ax.set_xticks(x_indexes, labels=map(str, x_indexes), **X_TICKS_STYLE)
    ax.set_xlabel(X_LABEL_DEEP_SLEEPING, **LABEL_STYLE)


def plotSleepingTwinBar(ax: Axes, grp_left: Series, grp_right: Series) -> None:
    """
    睡眠時間の度数をプロット (高さに対応する長方形を描画)
    :param ax: プロット領域
    :param grp_left: 左側描画用グルービングオブジェクト
    :param grp_right: 右側描画用グルービングオブジェクト
    """
    hist_max: np.int64 = np.max([grp_left.values.max(), grp_right.values.max()])
    half_step: float = 1.0 * STEP_SLEEPING / 2.
    half_width: float = (BAR_WIDTH_RATIO * STEP_SLEEPING) / 2.
    x_center: float = SLEEPING_MIN - half_step
    x_start: float
    for left_hist, right_hist in zip(grp_left.values, grp_right.values):
        x_center += STEP_SLEEPING
        # 左側の棒: 中心から左側に半幅が開始点
        if left_hist > 0:
            x_start = x_center - half_width
            bar: Rectangle = _makeBar(x_start, 0, half_width, left_hist, facecolor=BAR_COLOR_WARN)
            ax.add_patch(bar)
        # 右側の棒: 中心が開始点
        if right_hist > 0:
            x_start = x_center
            bar: Rectangle = _makeBar(x_start, 0, half_width, right_hist, facecolor=BAR_COLOR_GOOD)
            ax.add_patch(bar)
    # Y軸設定
    ax.set_ylim(0, hist_max + 1)
    ax.set_ylabel(Y_LABEL_HIST, **LABEL_STYLE)
    # X軸範囲
    ax.set_xlim(SLEEPING_MIN, SLEEPING_MAX)
    # X軸ラベルは時刻文字列
    x_indexes: iter = range(SLEEPING_MIN, SLEEPING_MAX + 1, STEP_SLEEPING)
    x_labels: List[str] = [minuteToFormatTime(minutes, trim_hour_zero=True) for minutes in x_indexes]
    ax.set_xticks(x_indexes, labels=x_labels, **X_TICKS_STYLE)
    ax.set_xlabel(Y_LABEL_SLEEPING, **LABEL_STYLE)


def plotToiletVisitsTwinHist(ax: Axes, grp_left: Series, grp_right: Series) -> None:
    """
    夜間トイレ回数の度数をプロット (バーを描画)
    :param ax: プロット領域
    :param grp_left: 左側描画用グルービングオブジェクト
    :param grp_right: 右側描画用グルービングオブジェクト
    """
    hist_max: np.int64 = np.max([grp_left.values.max(), grp_right.values.max()])
    # X軸の位置: (幅) 1.0
    x = np.arange(0, TOILET_VISITS_MAX)
    # 棒幅(半分): (幅[1.] * 幅比率) / 2
    half_width: float = BAR_WIDTH_RATIO / 2.
    # 中心から右左のオフセット: 棒幅(半分) / 2
    x_offset: float = half_width / 2.
    # 左側の棒グラフ: 中心から左側にオフセット幅をマイナス
    pa1: BarContainer = ax.bar(x - (1. * x_offset), grp_left.values, half_width,
                               label=LEGEND_WARN, color=BAR_COLOR_WARN)
    for child in pa1.get_children():
        app_logger.debug(f"pa1.child: {child}")
    # 右側の棒グラフ: 中心から右側にオフセット幅をプラス
    pa2: BarContainer = ax.bar(x + (1. * x_offset), grp_right.values, half_width,
                               label=LEGEND_GOOD, color=BAR_COLOR_GOOD)
    for child in pa2.get_children():
        app_logger.debug(f"pa2.child: {child}")
    ax.legend(**LEGEND_STYLE)
    ax.set_ylim(0, hist_max + 1)
    ax.set_ylabel(Y_LABEL_HIST, **LABEL_STYLE)
    ax.set_xlabel(X_LABEL_TOILET_VISITS, **LABEL_STYLE)


if __name__ == '__main__':
    logging.basicConfig(format=LOG_FMT)
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(level=logging.DEBUG)

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    # メールアドレス (例) user1@examples.com
    parser.add_argument("--mail-address", type=str, required=True,
                        help="Healthcare Database Person mailAddress.")
    # 検索開始日
    parser.add_argument("--start-date", type=str, required=True,
                        help="2023-04-01")
    # 検索終了日
    parser.add_argument("--end-date", type=str, required=True,
                        help="2023-04-30")
    # ホスト名 ※任意 (例) raspi-4
    parser.add_argument("--db-host", type=str, help="Other database hostname.")
    args: argparse.Namespace = parser.parse_args()
    # 選択クエリーの主キー: メールアドレス
    mail_address: str = args.mail_address
    # 検索範囲
    start_date = args.start_date
    end_date = args.end_date
    # ホスト名
    db_host = args.db_host
    # 日付文字列チェック
    for i_date in [start_date, end_date]:
        if not check_str_date(i_date):
            app_logger.warning(f"Invalid date format ('YYYY-mm-dd'): {i_date}")
            exit(1)

    connDict: dict = getDBConnectionWithDict(DB_HEALTHCARE_CONF, hostname=db_host)
    # データベース接続URL生成
    connUrl: URL = URL.create(**connDict)
    # SQLAlchemyデータベースエンジン
    engineHealthcare: sqlalchemy.Engine = create_engine(connUrl, echo=False)

    query_params: Dict = {"emailAddress": mail_address, "startDay": start_date, "endDay": end_date}
    pd.set_option('display.max_rows', None)
    try:
        with engineHealthcare.connect() as conn:
            df_all = pd.read_sql(
                text(QUERY_SLEEP_MAN), conn, params=query_params,
                parse_dates=['measurement_day']
            )
    except Exception as err:
        app_logger.warning(err)
        exit(1)

    app_logger.info(f"shape: {df_all.shape}")
    app_logger.info(f"columns: {df_all.columns}")
    # 測定日をインデックスに設定
    df_all: DataFrame = df_all.set_index('measurement_day')
    app_logger.debug(f"df_all: {df_all}")
    # (1) 睡眠スコアが良いデータ
    df_score_good: DataFrame = df_all.loc[df_all[COL_SLEEP_SCORE] >= GOOD_SLEEP_SCORE].copy()
    app_logger.info(f"df_score_good.size: {df_score_good.shape[0]}")
    app_logger.debug(f"df_score_good: {df_score_good}")
    # ヒストグラム用グルービングオブジェクト取得
    dict_good: Dict[str, Series] = makeGroupingObjectsForHistogram(df_score_good)
    good_bedtime: Series = dict_good[GROUP_BEDTIME]
    good_deep_sleeping: Series = dict_good[GROUP_DEEP_SLEEPING]
    good_sleeping: Series = dict_good[GROUP_SLEEPING]
    good_toilet_visits: Series = dict_good[GROUP_TOILET_VISITS]
    app_logger.info(f"good_bedtime: {good_bedtime}")
    app_logger.info(f"good_deep_sleeping: {good_deep_sleeping}")
    app_logger.info(f"good_sleeping: {good_sleeping}")
    app_logger.info(f"good_toilet_visits: {good_toilet_visits}")
    # (2) 睡眠スコアが悪いデータ
    df_score_warn: DataFrame = df_all.loc[df_all[COL_SLEEP_SCORE] < WARN_SLEEP_SCORE].copy()
    app_logger.info(f"df_score_warn.size: {df_score_warn.shape[0]}")
    app_logger.debug(f"df_score_warn: {df_score_warn}")
    dict_warn: Dict[str, Series] = makeGroupingObjectsForHistogram(df_score_warn)
    warn_bedtime: Series = dict_warn[GROUP_BEDTIME]
    warn_deep_sleeping: Series = dict_warn[GROUP_DEEP_SLEEPING]
    warn_sleeping: Series = dict_warn[GROUP_SLEEPING]
    warn_toilet_visits: Series = dict_warn[GROUP_TOILET_VISITS]
    app_logger.info(f"warn_bedtime: {warn_bedtime}")
    app_logger.info(f"warn_deep_sleeping: {warn_deep_sleeping}")
    app_logger.info(f"warn_sleeping: {warn_sleeping}")
    app_logger.info(f"warn_toilet_visits: {warn_toilet_visits}")

    # グラフ出力
    # 携帯用の描画領域サイズ(ピクセル)をインチに変換
    fig_width_inch, fig_height_inch = pixelToInch(
        PHONE_PX_WIDTH, PHONE_PX_HEIGHT, PHONE_DENSITY
    )
    fig: Figure
    # 1段目: 夜間トイレ回数の度数プロット領域
    ax_toilet_visits: Axes
    # 2段目: 就寝時刻の度数プロット領域
    ax_bedtime: Axes
    # 3段目: 深い睡眠の度数プロット領域
    ax_deep_sleeping: Axes
    # 4段目: 睡眠時間の度数プロット領域
    ax_sleeping: Axes
    fig, (ax_toilet_visits, ax_bedtime, ax_deep_sleeping, ax_sleeping) = plt.subplots(
        4, 1, gridspec_kw={'height_ratios': GRID_SPEC_HEIGHT_RATIO}, layout='constrained',
        figsize=(fig_width_inch, fig_height_inch)
    )
    # UserWarning: This figure was using a layout engine that is incompatible
    #  with subplots_adjust and/or tight_layout; not calling subplots_adjust.
    # plt.subplots_adjust(hspace=2.0)
    # Y方向のグリッド線のみ表示
    for axes in [ax_toilet_visits, ax_bedtime, ax_deep_sleeping, ax_sleeping]:
        axes.grid(**AXES_GRID_STYLE)

    # (1) 夜間起床回数
    # グラフタイトル (期間)
    titleDateRange: str = makeTitleWithDayRange(start_date, end_date)
    ax_toilet_visits.set_title(titleDateRange, **TITLE_STYLE)
    # Axes.barでツイン棒グラフ描画
    plotToiletVisitsTwinHist(ax_toilet_visits, warn_toilet_visits, good_toilet_visits)
    # カスタム(矩形)のツイン棒グラフ描画
    # (2) 就寝時刻プロット
    plotBedtimeTwinBar(ax_bedtime, warn_bedtime, good_bedtime)
    # (3) 深い睡眠時間プロット
    plotDeepSleepingTwinBar(ax_deep_sleeping, warn_deep_sleeping, good_deep_sleeping)
    # (4) 睡眠時間プロット
    plotSleepingTwinBar(ax_sleeping, warn_sleeping, good_sleeping)
    # 同じ凡例をまとめて設定 (2)-(4)
    # https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.legend.html
    for axes in [ax_bedtime, ax_deep_sleeping, ax_sleeping]:
        axes.legend(handles=[WARN_LEGEND, GOOD_LEGEND], **LEGEND_STYLE)

    # プロット結果をPNG形式でファイル保存
    save_name = gen_imgname(script_name)
    save_path = os.path.join("screen_shots", save_name)
    app_logger.info(save_path)
    fig.savefig(save_path, format="png", bbox_inches="tight")
