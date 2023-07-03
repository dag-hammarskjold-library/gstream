import boto3

class Config(object):
    client = boto3.client('ssm')
    api_secrets = client.get_parameter(Name='gdoc-api-secrets')['Parameter']['Value']
    connect_string = client.get_parameter(Name='prodISSU-admin-connect-string')['Parameter']['Value']
    dbname = "undlFiles"
    dlx_endpoint = 'https://metadata.un.org/editor/'
    duty_stations = [
        ('New York', 'NY'),
        ('Geneva', 'GE')
    ]