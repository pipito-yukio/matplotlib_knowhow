import argparse
import logging
import os
from typing import List, Optional, Tuple

import sqlite3
from sqlite3 import Error

import pandas as pd
from pandas.core.frame import DataFrame

from plotter.plotterweather import gen_plot_image

"""
気象センサーデータの前年対比グラフをHTMLに出力する 
[Database] SQLite3
https://docs.python.org/ja/3/library/sqlite3.html
sqlite3 --- SQLite データベースに対する DB-API 2.0 インターフェース
[pandas]
https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 出力画層用HTMLテンプレート
OUT_HTML = """
<!DOCTYPE html>
<html lang="ja">
<body>
<img src="{}"/>
</body>
</html>
"""

# インデックス
COL_TIME: str = "measurement_time"

# 気象データINSERT ※datetime型はデフオルトで"unixepoch"+"localtime"で登録される
"""
(登録SQL: INSERT_WEATHER)
  INSERT INTO t_weather(did, measurement_time, temp_out, temp_in, humid, pressure) 
  VALUES (?, ?, ?, ?, ?, ?)  
(レコード登録)
    conn = get_connection(weather_db, logger=logger)
    did = get_did(conn, device_name, logger=logger)
    rec = (did,
           int(measurement_time),
           to_float(temp_out),
           to_float(temp_in),
           to_float(humid),
           to_float(pressure)
           )
    try:
        with conn:
            conn.execute(INSERT_WEATHER, rec)
    except sqlite3.Error as err:
        if logger is not None:
            logger.warning("rec: {}\nerror:{}".format(rec, err))
    finally:
        if conn is not None:
           conn.close()
"""

# https://www.sqlite.org/lang_datefunc.html
#  Date And Time Functions
#  4. Examples
#   Compute the date and time given a unix timestamp 1092941466,
#     and compensate for your local timezone.
#   SELECT datetime(1092941466, 'unixepoch', 'localtime')
# ※1. SQLite3の時刻列はデフォルト "unixepoch"+"localtime"
# ※2. pyformat: name=%(deviceName)s で指定するとエラーになる
#  ': near "%": syntax error'
# https://peps.python.org/pep-0249/
#  PEP 249 – Python Database API Specification v2.0
#   paramstyle
# [OK] qmark: Question mark style, e.g. ...WHERE name=?
# [NG] pyformat: Python extended format codes, e.g. ...WHERE name=%(name)s

# 気象センサーデバイス名と期間から気象観測データを取得するSQL (SQLite3専用)
QUERY_RANGE_DATA: str = """
SELECT
   measurement_time, temp_out, humid, pressure
FROM
   t_weather
WHERE
   did=(SELECT id FROM t_device WHERE name=?)
   AND (
      datetime(measurement_time,'unixepoch','localtime') >= ?
      AND
      datetime(measurement_time,'unixepoch','localtime') < ?
   )
