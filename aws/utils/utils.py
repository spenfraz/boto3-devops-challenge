import os, json, yaml, boto3, sys
from pprint import pprint
from yaml.loader import SafeLoader
from dotenv import load_dotenv


# load aws credentials from .env file
def loadAwsCredentials(root_path, config):
    aws_credentials = config['credentials']['file']
    dotenv_path = root_path + aws_credentials
    load_dotenv(dotenv_path)
    
    region = os.getenv('AWS_REGION')

    session = boto3.session.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        aws_session_token=os.getenv('AWS_SESSION_TOKEN'),
        region_name=os.getenv('AWS_REGION')
    )
    iam_user = session.client('iam').get_user()

    return session, region, iam_user['User']['UserName']

# Open the json file and return contents as dictionary
def readFromFile(full_path):
    filepath = full_path
        
    json_content = {}
    
    with open(filepath) as json_file:
        json_content = json.load(json_file)
    return json.dumps(json_content)

# Open the yaml file and save it to config dict with key 'server'.
# Open the output json file (if exists) and save contents to deployed dict.
def readFromConfig(path, configfile):
    filepath = path + configfile

    config = {}

    # open yaml config and load as dict
    with open(filepath) as file:
        config = yaml.load(file, Loader=SafeLoader)
    
    return config

# Delete output file if it exists
def clearDeployed(g):
    config = g['config']

    file = config['output']['file']
    if os.path.exists(file):
        os.remove(file)
    
# Copy keys and values from changes dict to deployed dict and write to output file
def updateDeployed(g, changes):
    deployed = g['deployed']
    deployed['region'] = g['config']['region']
    config = g['config']
    
    deployed.update(changes)
    
    clearDeployed(g)

    output_file = config['output']['file']
    with os.fdopen(os.open(output_file, os.O_WRONLY | os.O_CREAT), "w+") as handle:
        handle.write(json.dumps(deployed, indent=4, sort_keys=True))
    
    return deployed

# scan vpc resources and update output file
def scanVPCAndUpdateDeployed(g):
    pass

