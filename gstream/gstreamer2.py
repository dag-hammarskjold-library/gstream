from zipfile import ZipFile
from datetime import timedelta
import urllib.parse, urllib.request
from io import StringIO, BytesIO
import datetime, os, json, hashlib, boto3, botocore
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from tqdm import tqdm
from lxml import etree
from lxml.html.soupparser import fromstring
import sys, logging

'''
This is a rewrite of gstreamer.py to refactor it into something more reusable and to account 
for some inconsistencies in data handling.
'''

def get_files_and_metadata(url):
    try:
        zipfile = ZipFile(BytesIO(urllib.request.urlopen(url, timeout=180).read()))
    except socket.timeout:
        #logging.error("%s - PROCESS TIMED OUT. You will want to run this process again.")
        raise
    return zipfile

def extract_metadata(zipfile):
    # we expect export.txt tp be here
    metadata = zipfile.open('export.txt')
    #results = json.load(metadata)
    return metadata

def write_file_to_s3(bucket, checksum, file_object, content_type):
    try:
        s3.Object(bucket, checksum).load()
    except botocore.exceptions.ClientError:
        s3object = s3.Object(bucket, checksum)
        s3object.put(Body=file_object.read(),ContentType=content_type)

def write_metadata_to_ddb(table, metadata):
    try:
        table.put_item(
            Item=metadata,
            Expected={
                'checksum':{'Exists':False}
            }
        )
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise

def resolve(endpoint, symbol):
    try:
        response = urllib.request.urlopen(endpoint + symbol)
        this_data = response.read()
        root = fromstring(this_data).find('.//a[@id="link-lang-select"]')
        undl_link = root.attrib['href']
        return undl_link
    except urllib.error.HTTPError:
        # nothing found
        return None

#init
session = boto3.Session(aws_access_key_id=Config.AWS_ACCESS_KEY_ID,aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY)
ddb = session.resource('dynamodb',region_name='us-east-1')
table = ddb.Table('gstream')
s3 = boto3.resource('s3')
bucket = Config.BUCKET
logging.basicConfig(filename="gstream.log",level=logging.INFO)

duty_stations = Config.DUTY_STATIONS
params = Config.PARAMS
host = Config.GDOC_HOST
resolver = Config.RESOLVER

try:
    query_date = sys.argv[1]
    params['DateFrom'] = query_date
    params['DateTo'] = query_date
except IndexError:
    pass

logging.info("%s - PROCESS STARTED" % datetime.datetime.now().__str__())

for ds in duty_stations:
    params['DutyStation'] = ds
    url = host + urllib.parse.urlencode(params)
    zipfile = get_files_and_metadata(url)
    results = json.load(zipfile.open('export.txt'))
    for metadata in tqdm(results):
        this_odsno = str(metadata['odsNo'])
        try:
            matching_file = [n for n in zipfile.namelist() if this_odsno + '.pdf' in n][0]
            checksum = hashlib.md5(zipfile.open(matching_file).read()).hexdigest()
            write_file_to_s3(bucket, checksum, zipfile.open(matching_file), 'application/pdf')
        except IndexError:
            checksum = hashlib.md5(str(metadata).encode()).hexdigest()
            
        metadata['checksum'] = checksum
        metadata['dutyStation'] = params['DutyStation']
        this_undl_link = resolve(resolver,metadata['symbol1'])
        if this_undl_link:
            metadata['undl_link'] = this_undl_link
        #make sure there are no empty key values
        # and avoid changing the size of a mutable object while iterating
        delete_keys = []
        change_keys = []
        for k in metadata:
            #print(k,m[k])
            #m[k] = str(m[k])
            if ('Date' in k or k == 'embargo'):
                # we have a date
                d,m,y = metadata[k].split('/')
                this_d = int(datetime.date(int(y),int(m),int(d)).__str__().replace('-',''))
                change_keys.append((k,this_d))
            if len(str(metadata[k])) == 0:
                delete_keys.append(k)
        for k,v in change_keys:
            metadata[k] = v
        for k in delete_keys:
            del metadata[k]
        write_metadata_to_ddb(table,metadata)
    # now what about files with no metadata?