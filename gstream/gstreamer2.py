from zipfile import ZipFile
from datetime import timedelta
from io import StringIO, BytesIO
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from tqdm import tqdm
from lxml import etree
from lxml.html.soupparser import fromstring
import sys, logging, socket
import urllib.parse, urllib.request
import datetime, os, json, hashlib, boto3, botocore

def download_to_s3(bucket,filename,body):
    logging.info("%s - Saving %s/%s" % (datetime.datetime.now().__str__(),bucket,filename) )
    try:
        s3.Object(bucket, filename).load()
    except botocore.exceptions.ClientError as e:
        s3object = s3.Object(bucket, filename)
        s3object.put(Body=body)

def store_to_dynamodb(item):
    logging.info("%s - STORE TO DDB PROCESS STARTED" % datetime.datetime.now().__str__())
    # put the item in the ddb if it doesn't exist already
    try:
        table.put_item(
            Item=item,
            Expected={
                'checksum':{'Exists':False}
            }
        )
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise

def get_symbol_list(ds,query_date):
    '''
    This portion of the script will find only the list of newly issued files.
    The idea here is to avoid timeouts, so we're chunking things up into smaller
    batches.
    '''
    logging.info("%s - FILE LIST PROCESS STARTED FOR %s on %s" % (datetime.datetime.now().__str__(),ds,query_date))
    return_symbols = []
    short_name, long_name = Config.DUTY_STATIONS[ds]
    Config.DYNAMIC_PARAMS['DutyStation'] = ds
    Config.STATIC_PARAMS['DownloadFiles'] = 'N'
    Config.DYNAMIC_PARAMS['DateFrom'] = query_date
    Config.DYNAMIC_PARAMS['DateTo'] = query_date
    url = Config.GDOC_HOST + urllib.parse.urlencode(Config.STATIC_PARAMS) + '&' + urllib.parse.urlencode(Config.DYNAMIC_PARAMS)
    # unclear if this should be enclosed in a try/except statement...
    # or what we would do about an issue like a timeout
    zipfile = ZipFile(BytesIO(urllib.request.urlopen(url, timeout=60).read()))
    if 'export.txt' in zipfile.namelist():
        # we're really only interested here in the list of symbols with files issued
        # on the specified date. This file could be empty...
        metadata = zipfile.open('export.txt')
        results = json.load(metadata)
        for result in results:
            this_symbol = result['symbol1']
            symbol_set = (ds,query_date,this_symbol)
            if symbol_set not in return_symbols:
                return_symbols.append(symbol_set)

    logging.info('%s - Found %s symbols from %s with files re/issued on %s' % (datetime.datetime.now().__str__(),len(return_symbols),ds,query_date) )
    return return_symbols     

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

# Init
session = boto3.Session(
    aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY
)
s3 = boto3.resource('s3')
bucket = Config.BUCKET
logging.basicConfig(
    filename="gstream.log",
    level=logging.DEBUG
)

# check argv to see if I passed a date
query_date = Config.DYNAMIC_PARAMS['DateFrom']
try:
    d,m,y = sys.argv[1].split('/')
    query_date = datetime.date(int(y),int(m),int(d)).__str__()
except IndexError:
    pass

# get a list of the symbols for this particular date and all duty stations
symbol_list = {}
for ds in Config.DUTY_STATIONS:
    symbol_list[ds] = get_symbol_list(ds,query_date)

# Now we can try to get the files and metadata. This should minimize the chance
# of timeouts that can occur when lots of files are issued in a day.
for ds in symbol_list:
    Config.STATIC_PARAMS['DownloadFiles'] = 'Y'
    for (this_ds,this_date,this_symbol) in tqdm(symbol_list[ds]):
        Config.DYNAMIC_PARAMS['DutyStation'] = this_ds
        Config.DYNAMIC_PARAMS['DateFrom'] = this_date
        Config.DYNAMIC_PARAMS['DateTo'] = this_date
        Config.DYNAMIC_PARAMS['Symbol'] = this_symbol
        url = Config.GDOC_HOST + urllib.parse.urlencode(Config.STATIC_PARAMS) + '&' + urllib.parse.urlencode(Config.DYNAMIC_PARAMS_NO_SYMBOl) + "&Symbol=%s" % this_symbol
        print(url)
        zipfile = ZipFile(BytesIO(urllib.request.urlopen(url, timeout=60).read()))
        if 'export.txt' in zipfile.namelist():
            # Now we get all of the files associated with the symbol in question
            metadata = zipfile.open('export.txt')
            results = json.load(metadata)
            logging.info('%s - Found %s files for %s on %s.' % (datetime.datetime.now().__str__(),len(results),this_symbol,this_date))
            for result in results:
                matching_file = [n for n in zipfile.namelist() if this_odsno + '.pdf' in n][0]
                checksum = hashlib.md5(zipfile.open(matching_file).read()).hexdigest()
                body = zipfile.open(matching_file).read()
                # try saving it to S3; the method will skip duplicates
                download_to_s3(Config.BUCKET,checksum,body)
                # next we will try to write the data to DDB
                result['checksum'] = checksum
                result['dutyStation'] = this_ds
                # first we need to try resolving the symbol
                undl_link = resolve(this_symbol)
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
            