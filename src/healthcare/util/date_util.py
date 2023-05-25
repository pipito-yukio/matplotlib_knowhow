from datetime import datetime, timedelta


def add_day_string(s_date, add_days=1, fmt_date="%Y-%m-%d"):
    dt = datetime.strptime(s_date, fmt_date)
    dt += timedelta(days=add_days)
    s_next = dt.strftime(fmt_date)
    return s_next
