import argparse
import logging
import json
import os
import socket
from typing import Dict, List

from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy import create_engine
from sqlalchemy.sql import text

"""
気象センサーデータベースの外気温データの前年度月データがある最新の年月リストを取得する
[DB] sensors_pgdb
[テーブル] weather.t_weather
"""
# ログフォーマット
LOG_FMT = '%(levelname)s %(message)s'

# 健康管理データベース接続情報
DB_CONF: str = os.path.join("conf", "db_sensors.json")

# 1年前の同月データがある最新の年月を取得
QUERY = """
WITH t_year_month AS(
  SELECT
    did
    ,to_char(measurement_time, 'YYYYMM') AS year_month
  FROM
    weather.t_device dev
    INNER JOIN weather.t_weather w ON dev.id = w.did
  WHERE
    dev.name=:deviceName
  GROUP BY did,year_month
)
SELECT
  curr.year_month as latest_year_month
FROM
  t_year_month curr
  INNER JOIN t_year_month prev ON curr.did = prev.did
WHERE
  to_number(curr.year_month, '999999') = to_number(prev.year_month, '999999') + 100
ORDER BY latest_year_month DESC;
"""


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


if __name__ == '__main__':
    logging.basicConfig(format=LOG_FMT)
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(level=logging.DEBUG)

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    # デバイス名: esp8266_1
    parser.add_argument("--device-name", type=str, required=True,
                        help="device name in t_device.")
    # ホスト名 ※任意 (例) raspi-4
    parser.add_argument("--db-host", type=str, help="Other database hostname.")
    args: argparse.Namespace = parser.parse_args()
    # 複合主キー: デバイス名
    device_name: str = args.device_name
    # DBサーバーホスト
    db_host = args.db_host

    connDict: dict = getDBConnectionWithDict(DB_CONF, hostname=db_host)
    # データベース接続URL生成
    connUrl: URL = URL.create(**connDict)
    app_logger.info(f"connUrl: {connUrl}")
    # SQLAlchemyデータベースエンジン
    engine: Engine = create_engine(connUrl, echo=False)

    query_params: Dict = {"deviceName": device_name}
    rows: List[str]
    try:
        with engine.connect() as conn:
            result: CursorResult = conn.execute(text(QUERY), parameters=query_params)
            app_logger.info(f"type(result): {type(result)}")
            # Tupleの1桁目を取得
            # type(row): <class 'sqlalchemy.engine.row.Row'>, ('202306',)
            rows = [row[0] for row in result]
    except Exception as err:
        app_logger.warning(err)
        exit(1)

    app_logger.info(f"{rows}")

"""
(raspi4_apps) yukio@Dell-T7500:~/py_project/weather_sensor$ python GetLatestYearMonth.py --device-name esp8266_1
INFO connUrl: postgresql+psycopg2://developer:***@Dell-T7500.local:5432/sensors_pgdb
INFO type(result): <class 'sqlalchemy.engine.cursor.CursorResult'>
INFO ['202306', '202305', '202304', '202303', '202302', '202301']
"""