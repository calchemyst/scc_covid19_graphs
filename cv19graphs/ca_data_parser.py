import logging
from dataclasses import dataclass

import math
import time
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import matplotlib.pyplot as plt
import pandas as pd


logger = logging.getLogger(__name__)
NYC_COUNTY = "New York City"
NYC_FIPS = 36061
CHARTS = {
    "cases_log": {"chart_title": "COVID19 Total Cases",
                  "ydata": "cases",
                  "yscale": "log",
                  "ylabel": "Total Cases (log scale)"},
    "cases": {"chart_title": "COVID19 Total Cases",
              "ylabel": "Total Cases"},
    "deaths": {"chart_title": "COVID19 Total Deaths",
               "ylabel": "Total Deaths"},
    "new_cases": {"chart_title": "COVID19 New Cases",
                  "ylabel": "New Cases"},
    "new_deaths": {"chart_title": "COVID19 New Deaths",
                   "ylabel": "New Deaths"},
    "cases_per_capita": {
        "ydata": "cases_pc",
        "chart_title": "Cases per Capita",
        "ylabel": "Cases p/c"
    },
    "deaths_per_capita": {
        "ydata": "deaths_pc",
        "chart_title": "Deaths per Capita",
        "ylabel": "Deaths p/c"
    }
}
DEFAULT_CHART_TYPE = "cases"
MAX_TICKS = 20


@dataclass
class ParserGlobals:
    us_counties: pd.DataFrame
    latest_date: str


pglobals = ParserGlobals(pd.DataFrame(), "")


def reload_us_counties() -> None:
    counties = pd.read_csv("us-counties.csv",
                           dtype={"county": "string",
                                  "state": "string",
                                  "fips": "Int32",
                                  "cases": "Int32",
                                  "deaths": "Int32"},
                           parse_dates=[0])
    # fix empty FIPS for NYC
    counties.loc[(counties.county == NYC_COUNTY) & (counties.fips.isnull()), 'fips'] = NYC_FIPS

    # add "new_cases" computed column
    deltas = counties.groupby(by=["state", "county"]).diff(axis=1).convert_dtypes().fillna(0)
    counties["new_cases"] = deltas.cases
    counties["new_deaths"] = deltas.deaths

    #   add per capita columns
    # load population column
    countypops = pd.read_csv("countypops.csv",
                             dtype={
                                 "state": "string",
                                 "county": "string",
                                 "population": "Int64",
                             })
    countypops.set_index(["state", "county"], inplace=True)
    counties.set_index(["state", "county"], inplace=True)
    counties = counties.join(countypops)
    counties.reset_index(inplace=True)

    counties["cases_pc"] = counties.cases / counties.population
    counties["deaths_pc"] = counties.deaths / counties.population

    pglobals.latest_date = counties.date.tail(1).dt.strftime("%Y-%m-%d").values[0]
    if not pglobals.us_counties.empty:
        del pglobals.us_counties
        pglobals.us_counties = counties


logger.info("Loading covid-19 data by county...")
start_load = time.time()
reload_us_counties()
end_load = time.time()
logger.info("Done.  Took %.3f seconds", end_load-start_load)


class NoDataAvailableException(BaseException):
    pass


def get_county_data(counties: Iterable[int], us_counties=pglobals.us_counties) -> List[pd.DataFrame]:
    if us_counties.empty:
        logger.warning("us_counties is empty!")
        return []
    dfs = []
    for fips in counties:
        df = us_counties.loc[us_counties.fips == fips]
        if df.empty:
            continue
        dfs.append(df)
    return dfs


def find_min_nonzero_date(dfs: Iterable[pd.DataFrame], cutoff: int) -> Optional[pd.Timestamp]:
    max_date = pd.Timestamp.max
    max_df_date = pd.Timestamp.min
    min_nonzero_date = max_date
    for df in dfs:
        df.sort_values('date')
        max_df_date = max(max_df_date, df.date.max())
        nonzero_cases = df[df.cases > cutoff]
        if not nonzero_cases.empty:
            min_nonzero_date = min(min_nonzero_date, nonzero_cases.head(1).date.values[0])
    if min_nonzero_date != max_date and min_nonzero_date != max_df_date:
        return min_nonzero_date
    return None


def combine_date_ranges(dfs: List[pd.DataFrame]) -> pd.Series:
    dr = dfs[0].date
    for df in dfs[1:]:
        dr = dr.append(df.date)
    dr = dr.sort_values().unique()
    return pd.Series(dr)


def decimate_ticks(daterange: pd.Series) -> List[datetime]:
    num_ticks = len(daterange)
    logger.debug("decimate_ticks: %d ticks", num_ticks)
    if num_ticks < MAX_TICKS:
        return list(daterange.array.date)
    divisor = math.ceil(num_ticks / MAX_TICKS)
    last_date = daterange.array.date[-1]
    if divisor > 1:
        dateticks = list(daterange[::divisor].array.date)
        logger.debug("decimate_ticks: decimated by /%d - %d ticks", divisor, len(dateticks))
    else:
        dateticks = list(daterange[:MAX_TICKS].array.date)
        logger.debug("decimate_ticks: truncated to %d", len(dateticks))
    if last_date not in dateticks:
        logger.debug("decimate_ticks: last_date no longer in date ticks!")
        tick_end = dateticks[-1]
        if abs(tick_end - last_date) < timedelta(days=7):
            dateticks = list(dateticks[:-1]) + [last_date]
            logger.debug("decimate_ticks: end of tick range (%s) too close to last_date (%s)", tick_end, last_date)
        else:
            dateticks += [last_date]
            logger.debug("decimate_ticks: Adding last_date back in.")
    return dateticks


def plot_counties(dfs: List[pd.DataFrame], chart_type: Optional[str], filename: str) -> None:
    plt.switch_backend('Agg')
    plt.subplots()
    ax = plt.figure().add_subplot()

    if not chart_type:
        chart_type = DEFAULT_CHART_TYPE
    if chart_type not in CHARTS:
        raise ValueError("Invalid chart type!")
    chart = CHARTS[chart_type]
    min_nonzero_date = find_min_nonzero_date(dfs, 5)
    if not min_nonzero_date:
        min_nonzero_date = find_min_nonzero_date(dfs, 1)
    daterange = combine_date_ranges(dfs)

    for df in dfs:
        county = df.head(1).county.values[0]
        state = df.head(1).state.values[0]

        if min_nonzero_date:
            date_truncated_df = df.loc[df.date >= min_nonzero_date]
            daterange = daterange.loc[lambda d: d >= min_nonzero_date]
        else:
            date_truncated_df = df
        date_truncated_df.set_index("date", inplace=True)
        if "ydata" in chart:
            ydata = chart["ydata"]
        else:
            ydata = chart_type
        data = date_truncated_df[ydata].values
        date = date_truncated_df.index
        plt.gcf().autofmt_xdate()
        ax.plot(date, data, label="{},{}".format(county, state))
    plt.grid(True)
    plt.legend()
    if "chart_title" in chart:
        chart_title = chart["chart_title"]
    else:
        chart_title = chart_type
    plt.title(f"{chart_title}")
    if "ylabel" in chart:
        plt.ylabel(chart["ylabel"])
    else:
        plt.ylabel(chart_type)
    plt.xlabel("Date")
    xtickrange = decimate_ticks(daterange)
    plt.xticks(xtickrange, rotation=90)
    if "yscale" in chart:
        plt.yscale(chart['yscale'])

    plt.savefig(filename)
