import datetime as dtt

import pandas as pd
import plotly.express as px
import streamlit as st
from snowflake.snowpark.context import get_active_session
from snowflake.snowpark.exceptions import SnowparkSQLException


st.set_page_config(layout="wide", page_title="Snowflake Account Usage App")
session = get_active_session()

DATE_FILTER_OPTIONS = [
    "Yesterday",
    "7 Days",
    "1 Month",
    "3 Months",
    "6 Months",
    "1 Year",
    "All Time",
    "Custom Date Range",
]

TIME_BUCKET_CASE = """
case
    when {field} < 10000 then '1: < 10 sec'
    when {field} < 60000 then '2: < 1 min'
    when {field} < 300000 then '3: < 5 min'
    when {field} < 600000 then '4: < 10 min'
    when {field} < 1800000 then '5: < 30 min'
    when {field} < 3600000 then '6: < 60 min'
    when {field} >= 3600000 then '7: >= 1 hour'
end
"""

SHORT_LIVED_TABLE_CASE = """
case
    when datediff('seconds', tm.table_created, tm.table_dropped) < 30 then '1: < 30 sec'
    when datediff('seconds', tm.table_created, tm.table_dropped) < 60 then '2: < 1 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < 120 then '3: < 2 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 3) then '4: < 3 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 4) then '5: < 4 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 5) then '6: < 5 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 10) then '7: < 10 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 30) then '8: < 30 min'
    when datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 60) then '9: < 60 min'
end
"""

