import argparse
import json
import logging
import os
import socket
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pandas.core.frame import DataFrame

import sqlalchemy.orm.scoping as scoping
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import scoped_session, sessionmaker

from plotter.plotterweather import gen_plot_image

"""
気象センサーデータの前年対比グラフをHTMLに出力する 
[Database] PostgreSQL
[Database library] SQLAlchemy (pip install sqlalchemy)
https://docs.sqlalchemy.org/en/20/tutorial/index.html
SQLAlchemy Unified Tutorial
"""

# スクリプト名
script_name = os.path.basename(__file__)
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 気象センサーデータベース接続情報
DB_CONF: str = os.path.join("conf", "db_sensors.json")

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

# 気象センサーデバイス名と期間から気象観測データを取得するSQL (SQLAlchemy用)
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


def get_engine_url(conf_path: str, hostname: str = None) -> URL:
    """
    SQLAlchemyの接続URLを取得する
    :param conf_path: 接続設定ファイルパス (JSON形式)
    :param hostname: ホスト名 ※未設定なら実行PCのホスト名
    :return: SQLAlchemyのURL用辞書オブジェクトDB_HEALTHCARE_CONF
    """
    with open(conf_path, 'r') as fp:
        db_conf: json = json.load(fp)
        if hostname is None:
            hostname = socket.gethostname()
        # host in /etc/hostname: "hostname.local"
        db_conf["host"] = db_conf["host"].format(hostname=hostname)
    return URL.create(**db_conf)


def get_dataframe(scoped_sess: scoped_session,
                  device_name: str, year_month: str,
                  logger: Optional[logging.Logger] = None) -> DataFrame:
    from_date: str = year_month + "-01"
    exclude_to_date = next_year_month(from_date)
    query_params: Dict = {
        'deviceName': device_name, 'fromDate': from_date, 'toDate': exclude_to_date
    }
    if logger is not None:
        logger.info(f"query_params: {query_params}")
    try:
        with scoped_sess.connection() as conn:
            df: pd.DataFrame = pd.read_sql(
                QUERY_RANGE_DATA, conn,
                params=query_params,
                parse_dates=[COL_TIME]
            )
        if logger is not None:
            logger.info(f"{df}")
        return df
    finally:
        scoped_sess.close()


def get_all_df(cls_sess: scoping.scoped_session,
               device_name: str, curr_year_month: str,
               logger: Optional[logging.Logger] = None
               ) -> Tuple[Optional[DataFrame], Optional[DataFrame], Optional[str]]:
    sess: scoped_session = cls_sess()
    if logger is not None:
        logger.info(f"scoped_sess: {sess}")

    df_curr: Optional[DataFrame]
    df_prev: Optional[DataFrame]
    try:
        # 今年の年月テータ取得
        df_curr = get_dataframe(sess, device_name, curr_year_month, logger=logger)
        if df_curr is not None and df_curr.shape[0] == 0:
            return None, None, curr_year_month

        # 前年の年月テータ取得
        # 前年計算
        prev_ym: str = previous_year_month(curr_year_month)
        df_prev = get_dataframe(sess, device_name, prev_ym, logger=logger)
        return df_curr, df_prev, prev_ym
    finally:
        cls_sess.remove()


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

    # データベース接続URL生成
    connUrl: URL = get_engine_url(DB_CONF, args.db_host)
    app_logger.info(f"connUrl: {connUrl}")
    Cls_sess: Optional[scoping.scoped_session] = None
    try:
        # SQLAlchemyデータベースエンジン
        db_engine: Engine = create_engine(connUrl, echo=False)
        eng_autocommit = db_engine.execution_options(isolation_level="AUTOCOMMIT")
        app_logger.info(f"db_engine: {db_engine}")

        # https://docs.sqlalchemy.org/en/20/orm/session_basics.html
        #  Session Basics
        sess_factory = sessionmaker(bind=eng_autocommit)
        app_logger.info(f"sess_factory: {sess_factory}")
        # Sessionクラスは sqlalchemy.orm.scoping.scoped_session
        Cls_sess: scoping.scoped_session = scoped_session(sess_factory)
        app_logger.info(f"Session class: {Cls_sess}")
        curr_df: Optional[DataFrame]
        prev_df: Optional[DataFrame]
        prev_year_month: Optional[str]
        curr_df, prev_df, prev_year_month = get_all_df(
            Cls_sess, args.device_name, param_year_month, logger=app_logger)

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
        if Cls_sess is not None:
            Cls_sess.remove()