ORDER BY measurement_time;
"""


def next_year_month(s_year_month: str) -> str:
    """
    年月文字列の次の月を計算する
    :param s_year_month: 年月文字列
    :return: 翌年月叉は翌年月日
    :raise ValueError:
    """
    date_parts: List[str] = s_year_month.split('-')
    date_parts_size = len(date_parts)
    if date_parts_size < 2 or date_parts_size > 3:
        raise ValueError

    year, month = int(date_parts[0]), int(date_parts[1])
    month += 1
    if month > 12:
        year += 1
        month = 1
    if date_parts_size == 2:
        result = f"{year:04}-{month:02}"
    else:
        day = int(date_parts[2])
        result = f"{year:04}-{month:02}-{day:02}"
    return result


def previous_year_month(s_year_month: str) -> str:
    """
    1年前の年月を取得する
    :param s_year_month: 妥当性チェック済みの年月文字列 "YYYY-MM"
    :return: 1年前の年月
    """
    s_year, s_month = s_year_month.split('-')
    # 1年前
    prev_year: int = int(s_year) - 1
    return f"{prev_year}-{s_month}"


def save_text(file, contents):
    with open(file, 'w') as fp:
        fp.write(contents)


def get_connection(db_file_path, auto_commit=False, read_only=False, logger=None):
    try:
        if read_only:
            db_uri = "file://{}?mode=ro".format(db_file_path)
            connection = sqlite3.connect(db_uri, uri=True)
        else:
            connection = sqlite3.connect(db_file_path)
            if auto_commit:
                connection.isolation_level = None
    except Error as e:
        if logger is not None:
            logger.error(e)
        raise e
    return connection


def get_dataframe(connection,
                  device_name: str, year_month: str,
                  logger: Optional[logging.Logger] = None) -> DataFrame:
    from_date: str = year_month + "-01"
    exclude_to_date: str = next_year_month(from_date)
    # https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html
    # sql.py
    # params : list, tuple or dict, optional, default: None
    query_params: Tuple = (
        device_name, from_date + " 00:00:00", exclude_to_date + " 00:00:00",
    )
    if logger is not None:
        logger.info(f"query_params: {query_params}")
    df: pd.DataFrame = pd.read_sql(
        QUERY_RANGE_DATA, connection, params=query_params, parse_dates=[COL_TIME]
    )
    if logger is not None:
        logger.info(f"{df}")
    return df


def get_all_df(connection,
               device_name: str, curr_year_month: str,
               logger: Optional[logging.Logger] = None
               ) -> Tuple[Optional[DataFrame], Optional[DataFrame], Optional[str]]:
    # 今年の年月テータ取得
    df_curr: DataFrame = get_dataframe(connection, device_name, curr_year_month, logger=logger)
    if df_curr is not None and df_curr.shape[0] == 0:
        return None, None, curr_year_month

    # 前年の年月テータ取得
    # 前年計算
    prev_ym: str = previous_year_month(curr_year_month)
    df_prev: DataFrame = get_dataframe(connection, device_name, prev_ym, logger=logger)
    return df_curr, df_prev, prev_ym


if __name__ == '__main__':
    logging.basicConfig(format=LOG_FMT)
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(level=logging.DEBUG)

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    # SQLite3 データベースパス: ~/db/weather.db
    parser.add_argument("--sqlite3-db", type=str, required=True,
                        help="QLite3 データベースパス")
    # デバイス名: esp8266_1
    parser.add_argument("--device-name", type=str, required=True,
                        help="device name in t_device.")
    # 最新の検索年月
    parser.add_argument("--year-month", type=str, required=True,
                        help="2023-04")
    args: argparse.Namespace = parser.parse_args()
    # データベースパス
    db_path: str = os.path.expanduser(args.sqlite3_db)
    if not os.path.exists(db_path):
        app_logger.warning("Requireormat is 'YYYY-MM'")
        exit(1)

    # デバイス名
    param_device_name: str = args.device_name
    # 比較最新年月
    param_year_month = args.year_month

    conn = None
    try:
        conn = get_connection(db_path, read_only=True)
        app_logger.info(f"connection: {conn}")
        curr_df: Optional[DataFrame]
        prev_df: Optional[DataFrame]
        prev_year_month: Optional[str]
        curr_df, prev_df, prev_year_month = get_all_df(
            conn, args.device_name, param_year_month, logger=app_logger)

        if curr_df is not None and prev_df is not None:
            img_src: str = gen_plot_image(
                curr_df, prev_df, param_year_month, prev_year_month, logger=app_logger)
            # プロット結果をPNG形式でファイル保存
            script_names: List[str] = script_name.split(".")
            save_name = f"{script_names[0]}.html"
            save_path = os.path.join("output", save_name)
            app_logger.info(save_path)
            html: str = OUT_HTML.format(img_src)
            save_text(save_path, html)
        else:
            app_logger.warning("該当レコードなし")
    except Exception as err:
        app_logger.warning(err)
        exit(1)
    finally:
        if conn is not None:
            conn.close()
