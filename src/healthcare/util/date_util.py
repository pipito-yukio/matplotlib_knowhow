from datetime import datetime, timedelta

"""
日付処理ユーティリティ
"""

# デフォルトの日付フォーマット (ISO8601形式)
FMT_ISO8601 = "%Y-%m-%d"


def add_day_string(s_date: str, add_days=1, fmt_date=FMT_ISO8601) -> str:
    """
    指定された日付文字列に指定された日数を加減算する
    :param s_date: 日付文字列
    :param add_days: 加算(n)または減算(-n)する日数
    :param fmt_date: デフォルト ISO8601形式
    :return: 加減算した日付文字列
    """
    dt = datetime.strptime(s_date, fmt_date)
    dt += timedelta(days=add_days)
    s_next = dt.strftime(fmt_date)
    return s_next


def check_str_date(s_date, fmt_date=FMT_ISO8601) -> bool:
    """
    日付文字列チェック
    :param s_date: 日付文字列
    :param fmt_date: デフォルト ISO8601形式
    :return: 日付文字列ならTrue, それ以外はFalse
    """
    try:
        datetime.strptime(s_date, fmt_date)
        return True
    except ValueError:
        return False
