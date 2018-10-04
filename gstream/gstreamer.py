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
import sys, logging, socket

def resolve(symbol):
    resolver_endpoint = 'https://9inpseo1ah.execute-api.us-east-1.amazonaws.com/prod/symbol/'
    try:
        response = urllib.request.urlopen(resolver_endpoint + symbol)
        this_data = response.read()
        root = fromstring(this_data).find('.//a[@id="link-lang-select"]')
        undl_link = root.attrib['href']
        return undl_link
    except urllib.error.HTTPError:
        # nothing found
        return None

session = boto3.Session(aws_access_key_id=Config.AWS_ACCESS_KEY_ID,aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY)
ddb = session.resource('dynamodb',region_name='us-east-1')
table = ddb.Table('gstream')
s3 = boto3.resource('s3')
bucket = Config.BUCKET
logging.basicConfig(filename="gstream.log",level=logging.INFO)

DUTY_STATIONS = {
    'NY':('NY','New York'),
    'GE':('GE','Geneva')
}

params = Config.PARAMS

# check argv to see if I passed a date
try:
    d,m,y = sys.argv[1].split('/')
    params['DateFrom'] = datetime.date(int(y),int(m),int(d)).__str__()
    params['DateTo'] = params['DateFrom']
except IndexError:
    pass

#static_params = Config.PARAMS
#static_params['DownloadFiles'] = 'N'

host = 'https://conferenceservices.un.org/ICTSAPI/ODS/GetODSDocumentsV2?'

logging.info("%s - PROCESS STARTED" % datetime.datetime.now().__str__())

for ds in DUTY_STATIONS:
    s,l = DUTY_STATIONS[ds]
    print("Processing %s" % l)
    logging.info('Downloading %s files for %s' % (l,params['DateFrom']))
    params['DutyStation'] = ds
    url = host + urllib.parse.urlencode(params)
    print(url)
    try:
        zipfile = ZipFile(BytesIO(urllib.request.urlopen(url, timeout=180).read()))
    except socket.timeout:
        logging.error("%s - PROCESS TIMED OUT. You will want to run this process again.")
        raise

    logging.debug(zipfile.namelist())
    if 'export.txt' in zipfile.namelist():
        metadata = zipfile.open('export.txt')
        results = json.load(metadata)
        print("Processing %s result(s) from %s" % (len(results), ds))
        logging.info("Processing %s result(s) from %s" % (len(results), l))
        output = []
        for result in tqdm(results):
            this_odsno = str(result['odsNo'])
            try:
                matching_file = [n for n in zipfile.namelist() if this_odsno + '.pdf' in n][0]
            except IndexError:
                logging.info("Hmm...couldn't find %s in export.txt" % this_odsno)
                logging.info("Tried to process from %s and looked for files from %s" % (result, zipfile.namelist()))
                continue
            checksum = hashlib.md5(zipfile.open(matching_file).read()).hexdigest()
            try:
                s3.Object(bucket, checksum).load()
            except botocore.exceptions.ClientError as e:
                s3object = s3.Object(bucket, checksum)
                s3object.put(Body=zipfile.open(matching_file).read(),ContentType='application/pdf')
            result['checksum'] = checksum
            result['dutyStation'] = params['DutyStation']
            this_undl_link = resolve(result['symbol1'])
            if this_undl_link:
                result['undl_link'] = this_undl_link
            #make sure there are no empty key values
            for k in result:
                result[k] = str(result[k])
                if ('Date' in k or k == 'embargo'):
                    # we have a date
                    d,m,y = result[k].split('/')
                    this_d = int(datetime.date(int(y),int(m),int(d)).__str__().replace('-',''))
                    result[k] = this_d
                if len(str(result[k])) == 0:
                    result[k] = "_"

            # put the item in the ddb if it doesn't exist already
            try:
                table.put_item(
                    Item=result,
                    Expected={
                        'checksum':{'Exists':False}
                    }
                )
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    raise

logging.info("%s - PROCESS FINISHED" % datetime.datetime.now().__str__())