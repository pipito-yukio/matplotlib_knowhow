import argparse
import logging
import json
import os
import socket
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rcParams
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

import pandas
import pandas as pd
from pandas.core.frame import DataFrame, Series

from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy import create_engine
from sqlalchemy.sql import text
from sqlalchemy.orm import scoped_session, sessionmaker
import sqlalchemy.orm.scoping as scoping

import util.date_util as du
from util.file_util import gen_imgname

"""
気象センサーの外気温の前年対比グラフをプロットする
[DB] sensors_pgdb
[テーブル] weather.t_weather
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 気象センサーデータベース接続情報
DB_CONF: str = os.path.join("conf", "db_sensors.json")

# 指定した気象デバイス名と期間から外気温測定データを取得
QUERY_RANGE_DATA = """
SELECT
  measurement_time
  ,temp_out
  ,humid
  ,pressure
FROM
  weather.t_device dev
  INNER JOIN weather.t_weather wt ON dev.id = wt.did
WHERE
  dev.name=:deviceName
  AND
  measurement_time BETWEEN :startTime AND :endTime
  ORDER BY measurement_time
"""

# ISO8601フォーマット
FMT_DATE: str = '%Y-%m-%d'
# datetime変換フォーマット ※ SQLで "%H:%M"にフォーマット済み
FMT_DATETIME: str = '%Y-%m-%d %H:%M'
# 取得カラム
COL_TIME: str = 'measurement_time'
COL_TEMP: str = 'temp_out'
COL_HUMID: str = 'humid'
COL_PRESSUE: str = 'pressure'
COL_PREV_PLOT_TIME: str = 'prev_plot_measurement_time'
# SQLパラメータ名
PARAM_DEVICE_NAME: str = 'deviceName'
PARAM_STA_TIME: str = 'startTime'
PARAM_END_TIME: str = 'endTime'
# 気圧
Y_PRESSURE_MIN: float = 960.
Y_PRESSURE_MAX: float = 1060.
# ラベル
Y_LABEL_TEMPER: str = '外気温 (℃)'
Y_LABEL_HUMID: str = '湿　度 (％)'
Y_LABEL_PRESSURE: str = '気　圧 (hPa)'
# タイトルフォーマット
FMT_MEASUREMENT_RANGE: str = "{} − {} データ比較"
# 平均値文字列
FMT_JP_YEAR_MONTH: str = "{year}年{month}月"
FMT_AVEG_TEXT: str = "{jp_year_month} 平均{type} {value:#.1f} {unit}"
DICT_AVE_TEMP: Dict = {'type': '気温', 'unit': '℃'}
DICT_AVEG_HUMID: Dict = {'type': '湿度', 'unit': '％'}
DICT_AVEG_PRESSURE: Dict = {'type': '気圧', 'unit': 'hPa'}
# 描画領域のグリッド線スタイル: Y方向のグリッド線のみ表示
AXES_GRID_STYLE: Dict = {'axis': 'y', 'linestyle': 'dashed', 'linewidth': 0.7,
                         'alpha': 0.75}
# カラー
CURR_COLOR: str = 'C0' #'tab:blue'
PREV_COLOR: str = 'C1' #'tab:orange'
# 平均線スタイル
AVEG_LINE_STYLE: Dict = {'linestyle': 'dashdot', 'linewidth': 1.}
CURR_AVEG_LINE_STYLE: Dict = {'color': CURR_COLOR, **AVEG_LINE_STYLE}
PREV_AVEG_LINE_STYLE: Dict = {'color': PREV_COLOR, **AVEG_LINE_STYLE}
# X軸のラベルスタイル
X_TICKS_STYLE: Dict = {'fontsize': 8, 'fontweight': 'heavy', 'rotation': 90}
# プロット領域のラベルスタイル
LABEL_STYLE: Dict = {'fontsize': 10, }
# 凡例スタイル
LEGEND_STYLE: Dict = {'fontsize': 10, }
# タイトルスタイル
TITLEL_STYLE: Dict = {'fontsize': 11, }


def getDBConnectionWithDict(filePath: str, hostname: str = None) -> dict:
    """
    SQLAlchemyの接続URL用の辞書オブジェクトを取得する
    :param filePath: 接続設定ファイルパス (JSON形式)
    :param hostname: ホスト名 ※未設定なら実行PCのホスト名
    :return: SQLAlchemyのURL用辞書オブジェクトDB_HEALTHCARE_CONF
    """
    with open(filePath, 'r') as fp:
        db_conf: json = json.load(fp)
        if hostname is None:
            hostname = socket.gethostname()
        # host in /etc/hostname: "hostname.local"
        db_conf["host"] = db_conf["host"].format(hostname=hostname)
    return db_conf


def getMeasurementTimeRangeData(cls_sess: scoping.scoped_session, qry_params: Dict) -> DataFrame:
    """
    指定されたクエリーパラメータの検索クエリーからデータフレームを生成する
    :param cls_sess: 接続設定ファイルパス (JSON形式)
    :param qry_params: ホスト名 ※未設定なら実行PCのホスト名
    :return: DataFrame
    """
    # Sessionオブジェクトは sqlalchemy.orm.scoped_session
    # バッチアプリでは同一スレッドで実行されるのでオブジェクトは前回と同一になる
    sess_obj: scoped_session = cls_sess()
    app_logger.info(f"scoped_session: {sess_obj}")
    try:
        with sess_obj.connection() as conn:
            read_df = pandas.read_sql(
                text(QUERY_RANGE_DATA), conn, params=qry_params,
                parse_dates=[COL_TIME]
            )
        return read_df
    except Exception as err:
        raise err
    finally:
        # Webアプリケーションではクリーンアップでクラスのremove()呼び出しが必須
        # バッチアプリでは不要
        cls_sess.remove()


def calcEndOfMonth(s_year_month: str) -> int:
    """
    年月(文字列)の末日を計算する
    :param s_year_month: 妥当性チェック済みの年月文字列 "YYYY-MM"
    :return: 末日
    """
    year_months = s_year_month.split("-")
    val_year, val_month = int(year_months[0]), int(year_months[1])
    if val_month == 12:
        val_year += 1
        val_month = 1
    else:
        val_month += 1
    # 月末日の翌月の1日
    val_next_year_month = date(val_year, val_month, 1)
    # 月末日の計算: 次の月-1日
    val_lat_day_of_month = val_next_year_month - timedelta(days=1)
    return val_lat_day_of_month.day


def toPreviousYearMonth(s_year_month: str) -> str:
    """
    1年前の年月を取得する
    :param s_year_month: 妥当性チェック済みの年月文字列 "YYYY-MM"
    :return: 1年前の年月
    """
    s_year, s_month = s_year_month.split('-')
    # 1年前
    prev_year: int = int(s_year) - 1
    return f"{prev_year}-{s_month}"


def measurementTimeRangeToDict(s_year_month: str, sql_param_dict: Dict) -> Dict:
    """
    検索用の開始時刻と最終時刻を取得する
    :param s_year_month: 妥当性チェック済みの年月文字列 "YYYY-MM"
    :param sql_param_dict: SQLパラメータ辞書オブジェクト
    :return: 時刻範囲のタプル (開始時刻, 最終時刻)
    """
    # 選択クエリーのパラメータ: 指定年月の開始時刻
    s_start_time: str = f"{s_year_month}-01 00:00:00"
    sql_param_dict[PARAM_STA_TIME] = s_start_time
    # 指定年月の月末日
    end_day: int = calcEndOfMonth(year_month)
    # 選択クエリーのパラメータ: 指定年月の最終時刻
    s_end_time: str = f"{s_year_month}-{end_day:#02d} 23:59:59"
    sql_param_dict[PARAM_END_TIME] = s_end_time
    return sql_param_dict


def plusOneYear(prev_datetime: datetime) -> datetime:
    """

    @param prev_datetime:
    @return:
    """
    next_val: datetime = datetime(prev_datetime.year + 1,
                                  prev_datetime.month,
                                  prev_datetime.day,
                                  prev_datetime.hour,
                                  prev_datetime.minute,
                                  prev_datetime.second
                                  )
    return next_val


def makeLegendLabel(s_year_month: str) -> str:
    """
    凡例用ラベル生成
    @param s_year_month: 年月文字列
    @return: 凡例用ラベル
    """
    parts: List[str] = s_year_month.split('-')
    return FMT_JP_YEAR_MONTH.format(year=parts[0], month=parts[1])


def makeAvePatch(plot_label, f_ave: float, s_color: str, dict_ave: Dict) -> Patch:
    """

    @param plot_label:
    @param f_ave:
    @param s_color
    @param dict_ave:
    @return:
    """
    def makeAvegText(jp_year_month: str, value: float, data_dict: Dict) -> str:
        """
        平均値用の文字列生成
        :param jp_year_month: 日本語年月文字列
        :@param value: 平均値
        :param data_dict: データ型ごとの置換用辞書オブジェクト
        :return: 平均値用の文字列
        """
        data_dict['jp_year_month'] = jp_year_month
        data_dict['value'] = value
        return FMT_AVEG_TEXT.format(**data_dict)

    s_ave = makeAvegText(plot_label, f_ave, dict_ave)
    return Patch(color=s_color, label=s_ave)


def setYLimWithAxes(plot_axes: Axes, curr_ser: Series, prev_ser: Series) -> None:
    """
    各データの最大値・最小値を設定する
    @param plot_axes: プロット領域
    @param curr_ser: 最新データ
    @param prev_ser: 前年データ
    """
    val_min: float = np.min([curr_ser.min(), prev_ser.min()])
    val_max: float = np.max([curr_temp_ser.max(), prev_temp_ser.max()])
    val_min = np.floor(val_min / 10.) * 10.
    val_max = np.ceil(val_max / 10.) * 10.
    plot_axes.set_ylim(val_min, val_max)


if __name__ == '__main__':
    logging.basicConfig(format=LOG_FMT)
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(level=logging.DEBUG)

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    # デバイス名: esp8266_1
    parser.add_argument("--device-name", type=str, required=True,
                        help="device name in t_device.")
    # 最新の検索年月
    parser.add_argument("--year-month", type=str, required=True,
                        help="2023-04")
    # ホスト名 ※任意 (例) raspi-4
    parser.add_argument("--db-host", type=str, help="Other database hostname.")
    args: argparse.Namespace = parser.parse_args()
    # 複合主キー: デバイス名
    device_name: str = args.device_name
    # 比較最新年月
    year_month = args.year_month
    db_host = args.db_host
    # 年月文字列チェック: ISO-8601
    chk_date: str = f"{year_month}-01"
    if not du.check_str_date(chk_date):
        app_logger.warning("Invalid year-month format is 'YYYY-MM'")
        exit(1)

    connDict: dict = getDBConnectionWithDict(DB_CONF, hostname=db_host)
    # データベース接続URL生成
    connUrl: URL = URL.create(**connDict)
    # SQLAlchemyデータベースエンジン
    db_engine: Engine = create_engine(connUrl, echo=False)
    sess_factory = sessionmaker(bind=db_engine)
    app_logger.info(f"session_factory: {sess_factory}")
    # Sessionクラスは sqlalchemy.orm.scoping.scoped_session
    Cls_sess = scoped_session(sess_factory)
    app_logger.info(f"Session class: {Cls_sess}")

    # クエリーパラメータにデバイス名をセット
    query_params: Dict = {PARAM_DEVICE_NAME: device_name}
    # 最新年月の範囲
    query_params = measurementTimeRangeToDict(year_month, query_params)
    app_logger.info(f"curr.query_params: {query_params}")
    prev_year_month: str
    try:
        df_curr: DataFrame = getMeasurementTimeRangeData(Cls_sess, query_params)
        # 年前年月の範囲
        prev_year_month = toPreviousYearMonth(year_month)
        query_params = measurementTimeRangeToDict(prev_year_month, query_params)
        app_logger.info(f"prev.query_params: {query_params}")
        df_prev: DataFrame = getMeasurementTimeRangeData(Cls_sess, query_params)
    except Exception as err:
        app_logger.warning(err)
        exit(1)

    app_logger.info(df_curr.head())
    app_logger.info(df_prev.head())
    # (1) 外気温
    curr_temp_ser: Series = df_curr[COL_TEMP]
    prev_temp_ser: Series = df_prev[COL_TEMP]
    # (2) 湿度
    curr_humid_ser: Series = df_curr[COL_HUMID]
    prev_humid_ser: Series = df_prev[COL_HUMID]
    # (3) 気圧
    curr_pressure_ser: Series = df_curr[COL_PRESSUE]
    prev_pressure_ser: Series = df_prev[COL_PRESSUE]
    # 前年データをX軸にプロットするために測定時刻列にを1年プラスする
    df_prev[COL_PREV_PLOT_TIME] = df_prev[COL_TIME].apply(plusOneYear)

    # 凡例用ラベル
    # 最新年月
    curr_plot_label = makeLegendLabel(year_month)
    # 前年月
    prev_plot_label = makeLegendLabel(prev_year_month)
    # タイトル
    main_title: str = FMT_MEASUREMENT_RANGE.format(curr_plot_label, prev_plot_label)

    fig: Figure
    ax_temp: Axes
    ax_humid: Axes
    ax_pressure: Axes
    fig = Figure(figsize=[12, 10])
    # x軸を共有する3行1列のサブプロット生成
    (ax_temp, ax_humid, ax_pressure) = fig.subplots(3, 1, sharex=True)
    # サブプロット間の間隔を変更する
    fig.subplots_adjust(wspace=0.1, hspace=0.1)
    # Y方向のグリッド線のみ表示
    for ax in [ax_temp, ax_humid, ax_pressure]:
        ax_temp.grid(**AXES_GRID_STYLE)

    # 平均値
    val_ave: float
    # 平均値用のラベル文字列
    ave_text: str
    curr_patch: Patch
    prev_patch: Patch
    # (1) 外気温領域のプロット
    # 最低・最高
    setYLimWithAxes(ax_temp, curr_temp_ser, prev_temp_ser)
    # 最新年月の外気温
    ax_temp.plot(df_curr[COL_TIME], curr_temp_ser, color=CURR_COLOR, marker="")
    val_ave = curr_temp_ser.mean()
    curr_patch = makeAvePatch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVE_TEMP)
    ax_temp.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月の外気温
    ax_temp.plot(df_prev[COL_PREV_PLOT_TIME], prev_temp_ser, color=PREV_COLOR, marker="")
    val_ave = prev_temp_ser.mean()
    prev_patch = makeAvePatch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVE_TEMP)
    ax_temp.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_temp.set_ylabel(Y_LABEL_TEMPER, **LABEL_STYLE)
    # 凡例
    ax_temp.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)
    ax_temp.set_title(main_title, **TITLEL_STYLE)

    # (2) 湿度領域のプロット
    ax_humid.set_ylim([0., 100.])
    # 最新年月
    ax_humid.plot(df_curr[COL_TIME], curr_humid_ser, color=CURR_COLOR, marker="")
    val_ave = curr_humid_ser.mean()
    curr_patch = makeAvePatch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVEG_HUMID)
    ax_humid.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月
    ax_humid.plot(df_prev[COL_PREV_PLOT_TIME], prev_humid_ser, color=PREV_COLOR, marker="")
    val_ave = prev_humid_ser.mean()
    prev_patch = makeAvePatch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVEG_HUMID)
    ax_humid.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_humid.set_ylabel(Y_LABEL_HUMID, **LABEL_STYLE)
    # 凡例
    ax_humid.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)

    # (3) 気圧領域のプロット
    ax_pressure.set_ylim(Y_PRESSURE_MIN, Y_PRESSURE_MAX)
    # 最新年月
    ax_pressure.plot(df_curr[COL_TIME], curr_pressure_ser, color=CURR_COLOR, marker="")
    val_ave = curr_pressure_ser.mean()
    curr_patch = makeAvePatch(curr_plot_label, val_ave, CURR_COLOR, DICT_AVEG_PRESSURE)
    ax_pressure.axhline(val_ave, **CURR_AVEG_LINE_STYLE)
    # 前年月
    ax_pressure.plot(df_prev[COL_PREV_PLOT_TIME], prev_pressure_ser, color=PREV_COLOR, marker="")
    val_ave = prev_pressure_ser.mean()
    prev_patch = makeAvePatch(prev_plot_label, val_ave, PREV_COLOR, DICT_AVEG_PRESSURE)
    ax_pressure.axhline(val_ave, **PREV_AVEG_LINE_STYLE)
    ax_pressure.set_ylabel(Y_LABEL_PRESSURE, **LABEL_STYLE)
    # 凡例
    ax_pressure.legend(handles=[curr_patch, prev_patch], **LEGEND_STYLE)
    # X軸ラベル
    ax_pressure.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    # プロット結果をPNG形式でファイル保存
    save_name = gen_imgname(script_name)
    save_path = os.path.join("screen_shots", save_name)
    app_logger.info(save_path)
    fig.savefig(save_path, format="png", bbox_inches="tight")
