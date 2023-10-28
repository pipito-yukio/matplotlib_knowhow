import argparse
import json
import logging
import os
import socket
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pandas.core.frame import DataFrame
import psycopg2
from psycopg2.extensions import connection

from plotter.plotterweather import gen_plot_image

"""
気象センサーデータの前年対比グラフをHTMLに出力する
[Database] PostgreSQL
[Python DB API 2.0] psycopg2 (pip install psycopg2-binary) 
https://www.psycopg.org/docs/
Psycopg – PostgreSQL database adapter for Python
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 気象センサーデータベース接続情報
DB_CONF: str = os.path.join("conf", "db_sensors_psycopg.json")

# 出力画層用HTMLテンプレート
OUT_HTML = """
<!DOCTYPE html>
<html lang="ja">
<body>
<img src="{}"/>
</body>
</html>
"""

# 取得カラム: 測定時刻,外気温,湿度,気圧
COL_TIME: str = "measurement_time"
COL_TEMP_OUT: str = "temp_out"
COL_HUMID: str = "humid"
COL_PRESSURE: str = "pressure"
HEADER_WEATHER: str = f'"{COL_TIME}","{COL_TEMP_OUT}","{COL_HUMID}","{COL_PRESSURE}"'

# 気象センサーデバイス名と期間から気象観測データを取得するSQL (PostgreSQL固有関数使用)
QUERY_RANGE_DATA: str = """
SELECT
   measurement_time, temp_out, humid, pressure
FROM
   weather.t_weather
WHERE
   did=(SELECT id FROM weather.t_device WHERE name=%(deviceName)s)
   AND (
     measurement_time >= %(fromDate)s
     AND
     measurement_time < %(toDate)s
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


class PgDatabase(object):
    def __init__(self, conf_path: str, hostname: str = None, logger: logging.Logger = None):
        self.logger = logger
        with open(conf_path, 'r') as fp:
            db_conf = json.load(fp)
            if hostname is None:
                hostname = socket.gethostname()
            db_conf["host"] = db_conf["host"].format(hostname=hostname)
        # default connection is itarable curosr
        self.conn = psycopg2.connect(**db_conf)
        # Dictinaly-like cursor connection.
        # self.conn = psycopg2.connect(**dbconf, cursor_factory=psycopg2.extras.DictCursor)
        if self.logger is not None:
            self.logger.debug(self.conn)

    def get_connection(self):
        return self.conn

    def close(self):
        if self.conn is not None:
            if self.logger is not None:
                self.logger.debug(f"Close {self.conn}")
            self.conn.close()


class WeatherDao:
    def __init__(self, conn: connection, logger: Optional[logging.Logger] = None):
        self.conn = conn
        self.logger = logger

    def getMonthData(self,
                     device_name: str,
                     year_month: str,
                     ) -> Tuple[int, Optional[StringIO]]:
        from_date: str = year_month + "-01"
        exclude_to_date = next_year_month(from_date)
        query_params: Dict = {
            'deviceName': device_name, 'fromDate': from_date, 'toDate': exclude_to_date
        }
        with self.conn.cursor() as cursor:
            cursor.execute(QUERY_RANGE_DATA, query_params)
            tuple_list = cursor.fetchall()
            record_count: int = len(tuple_list)
            if self.logger is not None:
                self.logger.debug(f"tuple_list.size {record_count}")

        if record_count == 0:
            return 0, None
        return record_count, _csv_to_stringio(tuple_list)


def _csv_to_stringio(tuple_list: List[Tuple[str, float, float, float]]) -> StringIO:
    str_buffer = StringIO()
    # ヘッダー出力
    str_buffer.write(HEADER_WEATHER + "\n")
    # レコード出力
    for (m_time, temp_out, humid, pressure) in tuple_list:
        line = f'"{m_time}",{temp_out},{humid},{pressure}\n'
        str_buffer.write(line)

    # StringIO need Set first position
    str_buffer.seek(0)
    return str_buffer


def get_dataframe(dao: WeatherDao,
                  device_name: str, year_month: str,
                  logger: Optional[logging.Logger] = None) -> Optional[pd.DataFrame]:
    record_count: int
    csv_buffer: StringIO
    record_count, csv_buffer = dao.getMonthData(device_name, year_month)
    if logger is not None:
        logger.info(f"{device_name}[{year_month}]: {record_count}")
    # 件数なし
    if record_count == 0:
        return None

    df: DataFrame = pd.read_csv(
        csv_buffer,
        header=0,
        parse_dates=[COL_TIME],
        names=[COL_TIME, COL_TEMP_OUT, COL_HUMID, COL_PRESSURE]
    )
    if logger is not None:
        logger.info(f"{df}")
    return df


def get_all_df(conn: connection,
               device_name: str, curr_year_month,
               logger: Optional[logging.Logger] = None
               ) -> Tuple[Optional[DataFrame], Optional[DataFrame], Optional[str]]:
    dao = WeatherDao(conn, logger=logger)
    try:
        # 今年の年月テータ取得
        df_curr: Optional[pd.DataFrame] = get_dataframe(
            dao, device_name, curr_year_month, logger=logger)
        if df_curr is None:
            return None, None, None

        # 前年の年月テータ取得
        # 前年計算
        prev_ym: str = previous_year_month(curr_year_month)
        df_prev: Optional[DataFrame] = get_dataframe(
            dao, device_name, prev_ym, logger=logger)
        return df_curr, df_prev, prev_ym
    except Exception as err:
        logger.warning(err)
        raise err


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
    # データベースサーバーのホスト名 ※任意 (例) raspi-4
    parser.add_argument("--db-host", type=str, help="Other database hostname.")
    args: argparse.Namespace = parser.parse_args()
    # デバイス名
    param_device_name: str = args.device_name
    # 比較最新年月
    param_year_month = args.year_month

    # database
    db: Optional[PgDatabase] = None
    try:
        db = PgDatabase(DB_CONF, args.db_host, logger=app_logger)
        db_conn: connection = db.get_connection()
        curr_df: Optional[DataFrame]
        prev_df: Optional[DataFrame]
        prev_year_month: Optional[str]
        curr_df, prev_df, prev_year_month = get_all_df(
            db_conn, args.device_name, param_year_month, logger=app_logger)

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
    except psycopg2.Error as db_err:
        app_logger.error(f"type({type(db_err)}): {db_err}")
        exit(1)
    except Exception as exp:
        app_logger.error(exp)
        exit(1)
    finally:
        if db is not None:
            db.close()
