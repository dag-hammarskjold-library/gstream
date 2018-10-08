from flask import Flask, render_template, jsonify, request, redirect
from zipfile import ZipFile
from boto3.dynamodb.conditions import Key, Attr
from io import StringIO, BytesIO
from datetime import timedelta
import datetime, boto3, botocore, os
from .config import Config
import requests, re, ssl

DUTY_STATIONS = {
    'NY':('NY','New York'),
    'GE':('GE','Geneva')
}

session = boto3.Session(aws_access_key_id=Config.AWS_ACCESS_KEY_ID,aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY)
ddb = session.resource('dynamodb',region_name='us-east-1')
table = ddb.Table('gstream')

app = Flask(__name__)

class SymbolObject(object):
    def __init__(self, metadata):
        self.symbol = metadata['symbol1']
        self.metadata = None
        self.files = []
        self.has_older = []
        self.has_newer = []
        self.has_current = []
        try:
            self.undl_link = metadata['undl_link']
        except KeyError:
            self.undl_link = None

class MetadataObject(object):
    def __init__(self, metadata):
        # metadata that's common to all of the files in the object
        # title is here until DGACM starts providing translated titles
        self.agendaNo = metadata['agendaNo']
        self.jobId = metadata['jobId']  # English jobid only
        self.symbol1 = metadata['symbol1']
        # sometimes blank:
        try:
            self.symbol2 = metadata['symbol2']
        except KeyError:
            pass
        self.area = metadata['area']
        # usually blank:
        try:
            self.sessionNo = metadata['sessionNo']
        except KeyError:
            pass
        self.distributionType = metadata['distributionType']
        self.title = metadata['title']
        self.dutyStation = metadata['dutyStation']

class FileObject(object):
    def __init__(self, metadata):
        self.checksum = metadata['checksum']
        self.embargo = metadata['embargo']
        self.languageId = metadata['languageId']
        self.odsNo = metadata['odsNo']
        self.registrationDate = metadata['registrationDate']
        self.officialSubmissionDate = metadata['officialSubmissionDate']

@app.route('/')
def index():
    # default to a date query for today
    today_int = datetime.date.today().__str__().replace('-','')
    query_date = int(request.args.get('date',today_int))
    
    return redirect('./date?date={}'.format(query_date),code=302)