st.markdown(
    """
    <style>
        .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
            font-size: 22px;
            font-weight: 700;
        }
        .block-container {
            max-width: 96%;
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def run_query(sql: str) -> pd.DataFrame:
    return session.sql(sql).to_pandas()


@st.cache_data(show_spinner=False)
def run_query_params(sql: str, start_date: str, end_date: str) -> pd.DataFrame:
    return session.sql(sql.format(start_date=start_date, end_date=end_date)).to_pandas()


def init_session_state() -> None:
    defaults = {
        "date_filter": "7 Days",
        "start_date": dtt.date.today() - dtt.timedelta(days=7),
        "end_date": dtt.date.today(),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def validate_account_usage_access() -> None:
    try:
        session.sql("select 1 from snowflake.account_usage.query_history limit 1").collect()
    except SnowparkSQLException:
        st.error(
            "Access error: your current Snowflake role cannot read SNOWFLAKE.ACCOUNT_USAGE. "
            "Ask your admin to grant imported privileges on database SNOWFLAKE to this role."
        )
        st.stop()


def get_date_range(filter_option: str):
    end_date = dtt.date.today()
    date_ranges = {
        "Yesterday": (end_date - dtt.timedelta(days=1), end_date),
        "7 Days": (end_date - dtt.timedelta(days=7), end_date),
        "1 Month": (end_date - dtt.timedelta(days=30), end_date),
        "3 Months": (end_date - dtt.timedelta(days=90), end_date),
        "6 Months": (end_date - dtt.timedelta(days=180), end_date),
        "1 Year": (end_date - dtt.timedelta(days=365), end_date),
        "All Time": (dtt.date(2000, 1, 1), end_date),
    }
    return date_ranges.get(filter_option, (None, None))


def fmt_num(value, decimals=2) -> str:
    if pd.isna(value):
        value = 0
    return f"{float(value):,.{decimals}f}"


def fmt_int(value) -> str:
    if pd.isna(value):
        value = 0
    return f"{int(float(value)):,}"


def shorten_label(text, max_len=28):
    if text is None:
        return "UNKNOWN"
    text = str(text)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def shorten_column_values(df: pd.DataFrame, col_name: str, max_len=28) -> pd.DataFrame:
    if col_name in df.columns:
        df = df.copy()
        df[col_name] = df[col_name].fillna("UNKNOWN").apply(lambda x: shorten_label(x, max_len=max_len))
    return df


def top_n_by_dimension(df: pd.DataFrame, dim_col: str, value_col: str, n=10) -> pd.DataFrame:
    if df.empty or dim_col not in df.columns or value_col not in df.columns:
        return df
    top_keys = (
        df.groupby(dim_col, dropna=False)[value_col]
        .sum()
        .sort_values(ascending=False)
        .head(n)
        .index
    )
    return df[df[dim_col].isin(top_keys)].copy()


def show_metrics(items):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def update_chart_layout(
    fig,
    horizontal=False,
    showlegend=True,
    many_categories=False,
    chart_height=None,
    text_labels=True,
):
    legend_config = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
    margin = dict(t=80, r=40)

    if many_categories:
        legend_config = dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02)
        margin = dict(t=80, r=260)
        chart_height = chart_height or 750

    fig.update_layout(legend=legend_config, showlegend=showlegend, margin=margin)

    if chart_height:
        fig.update_layout(height=chart_height)

    if text_labels:
        fig.update_traces(texttemplate="%{x}" if horizontal else "%{y}", textfont=dict(size=12))
    else:
        fig.update_traces(texttemplate=None)

    return fig


def bar_chart(
    df,
    x,
    y,
    title,
    color=None,
    orientation="v",
    barmode=None,
    showlegend=True,
    many_categories=False,
    chart_height=None,
    text_labels=True,
):
    fig = px.bar(df, x=x, y=y, color=color, orientation=orientation, title=title, barmode=barmode)
    return update_chart_layout(
        fig,
        horizontal=(orientation == "h"),
        showlegend=showlegend,
        many_categories=many_categories,
        chart_height=chart_height,
        text_labels=text_labels,
    )


def render_header_filters():
    st.title("Snowflake Account Usage App :snowflake:")
    st.divider()

    col1, col2 = st.columns([1, 2])
    with col1:
        date_filter = st.selectbox("📅 Select Date Range", DATE_FILTER_OPTIONS, key="date_filter")

    if date_filter == "Custom Date Range":
        with col2:
            sub1, sub2 = st.columns(2)
            with sub1:
                start_date = st.date_input("Start Date", st.session_state["start_date"])
            with sub2:
                end_date = st.date_input("End Date", st.session_state["end_date"])
    else:
        start_date, end_date = get_date_range(date_filter)

    st.session_state["start_date"] = start_date
    st.session_state["end_date"] = end_date
    return str(start_date), str(end_date)


@st.cache_data(show_spinner=False)
def get_cost_summary(start_date: str, end_date: str):
    sql = """
        select round(sum(credits_used), 2) as total_credits
        from snowflake.account_usage.metering_daily_history
        where usage_date between '{start_date}' and '{end_date}'
    """
    return run_query_params(sql, start_date, end_date)


@st.cache_data(show_spinner=False)
def get_cost_by_warehouse(start_date: str, end_date: str, credit_price: float):
    sql = f"""
        select
            warehouse_name,
            round(sum(credits_used), 2) as credits_used,
            round(sum(credits_used_compute), 2) as compute_credits,
            round(sum(credits_used_cloud_services), 2) as cloud_services_credits,
            round(sum(credits_used) * {credit_price}, 2) as total_cost
        from snowflake.account_usage.warehouse_metering_history
        where start_time between '{{start_date}}' and '{{end_date}}'
        group by warehouse_name
        order by credits_used desc
    """
    return run_query_params(sql, start_date, end_date)


@st.cache_data(show_spinner=False)
def get_consumption_summary(start_date: str, end_date: str):
    sql = """
        select
            round(sum(credits_used), 2) as total_credits,
            coalesce(round(sum(case when service_type = 'WAREHOUSE_METERING' then credits_used else 0 end), 2), 0) as warehouse_metering,
            coalesce(round(sum(case when service_type = 'PIPE' then credits_used else 0 end), 2), 0) as pipe,
            coalesce(round(sum(case when service_type = 'TRUST_CENTER' then credits_used else 0 end), 2), 0) as trust_center,
            coalesce(round(sum(case when service_type = 'SERVERLESS_TASK' then credits_used else 0 end), 2), 0) as serverless_task,
            coalesce(round(sum(case when service_type = 'MATERIALIZED_VIEW' then credits_used else 0 end), 2), 0) as materialized_view
        from snowflake.account_usage.metering_history
        where start_time between '{start_date}' and '{end_date}'
    """
    return run_query_params(sql, start_date, end_date)


@st.cache_data(show_spinner=False)
def get_users_summary(start_date: str, end_date: str):
    sql = """
        select
            count(distinct case when deleted_on is null then name end) as total_users,
            count(distinct case when created_on between '{start_date}'::date and '{end_date}'::date and deleted_on is null then name end) as new_users,
            count(distinct case when created_on between '{start_date}'::date and '{end_date}'::date and deleted_on is not null then name end) as dropped_users
        from snowflake.account_usage.users
    """
    return run_query_params(sql, start_date, end_date)


@st.cache_data(show_spinner=False)
def get_storage_summary():
    sql = """
        select
            round(sum(storage_bytes + stage_bytes + failsafe_bytes) / power(1024, 4), 2) as total_storage_tb,
            round(sum(storage_bytes) / power(1024, 4), 2) as timetravel_storage_tb,
            round(sum(stage_bytes) / power(1024, 4), 2) as stage_storage_tb,
            round(sum(failsafe_bytes) / power(1024, 4), 2) as failsafe_storage_tb
        from snowflake.account_usage.storage_usage
    """
    return run_query(sql)


@st.cache_data(show_spinner=False)
def get_performance_summary(start_date: str, end_date: str):
    sql = """
        select
            count(*) as total_jobs,
            sum(case when execution_status = 'SUCCESS' then 1 else 0 end) as success_jobs,
            sum(case when execution_status = 'FAIL' then 1 else 0 end) as failed_jobs
        from snowflake.account_usage.query_history
        where start_time between '{start_date}' and '{end_date}'
    """
    return run_query_params(sql, start_date, end_date)


def render_cost_tab(start_date: str, end_date: str):
    st.header("Cost Dashboard")
    st.divider()

    credit_price = st.number_input("Credit Price ($)", value=3.52, step=0.01, format="%.2f")
    summary = get_cost_summary(start_date, end_date)
    total_credits = float(summary.iat[0, 0] or 0)
    total_cost = total_credits * credit_price

    show_metrics([
        ("Total Credits", fmt_num(total_credits)),
        ("Compute Price/Credit", f"${credit_price:,.2f}"),
        ("Spend in Dollars", f"${total_cost:,.2f}"),
    ])

    st.divider()
    st.subheader("Cost Breakdown by Warehouse")
    df = get_cost_by_warehouse(start_date, end_date, credit_price)
    st.dataframe(df, use_container_width=True, hide_index=True)

    plot_df = shorten_column_values(df, "WAREHOUSE_NAME", max_len=24)
    fig = bar_chart(
        plot_df,
        x="WAREHOUSE_NAME",
        y="TOTAL_COST",
        color="WAREHOUSE_NAME",
        title="Total Cost by Warehouse ($)",
        many_categories=True,
        chart_height=700,
        text_labels=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_consumption_tab(start_date: str, end_date: str):
    st.header("Consumption Dashboard")
    st.divider()
    st.subheader("Credits Usage")

    summary = get_consumption_summary(start_date, end_date).iloc[0]
    show_metrics([
        ("Total Credits", fmt_num(summary["TOTAL_CREDITS"])),
        ("Warehouse Metering", fmt_num(summary["WAREHOUSE_METERING"])),
        ("PIPE", fmt_num(summary["PIPE"])),
        ("Trust Center", fmt_num(summary["TRUST_CENTER"])),
        ("Serverless Task", fmt_num(summary["SERVERLESS_TASK"])),
        ("Materialized Views", fmt_num(summary["MATERIALIZED_VIEW"])),
    ])

    sql_daily = """
        select start_time::date as usage_date, round(sum(credits_used), 2) as total_credits_used
        from snowflake.account_usage.metering_history
        where start_time::date between '{start_date}' and '{end_date}'
        group by 1
        order by 1
    """
    df_daily = run_query_params(sql_daily, start_date, end_date)
    st.plotly_chart(
        bar_chart(df_daily, x="USAGE_DATE", y="TOTAL_CREDITS_USED", color="TOTAL_CREDITS_USED", title="Credits Usage", showlegend=False),
        use_container_width=True,
    )

    sql_service = """
        select start_time::date as usage_date, round(sum(credits_used), 2) as total_credits_used, service_type
        from snowflake.account_usage.metering_history
        where start_time::date between '{start_date}' and '{end_date}'
        group by 1, 3
        order by 1
    """
    df_service = run_query_params(sql_service, start_date, end_date)
    st.plotly_chart(
        bar_chart(df_service, x="USAGE_DATE", y="TOTAL_CREDITS_USED", color="SERVICE_TYPE", title="Credits Used by Service type", text_labels=False),
        use_container_width=True,
    )

    sql_wh = """
        select start_time::date as usage_date, sum(credits_used) as total_credits_used, warehouse_name
        from snowflake.account_usage.warehouse_metering_history
        where start_time between '{start_date}' and '{end_date}'
        group by 1, 3
        order by 3, 1
    """
    df_wh = run_query_params(sql_wh, start_date, end_date)
    df_wh = top_n_by_dimension(df_wh, "WAREHOUSE_NAME", "TOTAL_CREDITS_USED", n=10)
    df_wh = shorten_column_values(df_wh, "WAREHOUSE_NAME", max_len=22)
    st.plotly_chart(
        bar_chart(
            df_wh,
            x="USAGE_DATE",
            y="TOTAL_CREDITS_USED",
            color="WAREHOUSE_NAME",
            title="Credits Used by Warehouse (Top 10)",
            many_categories=True,
            chart_height=700,
            text_labels=False,
        ),
        use_container_width=True,
    )

    sql_gs_util = """
        select query_type, sum(credits_used_cloud_services) as cs_credits, count(1) as num_queries
        from snowflake.account_usage.query_history
        where start_time::date between '{start_date}' and '{end_date}'
        group by 1
        order by 2 desc
        limit 10
    """
    df_gs_util = run_query_params(sql_gs_util, start_date, end_date)
    fig_gs_util = bar_chart(df_gs_util, x="QUERY_TYPE", y="CS_CREDITS", title="Credit Utilization by Query Type (Top 10)", showlegend=False, text_labels=False)
    fig_gs_util.update_traces(marker_color="green")

    sql_gs_wh = """
        select warehouse_name, sum(credits_used_cloud_services) as credits_used_cloud_services
        from snowflake.account_usage.warehouse_metering_history
        where start_time::date between '{start_date}' and '{end_date}'
        group by 1
        order by 2 desc
        limit 10
    """
    df_gs_wh = run_query_params(sql_gs_wh, start_date, end_date)
    df_gs_wh = shorten_column_values(df_gs_wh, "WAREHOUSE_NAME", max_len=20)
    fig_gs_wh = bar_chart(
        df_gs_wh,
        x="WAREHOUSE_NAME",
        y="CREDITS_USED_CLOUD_SERVICES",
        title="Compute and Cloud Services by Warehouse (Top 10)",
        barmode="group",
        showlegend=False,
        text_labels=False,
    )
    fig_gs_wh.update_traces(marker_color="purple")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_gs_util, use_container_width=True)
    with c2:
        st.plotly_chart(fig_gs_wh, use_container_width=True)

    st.info("The below chart is static and not modified by the date range filter", icon="ℹ️")
    sql_billed = """
        select date_trunc('month', usage_date) as usage_month, sum(credits_billed) as credits_billed
        from snowflake.account_usage.metering_daily_history
        group by 1
        order by 1
    """
    df_billed = run_query(sql_billed)
    st.plotly_chart(
        bar_chart(df_billed, x="USAGE_MONTH", y="CREDITS_BILLED", color="CREDITS_BILLED", title="Credits Billed by Month", showlegend=False),
        use_container_width=True,
    )
    st.divider()


def render_users_tab(start_date: str, end_date: str):
    st.header("Users Dashboard")
    st.divider()

    summary = get_users_summary(start_date, end_date).iloc[0]
    show_metrics([
        ("Total Users", fmt_int(summary["TOTAL_USERS"])),
        ("New Users", fmt_int(summary["NEW_USERS"])),
        ("Dropped Users", fmt_int(summary["DROPPED_USERS"])),
    ])

    sql_failed = """
        select count(*) as count, error_message
        from snowflake.account_usage.login_history
        where error_code is not null
          and event_timestamp between '{start_date}'::date and '{end_date}'::date
        group by error_message
        order by count asc
    """
    df_failed = run_query_params(sql_failed, start_date, end_date)
    df_failed = shorten_column_values(df_failed, "ERROR_MESSAGE", max_len=45)
    st.plotly_chart(bar_chart(df_failed, x="COUNT", y="ERROR_MESSAGE", orientation="h", title="Failed Login Attempts", showlegend=False, text_labels=False), use_container_width=True)

    sql_client_types = """
        select count(*) as count, reported_client_type
        from snowflake.account_usage.login_history
        where event_timestamp between '{start_date}'::date and '{end_date}'::date
        group by reported_client_type
        order by count asc
    """
    df_client_types = run_query_params(sql_client_types, start_date, end_date)
    st.plotly_chart(bar_chart(df_client_types, x="COUNT", y="REPORTED_CLIENT_TYPE", orientation="h", title="Client Types", showlegend=False, text_labels=False), use_container_width=True)

    sql_logins_client = """
        select
            reported_client_type as client,
            sum(iff(is_success = 'NO', 1, 0)) as failed,
            sum(iff(is_success = 'YES', 1, 0)) as success
        from snowflake.account_usage.login_history
        where event_timestamp between '{start_date}'::date and '{end_date}'::date
        group by 1
    """
    df_logins = run_query_params(sql_logins_client, start_date, end_date)
    fig_success = bar_chart(df_logins, x="SUCCESS", y="CLIENT", orientation="h", title="Successful Logins by Client", showlegend=False, text_labels=False)
    fig_failed = bar_chart(df_logins, x="FAILED", y="CLIENT", orientation="h", title="Failed Logins by Client", showlegend=False, text_labels=False)
    fig_failed.update_traces(marker_color="red")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_success, use_container_width=True)
    with c2:
        st.plotly_chart(fig_failed, use_container_width=True)
    st.divider()


def render_storage_tab(start_date: str, end_date: str):
    st.header("Storage Dashboard")
    st.divider()

    summary = get_storage_summary().iloc[0]
    show_metrics([
        ("Total Storage (TB)", fmt_num(summary["TOTAL_STORAGE_TB"])),
        ("TimeTravel Storage (TB)", fmt_num(summary["TIMETRAVEL_STORAGE_TB"])),
        ("Stage Storage (TB)", fmt_num(summary["STAGE_STORAGE_TB"])),
        ("Fail Safe Storage (TB)", fmt_num(summary["FAILSAFE_STORAGE_TB"])),
    ])

    st.divider()
    st.info("The below chart is static and non modified by the date range filter", icon="ℹ️")

    sql_storage_overtime = """
        select
            date_trunc(month, usage_date) as usage_month,
            avg(storage_bytes + stage_bytes + failsafe_bytes) / power(1024, 3) as billable_gb,
            avg(storage_bytes) / power(1024, 3) as storage_gb,
            avg(stage_bytes) / power(1024, 3) as stage_gb,
            avg(failsafe_bytes) / power(1024, 3) as failsafe_gb
        from snowflake.account_usage.storage_usage
        group by 1
        order by 1
    """
    df_storage_overtime = run_query(sql_storage_overtime)
    st.plotly_chart(bar_chart(df_storage_overtime, x="USAGE_MONTH", y="BILLABLE_GB", color="BILLABLE_GB", title="Data Storage used Overtime", showlegend=False), use_container_width=True)

    st.divider()

    sql_storage_day_gb = """
        select
            usage_date,
            round(storage_bytes / power(2, 30), 3) as timetravel_storage_gb,
            round(stage_bytes / power(2, 30), 3) as internal_stage_gb,
            round(failsafe_bytes / power(2, 30), 3) as failsafe_gb
        from snowflake.account_usage.storage_usage
        where usage_date between '{start_date}' and '{end_date}'
        order by usage_date
    """
    df_day_gb = run_query_params(sql_storage_day_gb, start_date, end_date)
    fig_day_gb = bar_chart(df_day_gb, x="USAGE_DATE", y=["TIMETRAVEL_STORAGE_GB", "INTERNAL_STAGE_GB", "FAILSAFE_GB"], title="Storage by day in GB", barmode="group", text_labels=False)

    sql_storage_day_mb = """
        select
            usage_date,
            round(storage_bytes / power(2, 30), 2) as timetravel_storage_mb,
            round(stage_bytes / power(2, 30), 2) as internal_stage_mb,
            round(failsafe_bytes / power(2, 30), 2) as failsafe_mb
        from snowflake.account_usage.storage_usage
        where usage_date between '{start_date}' and '{end_date}'
        order by usage_date
    """
    df_day_mb = run_query_params(sql_storage_day_mb, start_date, end_date)
    fig_day_mb = bar_chart(df_day_mb, x="USAGE_DATE", y=["TIMETRAVEL_STORAGE_MB", "INTERNAL_STAGE_MB", "FAILSAFE_MB"], title="Storage by day in MB", barmode="group", text_labels=False)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_day_gb, use_container_width=True)
    with c2:
        st.plotly_chart(fig_day_mb, use_container_width=True)

    sql_storage_db_mb = """
        select
            table_catalog as database_name,
            round(sum(active_bytes) / power(2, 20), 2) as active_storage_mb,
            round(sum(time_travel_bytes) / power(2, 20), 2) as time_travel_storage_mb,
            round(sum(failsafe_bytes) / power(2, 20), 2) as failsafe_storage_mb,
            round(sum(retained_for_clone_bytes) / power(2, 20), 2) as retained_for_clone_storage_mb,
            round(sum(active_bytes + time_travel_bytes + failsafe_bytes + retained_for_clone_bytes) / power(2, 20), 2) as total_storage_mb
        from snowflake.account_usage.table_storage_metrics
        group by 1
        order by total_storage_mb asc
    """
    df_storage_db_mb = run_query(sql_storage_db_mb)
    df_storage_db_mb = shorten_column_values(df_storage_db_mb, "DATABASE_NAME", max_len=24)
    fig_storage_db_mb = bar_chart(
        df_storage_db_mb,
        x=["ACTIVE_STORAGE_MB", "TIME_TRAVEL_STORAGE_MB", "FAILSAFE_STORAGE_MB", "RETAINED_FOR_CLONE_STORAGE_MB", "TOTAL_STORAGE_MB"],
        y="DATABASE_NAME",
        orientation="h",
        title="Storage by Database in MB",
        text_labels=False,
    )
    st.plotly_chart(fig_storage_db_mb, use_container_width=True)

    sql_storage_db_gb = """
        select
            table_catalog as database_name,
            round(sum(active_bytes) / power(2, 30), 2) as active_storage_gb,
            round(sum(time_travel_bytes) / power(2, 30), 2) as time_travel_storage_gb,
            round(sum(failsafe_bytes) / power(2, 30), 2) as failsafe_storage_gb,
            round(sum(retained_for_clone_bytes) / power(2, 30), 2) as retained_for_clone_storage_gb,
            round(sum(active_bytes + time_travel_bytes + failsafe_bytes + retained_for_clone_bytes) / power(2, 30), 2) as total_storage_gb
        from snowflake.account_usage.table_storage_metrics
        group by 1
        order by total_storage_gb asc
    """
    df_storage_db_gb = run_query(sql_storage_db_gb)
    df_storage_db_gb = shorten_column_values(df_storage_db_gb, "DATABASE_NAME", max_len=24)
    fig_storage_db_gb = bar_chart(
        df_storage_db_gb,
        x=["ACTIVE_STORAGE_GB", "TIME_TRAVEL_STORAGE_GB", "FAILSAFE_STORAGE_GB", "RETAINED_FOR_CLONE_STORAGE_GB", "TOTAL_STORAGE_GB"],
        y="DATABASE_NAME",
        orientation="h",
        title="Storage by Database in GB",
        text_labels=False,
    )
    st.plotly_chart(fig_storage_db_gb, use_container_width=True)

    sql_short_lived = f"""
        select
            concat(tm.table_catalog, '.', tm.table_schema) as schema_name,
            {SHORT_LIVED_TABLE_CASE} as time_group,
            count(*) as table_count
        from snowflake.account_usage.table_storage_metrics tm
        where tm.deleted = true
          and tm.table_created::date between '{{start_date}}'::date and '{{end_date}}'::date
          and tm.is_transient = 'NO'
          and datediff('seconds', tm.table_created, tm.table_dropped) < (60 * 60)
          and left(table_name, 3) <> 'TMP'
          and left(table_name, 4) <> 'TEMP'
          and right(table_name, 3) <> 'TMP'
          and right(table_name, 4) <> 'TEMP'
        group by 1, 2
        order by 2 desc
    """
    df_short_lived = run_query_params(sql_short_lived, start_date, end_date)
    df_short_lived = shorten_column_values(df_short_lived, "SCHEMA_NAME", max_len=28)
    st.plotly_chart(bar_chart(df_short_lived, x="TABLE_COUNT", y="SCHEMA_NAME", color="TIME_GROUP", orientation="h", title="Short lived Tables", text_labels=False), use_container_width=True)

    sql_rows_loaded = """
        select to_timestamp(date_trunc(day, last_load_time)) as usage_date, sum(row_count) as total_rows
        from snowflake.account_usage.load_history
        where last_load_time::date between '{start_date}'::date and '{end_date}'::date
        group by 1
        order by usage_date desc
    """
    df_rows_loaded = run_query_params(sql_rows_loaded, start_date, end_date)
    st.plotly_chart(bar_chart(df_rows_loaded, x="USAGE_DATE", y="TOTAL_ROWS", title="Rows Loaded Overtime (Copy Into)", showlegend=False), use_container_width=True)
    st.divider()


def render_performance_tab(start_date: str, end_date: str):
    st.header("Performance Dashboard")
    st.divider()

    summary = get_performance_summary(start_date, end_date).iloc[0]
    show_metrics([
        ("Total # of Jobs Executed", fmt_int(summary["TOTAL_JOBS"])),
        ("Total Successful Jobs Executed", fmt_int(summary["SUCCESS_JOBS"])),
        ("Total failed Jobs", fmt_int(summary["FAILED_JOBS"])),
    ])

    exec_case = TIME_BUCKET_CASE.format(field="qh.execution_time")
    compilation_case = TIME_BUCKET_CASE.format(field="qh.compilation_time")
    queued_case = TIME_BUCKET_CASE.format(field="qh.queued_overload_time")

    sql_exec = f"""
        select {exec_case} as time_group, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time::date between '{{start_date}}' and '{{end_date}}'
          and qh.execution_time is not null and qh.execution_time > 0
          and qh.warehouse_size is not null
        group by 1
        order by 1
    """
    df_exec = run_query_params(sql_exec, start_date, end_date)
    st.plotly_chart(bar_chart(df_exec, x="QUERY_COUNT", y="TIME_GROUP", orientation="h", title="Query Execution by Time Bucket", showlegend=False), use_container_width=True)

    sql_compilation = f"""
        select {compilation_case} as time_group, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.compilation_time is not null and qh.compilation_time > 0
          and qh.warehouse_size is not null
        group by 1
        order by 1
    """
    df_compilation = run_query_params(sql_compilation, start_date, end_date)
    st.plotly_chart(bar_chart(df_compilation, x="QUERY_COUNT", y="TIME_GROUP", orientation="h", title="Query Compilation Stats", showlegend=False), use_container_width=True)

    sql_queued = f"""
        select {queued_case} as time_group, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.execution_time is not null and qh.execution_time > 0
          and qh.warehouse_size is not null
        group by 1
        order by 1
    """
    df_queued = run_query_params(sql_queued, start_date, end_date)
    st.plotly_chart(bar_chart(df_queued, x="QUERY_COUNT", y="TIME_GROUP", orientation="h", title="Query Queued Stats", showlegend=False), use_container_width=True)

    sql_exec_wh_time = f"""
        select {exec_case} as time_group, qh.warehouse_name as warehouse_name, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.execution_time is not null and qh.execution_time > 0
          and qh.warehouse_size is not null
        group by 1, 2
        order by 1, 2
    """
    df_exec_wh_time = run_query_params(sql_exec_wh_time, start_date, end_date)
    df_exec_wh_time = top_n_by_dimension(df_exec_wh_time, "WAREHOUSE_NAME", "QUERY_COUNT", n=10)
    df_exec_wh_time = shorten_column_values(df_exec_wh_time, "WAREHOUSE_NAME", max_len=22)
    st.plotly_chart(
        bar_chart(
            df_exec_wh_time,
            x="QUERY_COUNT",
            y="TIME_GROUP",
            color="WAREHOUSE_NAME",
            orientation="h",
            title="Query Execution by Time Bucket by Warehouse (Top 10)",
            many_categories=True,
            chart_height=700,
            text_labels=False,
        ),
        use_container_width=True,
    )

    sql_exec_wh_name = f"""
        select {exec_case} as time_group, qh.warehouse_name as warehouse_name, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.execution_time is not null and qh.execution_time > 0
          and qh.warehouse_size is not null
        group by 1, 2
        order by 1, 2
    """
    df_exec_wh_name = run_query_params(sql_exec_wh_name, start_date, end_date)
    df_exec_wh_name = top_n_by_dimension(df_exec_wh_name, "WAREHOUSE_NAME", "QUERY_COUNT", n=10)
    df_exec_wh_name = shorten_column_values(df_exec_wh_name, "WAREHOUSE_NAME", max_len=22)
    st.plotly_chart(
        bar_chart(
            df_exec_wh_name,
            x="QUERY_COUNT",
            y="WAREHOUSE_NAME",
            color="TIME_GROUP",
            orientation="h",
            title="Query Execution by Time Bucket by Warehouse View (Top 10)",
            text_labels=False,
        ),
        use_container_width=True,
    )

    sql_compilation_wh = f"""
        select {compilation_case} as time_group, qh.warehouse_name as warehouse_name, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.compilation_time is not null and qh.compilation_time > 0
          and qh.warehouse_size is not null
        group by 1, 2
        order by 1, 2
    """
    df_compilation_wh = run_query_params(sql_compilation_wh, start_date, end_date)
    df_compilation_wh = top_n_by_dimension(df_compilation_wh, "WAREHOUSE_NAME", "QUERY_COUNT", n=10)
    df_compilation_wh = shorten_column_values(df_compilation_wh, "WAREHOUSE_NAME", max_len=22)
    st.plotly_chart(
        bar_chart(
            df_compilation_wh,
            x="QUERY_COUNT",
            y="TIME_GROUP",
            color="WAREHOUSE_NAME",
            barmode="group",
            orientation="h",
            title="Query Compilation Stats by Warehouse (Top 10)",
            many_categories=True,
            chart_height=720,
            text_labels=False,
        ),
        use_container_width=True,
    )

    sql_queued_wh = f"""
        select {queued_case} as time_group, qh.warehouse_name as warehouse_name, count(*) as query_count
        from snowflake.account_usage.query_history qh
        where qh.start_time between '{{start_date}}' and '{{end_date}}'
          and qh.execution_time is not null and qh.execution_time > 0
          and qh.warehouse_size is not null
        group by 1, 2
        order by 1, 2
    """
    df_queued_wh = run_query_params(sql_queued_wh, start_date, end_date)
    df_queued_wh = top_n_by_dimension(df_queued_wh, "WAREHOUSE_NAME", "QUERY_COUNT", n=10)
    df_queued_wh = shorten_column_values(df_queued_wh, "WAREHOUSE_NAME", max_len=22)
    st.plotly_chart(
        bar_chart(
            df_queued_wh,
            x="QUERY_COUNT",
            y="TIME_GROUP",
            color="WAREHOUSE_NAME",
            barmode="group",
            orientation="h",
            title="Query Queued Stats by Warehouse (Top 10)",
            many_categories=True,
            chart_height=720,
            text_labels=False,
        ),
        use_container_width=True,
    )

    sql_role = """
        with ranked_data as (
            select
                date_trunc('day', qh.start_time)::date as usage_date,
                qh.role_name,
                count(*) as query_count,
                rank() over (partition by date_trunc('day', qh.start_time)::date order by count(*) desc) as role_rank
            from snowflake.account_usage.query_history qh
            where qh.start_time::date between '{start_date}'::date and '{end_date}'::date
              and (qh.role_name ilike 'AAD%' or qh.role_name ilike '%ETLSVC%' or qh.role_name ilike '%ADMIN' or qh.role_name ilike '%PROFILE%')
            group by 1, 2
        )
        select
            usage_date,
            case when role_rank <= 5 then role_name else 'Other' end as role_group,
            sum(query_count) as query_count
        from ranked_data
        group by 1, 2
        order by 1 desc, 3 desc
    """
    df_role = run_query_params(sql_role, start_date, end_date)
    df_role = shorten_column_values(df_role, "ROLE_GROUP", max_len=22)
    st.plotly_chart(bar_chart(df_role, x="USAGE_DATE", y="QUERY_COUNT", color="ROLE_GROUP", barmode="group", title="Queries by Role", text_labels=False), use_container_width=True)

    sql_exec_qtype = """
        select query_type, warehouse_size, round(avg(execution_time) / 60000, 2) as average_execution_time
        from snowflake.account_usage.query_history
        where start_time between '{start_date}' and '{end_date}'
        group by 1, 2
        order by 3 asc
    """
    df_exec_qtype = run_query_params(sql_exec_qtype, start_date, end_date)
    st.plotly_chart(bar_chart(df_exec_qtype, x="AVERAGE_EXECUTION_TIME", y="QUERY_TYPE", orientation="h", title="Average Execution by Query Type", showlegend=False, text_labels=False), use_container_width=True)

    sql_longest_success = """
        select query_id, left(query_text, 40) as query_text, (execution_time / 60000) as exec_time
        from snowflake.account_usage.query_history
        where execution_status = 'SUCCESS'
          and start_time between '{start_date}' and '{end_date}'
        order by execution_time desc
        limit 25
    """
    df_longest_success = run_query_params(sql_longest_success, start_date, end_date)
    fig_longest_success = bar_chart(df_longest_success, x="EXEC_TIME", y="QUERY_TEXT", orientation="h", title="Longest Successful Queries (Top 25)", showlegend=False, text_labels=False)

    sql_longest_fail = """
        select query_id, left(query_text, 40) as query_text, (execution_time / 60000) as exec_time
        from snowflake.account_usage.query_history
        where execution_status = 'FAIL'
          and start_time between '{start_date}' and '{end_date}'
        order by execution_time desc
        limit 25
    """
    df_longest_fail = run_query_params(sql_longest_fail, start_date, end_date)
    fig_longest_fail = bar_chart(df_longest_fail, x="EXEC_TIME", y="QUERY_TEXT", orientation="h", title="Longest Failed Queries (Top 25)", showlegend=False, text_labels=False)
    fig_longest_fail.update_traces(marker_color="red")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_longest_success, use_container_width=True)
    with c2:
        st.plotly_chart(fig_longest_fail, use_container_width=True)

    sql_total_exec = """
        select left(query_text, 40) as query_text, (sum(execution_time) / 60000) as exec_time
        from snowflake.account_usage.query_history
        where execution_status = 'SUCCESS'
          and start_time between '{start_date}' and '{end_date}'
        group by 1
        order by exec_time desc
        limit 10
    """
    df_total_exec = run_query_params(sql_total_exec, start_date, end_date)
    fig_total_exec = bar_chart(df_total_exec, x="EXEC_TIME", y="QUERY_TEXT", orientation="h", title="Total Execution Time by Repeated Queries", showlegend=False, text_labels=False)
    fig_total_exec.update_traces(marker_color="LightSkyBlue")
    st.plotly_chart(fig_total_exec, use_container_width=True)

    sql_avg_exec_user = """
        select user_name, avg(execution_time) / 1000 as average_execution_time
        from snowflake.account_usage.query_history
        where start_time between '{start_date}' and '{end_date}'
        group by 1
        order by 2 desc
        limit 10
    """
    df_avg_exec_user = run_query_params(sql_avg_exec_user, start_date, end_date)
    df_avg_exec_user = shorten_column_values(df_avg_exec_user, "USER_NAME", max_len=24)
    fig_avg_exec_user = bar_chart(df_avg_exec_user, x="USER_NAME", y="AVERAGE_EXECUTION_TIME", title="Average Execution Time per User", showlegend=False, text_labels=False)
    fig_avg_exec_user.update_traces(marker_color="MediumPurple")
    st.plotly_chart(fig_avg_exec_user, use_container_width=True)
    st.divider()


def main():
    init_session_state()
    validate_account_usage_access()
    start_date, end_date = render_header_filters()

    cost_tab, consumption_tab, users_tab, storage_tab, performance_tab = st.tabs([
        "Cost Dashboard | ",
        "Consumption Dashboard | ",
        "Users Dashboard | ",
        "Storage Dashboard | ",
        "Performance Dashboard",
    ])

    with cost_tab:
        render_cost_tab(start_date, end_date)
    with consumption_tab:
        render_consumption_tab(start_date, end_date)
    with users_tab:
        render_users_tab(start_date, end_date)
    with storage_tab:
        render_storage_tab(start_date, end_date)
    with performance_tab:
        render_performance_tab(start_date, end_date)


if __name__ == "__main__":
    main()
