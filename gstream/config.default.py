import datetime, os

class Config:
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

    # The username and password entries will be provided by the gDoc team.
    STATIC_PARAMS = {
        'APIUserNAme': 'API username',
        'APIPassword': 'API password',
        'UserName': 'username',
        'Password': 'password',
        'AppName': 'gDoc',
        'DstOff': 'Y',
        'LocalDate': datetime.datetime.now().__str__(),
        'DownloadFiles': 'Y',
        'Odsstatus': 'Y'
    }

    BUCKET="mybucket"