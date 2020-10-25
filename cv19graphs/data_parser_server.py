import json
import logging
import os
import signal
import uuid
from typing import Mapping, Any, Iterable, List, Union, Tuple, Optional

from flask import Flask, jsonify, url_for
from flask import render_template, request
from werkzeug.exceptions import abort

from cv19graphs import ca_data_parser
from cv19graphs.ca_data_parser import NoDataAvailableException
from cv19graphs.flaskgzip import gzipped

app = Flask(__name__)

STATIC_FOLDER = os.path.join('static')


def load_fips_county_mapping(filename='fips_county_mapping.json') -> Mapping[str, Any]:
    with open(os.path.join(STATIC_FOLDER, filename)) as f:
        return json.load(f)


fips_county_mapping = load_fips_county_mapping()


def sighup_handler(_unused, _unused2) -> None:
    app.logger.info("SIGHUP received, reloading counties and mapping.")
    ca_data_parser.reload_us_counties()
    load_fips_county_mapping()
    app.logger.info("Done.  latest date=%s, counties in mapping=%d",
                    ca_data_parser.latest_date,
                    len(fips_county_mapping.keys()))


signal.signal(signal.SIGHUP, sighup_handler)


def render_graph(counties: Iterable[int], chart: Optional[str]) -> str:
    logger = app.logger
    dfs = ca_data_parser.get_county_data(counties)
    if not dfs:
        raise NoDataAvailableException("No counties matched in data!")

    filename = f"{uuid.uuid4()}.png"
    full_filename = os.path.join(STATIC_FOLDER, filename)
    ca_data_parser.plot_counties(dfs, chart, full_filename)
    logger.info("rendered chart to %s", full_filename)
    return filename


MAX_COUNTIES = 10


@app.errorhandler(413)
def request_too_large(_) -> Tuple[str, int]:
    return jsonify(error=f"Too many counties (max {MAX_COUNTIES})"), 413


@app.errorhandler(400)
def bad_request(_) -> Tuple[str, int]:
    return jsonify(error=f"Invalid request parameters specified."), 400


def get_counties(req_json: List[Union[str, int]]) -> List[int]:
    counties = []
    if type(req_json) is not list:
        raise TypeError(f"Invalid outer type ({type(req_json)})")
    for s in req_json:
        if type(s) == str:
            try:
                counties.append(int(s))
            except ValueError as e:
                raise TypeError(e.args)
        elif type(s) == int:
            counties.append(int(s))
        else:
            raise TypeError(f"Invalid inner type ({type(s)})")
    return counties


@app.route('/graph', methods=['POST'])
def handle_graph() -> Tuple[str, int]:
    if not request.json:
        return abort(400)
    logger = app.logger

    if "counties" not in request.json:
        return abort(400)

    counties_arg = request.json['counties']
    chart = None
    if "chart" in request.json:
        json_chart = request.json['chart']
        if type(json_chart) != str:
            logger.warning("Bad arg type (%s) for chart", type(json_chart))
            return abort(400)
        chart = str(json_chart)

    logger.debug("chart type: %s", chart)

    if len(counties_arg) > MAX_COUNTIES:
        return abort(413)
    if len(counties_arg) == 0:
        logger.warning("No counties in request?")
        return "", 204

    try:
        counties = get_counties(counties_arg)
        logger.debug("counties: %s", counties)
    except TypeError as e:
        logger.warning("Invalid type encountered while unpacking json params: %s", e)
        return abort(400)

    try:
        filename = render_graph(counties, chart)
    except NoDataAvailableException:
        logger.warning("No data found for specified counties.")
        return "", 204

    return jsonify({
        "covid_graph": url_for("static", filename=filename)
    })


@app.route('/')
@gzipped
def index():
    return render_template('index.html',
                           fips_county_mapping=fips_county_mapping,
                           max_counties=MAX_COUNTIES,
                           latest_date=ca_data_parser.latest_date,
                           chart_types=list(ca_data_parser.CHARTS.keys()))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
