import argparse
import base64
import os
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from matplotlib import rcParams
# 日本語フォントを設定
rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['IPAexGothic']
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.pyplot import setp


WEATHER_IDX_COLUMN = 'measurement_time'
LABEL_FONTSIZE = 10
GRID_STYLES = {"linestyle": "- -", "linewidth": 1.0}

FMT_JP_DATE = "%Y年%m月%d日"
# datetime.weekday(): 月:0, 火:1, ..., 日:6
LIST_DAY_WEEK_JP = ["月", "火", "水", "木", "金", "土", "日"]


def addDayToString(s_date, add_days=1, fmt_date="%Y-%m-%d"):
    """
    日付文字列に加算日数を加えた日付文字列を出力日付書式に従って返却する
    (例) '2022-08-30' + 2日 -> '2022-09-01'
    :param s_date: 日付文字列
    :param add_days: 加算日数 ※マイナス日数の場合
    :param fmt_date: 出力日付書式
    :return: 出力日付書式の加算日付文字列
    """
    dt = datetime.strptime(s_date, fmt_date)
    dt += timedelta(days=add_days)
    s_next = dt.strftime(fmt_date)
    return s_next


def strDateToDatetimeTime000000(s_date):
    """
    日付文字列の "00:00:00"のdatetimeブジェクトを返却する
    :param s_date: 日付文字列
    :return: datetimeブジェクト
    """
    return datetime.strptime(s_date + " 00:00:00", "%Y-%m-%d %H:%M:%S")


def datetimeToJpDateWithWeek(cur_datetime):
    """
    日本語の曜日を含む日付を返却する
    (例) 2022-09-09 -> 2022-09-09 (金)
    :param cur_datetime:日付
    :return: 日本語の曜日を含む日付
    """
    s_date = cur_datetime.strftime(FMT_JP_DATE)
    idx_week = cur_datetime.weekday()
    return "{} ({})".format(s_date, LIST_DAY_WEEK_JP[idx_week])


def _axesTemperatureSetting(ax, df, titleDate):
    """
    温度サブプロット(axes)にタイトル、軸・軸ラベルを設定し、
    DataFrameオプジェクトの外気温・室内気温データをプロットする
    :param ax:温度サブプロット(axes)
    :param df:DataFrameオプジェクト
    :param titleDate: タイトル日付文字列
    """
    ax.plot(df[WEATHER_IDX_COLUMN], df["temp_out"], color="blue", marker="", label="外気温")
    ax.plot(df[WEATHER_IDX_COLUMN], df["temp_in"], color="red", marker="", label="室内気温")
    ax.set_ylim([-20, 40])
    ax.set_ylabel("気温 (℃)", fontsize=LABEL_FONTSIZE)
    ax.legend(loc="best")
    ax.set_title("気象データ：{}".format(titleDate))
    # Hide xlabel
    ax.label_outer()
    ax.grid(GRID_STYLES)


def _axesHumidSetting(ax, df):
    """
    湿度サブプロット(axes)に軸・軸ラベルを設定し、DataFrameオプジェクトの室内湿度データをプロットする
    :param ax:湿度サブプロット(axes)
    :param df:DataFrameオプジェクト
    """
    ax.plot(df[WEATHER_IDX_COLUMN], df["humid"], color="green", marker="")
    ax.set_ylim([0, 100])
    ax.set_ylabel("室内湿度 (％)", fontsize=LABEL_FONTSIZE)
    # Hide xlabel
    ax.label_outer()
    ax.grid(GRID_STYLES)


def _axesPressureSetting(ax, df):
    """
    気圧サブプロット(axes)に軸・軸ラベルを設定し、DataFrameオプジェクトの気圧データをプロットする
    :param ax:湿度サブプロット(axes)
    :param df:DataFrameオプジェクト
    """
    ax.plot(df[WEATHER_IDX_COLUMN], df["pressure"], color="fuchsia", marker="")
    # 気圧 (hPa]: 軸ラベルは時間 (00,03,06,09,12,15,18,21,翌日の00)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
    ax.set_ylim([960, 1030])
    ax.set_ylabel("hPa", fontsize=LABEL_FONTSIZE)
    ax.grid(GRID_STYLES)


