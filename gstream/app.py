from flask import Flask, render_template, jsonify, request, redirect
from datetime import timedelta
from gdoc_api import Gdoc
import datetime
import requests, re, ssl, json
import boto3
from gstream.config import Config

secrets = json.loads(Config.api_secrets)

app = Flask(__name__)

@app.route('/')
def index():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    date = str(request.args.get('date',yesterday))
    date_obj = datetime.datetime.strptime(date, '%Y-%m-%d')
    duty_station = request.args.get('dutyStation', 'NY')

    g = Gdoc(username=secrets["username"], password=secrets["password"])
    

    g.set_param('dutyStation', duty_station)
    g.set_param('dateFrom', date)
    g.set_param('dateTo', date)
    g.set_param('includeFiles', 'false')

    next_date = date_obj.date() + datetime.timedelta(days=1)
    if next_date > today:
        next_date = None
    prev_date = date_obj.date() - datetime.timedelta(days=1)

    return render_template('index.html', duty_stations=Config.duty_stations, data=g.data, date=date, duty_station=duty_station, next_date=next_date, prev_date=prev_date)