@app.route('/date')
def bydate():
    items = []
    # process args and see what we got:
    # we'll set a default query date for fallback purposes
    query_date = int(datetime.date.today().__str__().replace('-',''))
    returnable_query_date = query_date
    date_range = ""
    if request.args.get('date') is not None:
        query_date = int(request.args.get('date'))
        returnable_query_date = query_date
        print("single date requested: %s" % query_date)
        response = table.query(
            IndexName='embargo-symbol1-index',
            #ProjectionExpression="agendaNo, jobId, embargo, checksum, odsNo, dutyStation, symbol1, symbol2, languageId, registrationDate, officialSubmissionDate",
            KeyConditionExpression=Key('embargo').eq(query_date) & Key('symbol1').between('A','Z')
        )
    elif request.args.get('daterange') is not None:
        date_from,date_to = request.args.get("daterange").split(' - ')
        returnable_query_date = ""
        date_range = " - ".join([date_from, date_to])
        # date range picker is giving DD/MM/YYY so we have to fix that for what we need
        m,d,y = date_from.split('/')
        q_date_from = int(''.join([y,m,d]))
        m,d,y = date_to.split('/')
        q_date_to = int(''.join([y,m,d]))
        print("date range requested: %s - %s" % (q_date_from,q_date_to))
    
        if q_date_from == q_date_to:
            return redirect('./date?date={}'.format(q_date_from),code=302)

        response = table.scan(
            IndexName='embargo-symbol1-index',
            FilterExpression=Key('embargo').between(q_date_from,q_date_to)
        )
    else:
        # neither date nor range were specified, so we're going with the fallback
        print("neither, so falling back to today's date")
        response = table.query(
           IndexName='embargo-symbol1-index',
            #ProjectionExpression="agendaNo, jobId, embargo, checksum, odsNo, dutyStation, symbol1, symbol2, languageId, registrationDate, officialSubmissionDate",
            KeyConditionExpression=Key('embargo').eq(query_date) & Key('symbol1').between('A','Z')
        )


    symbol_objects = []
    items = response['Items']
    for item in items:
        # we can get a good deal of use out of the one item record
        #print(item)
        this_so = SymbolObject(item)
        metadata_object = MetadataObject(item)
        file_object = FileObject(item)
        try:
            symbol_object = list(filter(lambda so:so.symbol == this_so.symbol, symbol_objects))[0]
        except IndexError:
            symbol_object = SymbolObject(item)
            symbol_objects.append(symbol_object)
        
        symbol_object.metadata = metadata_object
        symbol_object.files.append(file_object)

    # Let's get a basic sense of the symbol history
    for mo in symbol_objects:
        response = table.query(
            IndexName='symbol1-index',
            ProjectionExpression="embargo, checksum, odsNo, dutyStation, symbol1, languageId, registrationDate, officialSubmissionDate",
            KeyConditionExpression=Key('symbol1').eq(mo.symbol)
        )
        items = response['Items']
        for item in items:
            fo = FileObject(item)
            if fo.embargo < query_date:
                mo.has_older.append(fo.languageId)
            if fo.embargo > query_date:
                mo.has_newer.append(fo.languageId)

        for f in mo.files:
            mo.has_current.append(f.languageId)

    #return render_template('index.html')
    deploy_context = os.environ.get("DEPLOY_CONTEXT","/")
    return render_template('index.html',results={'metadata_objects':symbol_objects,'query_date':returnable_query_date,'date_range':date_range},deploy_context=deploy_context)

#@app.route('/symbol/', defaults={'search_string': ''})
#@app.route('/symbol/<path:search_string>')
@app.route('/symbol')
def symbol():
    '''
    We want to be able to get the metadata/file history for a particular symbol or the matches
    generated by a partial symbol search. We also want to know if it's in the UNDL already, 
    and which files are already attached.
    '''
    deploy_context = os.environ.get("DEPLOY_CONTEXT","/")
    search_string = request.args.get('symbol','A/73/295')
    response = table.query(
        IndexName='symbol1-index',
        #ProjectionExpression="embargo, checksum, odsNo, dutyStation, symbol1, languageId, registrationDate, officialSubmissionDate",
        KeyConditionExpression=Key('symbol1').eq(search_string)
    )
    items = response['Items']
    if len(items) > 0:
        # All of these belong to the same symbol, so we just should create the object from the first 
        # in the list, then iterate through the rest and append the file-only metadata
        symbol_object = SymbolObject(items[0])
        symbol_object.metadata = MetadataObject(items[0])
        for item in items:
            symbol_object.files.append(FileObject(item))

        return render_template('symbol.html', results=symbol_object, deploy_context=deploy_context)
    else:
        return jsonify('Unable to find a symbol in the database that matches your query.')

@app.route('/s3resolve')
def s3resolve():
    '''
    This function is necessary to match up a checksum, which is our unique id in Dynamo DB, 
    to a file in S3. Because we can receive metadata with no files, we want to avoid making 
    dead links.
    '''
    checksum = request.args.get('checksum',None)
    bucket = Config.BUCKET
    s3 = session.resource('s3')
    if checksum is not None:
        try:
            s3.Object(bucket,checksum).load()
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                return jsonify('The object does not exist')
            else:
                return jsonify(e)
        else:
            url = 'https://s3.amazonaws.com/{}/{}'.format(bucket,checksum)
            return jsonify({'url':url})
    else:
        return jsonify('No identifier was specified. Please include a checksum as your query argument.')