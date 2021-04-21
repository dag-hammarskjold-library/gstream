import boto3

class Config(object):
    client = boto3.client('ssm')
    api_secrets = client.get_parameter(Name='gdoc-api-secrets')['Parameter']['Value']
    duty_stations = [
        ('New York', 'NY'),
        ('Geneva', 'GE')
    ]