from flask import Flask, render_template, jsonify, request, redirect
from datetime import timedelta
from gdoc_api import Gdoc
import datetime
import requests, re, ssl, json
import boto3
from gstream.config import Config
from dlx import DB as DLX
from dlx.file import File as DLXFile
from dlx.marc import BibSet, Query

secrets = json.loads(Config.api_secrets)
app = Flask(__name__)
db_client = DLX.connect(Config.connect_string, database=Config.dbname)

class MetadataObject(object):
    def __init__(self, metadata):
        # metadata that's common to all of the files in the object
        # title is here until DGACM starts providing translated titles
        self.agendaNo = metadata['agendaNo']
        self.jobId = metadata['jobId']  # English jobid only
        self.symbol1 = metadata['symbol1']
        self.symbol2 = metadata['symbol2']
        self.area = metadata['area']
        self.sessionNo = metadata['sessionNo']
        self.distributionType = metadata['distributionType']
        self.title = metadata['title']
        self.files = []
        self.links = []

    def __str__(self):
        return str({
            'agendaNo': self.agendaNo,
            'jobId': self.jobId,
            'symbol1': self.symbol1,
            'symbol2': self.symbol2,
            'area': self.area,
            'sessionNo': self.sessionNo,
            'distributionType': self.distributionType,
            'title': self.title,
            'files': self.files
        })

class FileObject(object):
    def __init__(self, metadata):
        #self.checksum = metadata['checksum']
        self.embargo = metadata['embargo']
        self.languageId = metadata['languageId']
        self.odsNo = metadata['jobId']
        self.registrationDate = metadata['registrationDate']
        self.officialSubmissionDate = metadata['officialSubmissionDate']


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
    #g.set_param('Odsstatus', 'N')
    g.set_param('DownloadFiles', 'N')

    next_date = date_obj.date() + datetime.timedelta(days=1)
    if next_date > today:
        next_date = None
    prev_date = date_obj.date() - datetime.timedelta(days=1)

    symbol_objects = {}
    for d in g.data:
        m = MetadataObject(d)
        f = FileObject(d)
        if m.symbol1 not in symbol_objects:
            m.files.append(f)
            symbol_objects[m.symbol1] = m
        else:
            symbol_objects[m.symbol1].files.append(f)

    for s in symbol_objects:
        symbol2 = symbol_objects[s].symbol2
        if len(symbol2) > 0:
            returned_files = DLXFile.find({'identifiers': [{'type': 'symbol', 'value': s}, {'type': 'symbol', 'value': symbol2}], 'languages': ['EN']})
        else:
            returned_files = DLXFile.find({'identifiers': [{'type': 'symbol', 'value': s}], 'languages': ['EN']})
        for f in returned_files:
            symbol_objects[s].links.append(('PDF', f"https://{f.uri}"))

        query = Query.from_string(f'191__a:{s}')
        res = list(BibSet.from_query(query.compile()))
        try:
            my_s = res[0].get_value('191','a')
            symbol_objects[s].links.append(('UNDL', f"{Config.dlx_endpoint}records/bibs/{res[0].id}"))
        except:
            pass

    return render_template('index.html', duty_stations=Config.duty_stations, data=symbol_objects, date=date, duty_station=duty_station, next_date=next_date, prev_date=prev_date)