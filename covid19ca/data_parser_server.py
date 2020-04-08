import json
import os
import uuid

from flask import Flask, jsonify, url_for
from flask import render_template, request
from flask.json import loads
from werkzeug.exceptions import abort

from covid19ca import ca_data_parser

app = Flask(__name__)

STATIC_FOLDER = os.path.join('static')

with open(os.path.join(STATIC_FOLDER, 'county_state_mapping')) as f:
    state_county_dict = json.load(f)


class NoDataAvailableException(Exception):
    pass


def render_graph(counties):
    logger = app.logger
    dfts = ca_data_parser.get_county_data(counties)
    if not dfts:
        raise NoDataAvailableException("No counties matched in data!")

    filename = f"{uuid.uuid4()}.png"
    full_filename = os.path.join(STATIC_FOLDER, filename)
    ca_data_parser.plot_counties(dfts, full_filename)
    logger.debug("rendered chart to %s", full_filename)
    return filename


MAX_COUNTIES = 100


@app.errorhandler(413)
def request_too_large(e):
    return jsonify(error=f"Too many counties (max {MAX_COUNTIES})"), 413


@app.errorhandler(400)
def bad_request(e):
    return jsonify(error=f"Invalid request parameters specified."), 400


def get_counties(req_json):
    counties = []
    if type(req_json) is not list:
        raise TypeError("Invalid outer type!")
    for s in req_json:
        if type(s) != str:
            raise TypeError("Invalid inner type!")
        o = loads(s)
        if "state" not in o or "county" not in o:
            raise TypeError("Invalid county dict!")
        counties.append(o)
    return counties


@app.route('/graph', methods=['GET', 'POST'])
def handle_graph():
    if not request.json:
        return abort(400)
    logger = app.logger

    if len(request.json) > MAX_COUNTIES:
        return abort(413)

    try:
        counties = get_counties(request.json)
        logger.debug(counties)
    except TypeError:
        logger.warning("Invalid type encountered while unpacking json params!")
        return abort(400)

    try:
        filename = render_graph(counties)
    except NoDataAvailableException:
        logger.warning("No data found for specified counties.")
        return "", 204

    return jsonify({
        "covid_graph": url_for("static", filename=filename)
    })


@app.route('/')
def index():
    return render_template('index.html', county_states=state_county_dict, max_counties=MAX_COUNTIES)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
