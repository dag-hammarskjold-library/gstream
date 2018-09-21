from zipfile import ZipFile
from datetime import timedelta
import urllib.parse, urllib.request
from io import StringIO, BytesIO
import datetime, os, json, hashlib, boto3, botocore
from botocore.exceptions import ClientError
from config import Config
from boto3.dynamodb.conditions import Key, Attr
from tqdm import tqdm
from lxml import etree
from lxml.html.soupparser import fromstring
import sys

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

def update(item_id,undl_link):
    try:
        response = table.update_item(
            Key={
                'checksum': item_id
            },
            UpdateExpression="set undl_link = :u",
            ExpressionAttributeValues={
                ':u': undl_link
            },
            ReturnValues="UPDATED_NEW"
        )
    except ClientError as e:
        print(e.response['Error']['Message'])


session = boto3.Session(aws_access_key_id=Config.AWS_ACCESS_KEY_ID,aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY)
ddb = session.resource('dynamodb',region_name='us-east-1')
table = ddb.Table('gstream')

response = table.scan(
    ProjectionExpression = "checksum, symbol1, undl_link"
)

for item in tqdm(response['Items']):
    try:
        undl_link = item['undl_link']
        pass
    except KeyError:
        resolved_symbol = resolve(item['symbol1'])
        if resolved_symbol:
            update(item['checksum'],resolved_symbol)
    
while 'LastEvaluatedKey' in response:
    response = table.scan(
        ProjectionExpression = "checksum, symbol1, undl_link",
        ExclusiveStartKey = response['LastEvaluatedKey']
    )

    for item in tqdm(response['Items']):
        try:
            undl_link = item['undl_link']
            pass
        except KeyError:
            resolved_symbol = resolve(response['symbol1'])
            if resolved_symbol:
                update(item['checksum'])