def gen_plot_imagetag(csv_file, str_today="now"):
    """
    気象データCSVファイルからMatplotlib画像を生成し、img タグを含むHTML文字列を返却する
    :param csv_file:CSVファイルパス
    :param str_today:当日を表す日付文字列: "now"なら今日, それ以外は有効な日付文字列(YYYY-mm-DD)
    :return: img タグを含むhtml文字列
    """
    # CSVファイルからDataFrameを生成
    df = pd.read_csv(csv_file,
                     header=0,
                     parse_dates=[WEATHER_IDX_COLUMN],
                     names=[WEATHER_IDX_COLUMN, 'temp_out', 'temp_in', 'humid', 'pressure']
                     )
    # タイムスタンプをデータフレームのインデックスに設定
    df.index = df[WEATHER_IDX_COLUMN]

    if str_today == "now":
        first_datetime = datetime.now()
    else:
        # 指定された日付="YYYY-MM-DD"
        first_datetime = datetime.strptime(str_today, "%Y-%m-%d")
    # 当日の日付文字列 ※一旦 dateオブジェクトに変換して"年月日"を取得
    s_first_date = first_datetime.date().isoformat()
    # 表示範囲：当日の "00:00:00" から
    x_day_min = strDateToDatetimeTime000000(s_first_date)
    # 翌日の "00:00:00" 迄
    s_nextday = addDayToString(s_first_date)
    x_day_max = strDateToDatetimeTime000000(s_nextday)
    # タイトル用の日本語日付(曜日)
    title_date = datetimeToJpDateWithWeek(first_datetime)

    # 描画領域生成: 11 x 8インチ
    fig = Figure(figsize=[11, 8])
    # x軸を共有する3行1列のサププロット領域生成
    (ax_temp, ax_humid, ax_pressure) = fig.subplots(3, 1, sharex=True)

    # サブプロット間の間隔を変更する
    fig.subplots_adjust(wspace=0.1, hspace=0.1)
    # 軸ラベルのフォントサイズを設定
    for ax in [ax_temp, ax_humid, ax_pressure]:
        setp(ax.get_xticklabels(), fontsize=9)
        setp(ax.get_yticklabels(), fontsize=9)

    # 1日データx軸の範囲: 当日 00時 から 翌日 00時
    for ax in [ax_temp, ax_humid, ax_pressure]:
        ax.set_xlim([x_day_min, x_day_max])

    # サブプロットの設定
    # 1.外気温と室内気温
    _axesTemperatureSetting(ax_temp, df, title_date)
    # 2.室内湿度
    _axesHumidSetting(ax_humid, df)
    # 3.気圧
    _axesPressureSetting(ax_pressure, df)

    # 画像をバイトストリームに溜め込みそれをbase64エンコードしてレスポンスとして返す
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    data = base64.b64encode(buf.getbuffer()).decode("ascii")
    img_tag = '<img src="data:image/png;base64,{}">'.format(data)
    return img_tag


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-path", type=str, required=True, help="Weather data csv file of absolute path.")
    parser.add_argument("--output-dir", type=str, help="Output HTML directory.")
    parser.add_argument("--today-date", type=str, help="CSV data date: 'now' or 'YYYY-mm-DD'.")
    args = parser.parse_args()

    csv_file = os.path.join(os.path.expanduser(args.csv_path))
    if not os.path.exists(csv_file):
        print("{} is not found!".format(csv_file))
        exit(1)

    file_name = os.path.basename(csv_file)
    name_only = os.path.splitext(file_name)[0]
    html_name = name_only + "_singleFont.html"
    if args.output_dir is None:
        save_dir = os.path.dirname(csv_file)
        html_path = os.path.join(save_dir, html_name)
    else:
        if not not os.path.exists(args.output_dir) or not os.path.isdir(args.output_dir):
            print("{} is not valid output directory!".format(args.output_dir))
            exit(1)
        html_path = os.path.join(args.output_path, html_name)

    today_date = args.today_date
    if today_date is None or (today_date is not None and today_date == 'now'):
        img_tag = gen_plot_imagetag(csv_file)
    else:
        try:
            datetime.strptime(today_date, "%Y-%m-%d")
        except ValueError:
            print("today-date is 'YYYY-MM-DD'")
            exit(1)
        img_tag = gen_plot_imagetag(csv_file, str_today=today_date)

    with open(html_path, 'w') as fp:
        fp.write(img_tag)
    print("Saved: {}".format(html_path))

