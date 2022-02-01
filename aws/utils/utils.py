import os, json, yaml, boto3
from yaml.loader import SafeLoader

from dotenv import load_dotenv
from os.path import join, dirname


# load aws credentials from .env file
def loadAwsCredentials(g):
    aws_credentials = g['config']['credentials']['file']
    dotenv_path = g['root_path'] + aws_credentials
    load_dotenv(dotenv_path)
    
    changes = {}
    changes['region'] = os.getenv('AWS_REGION')
    updateDeployed(g, changes)

    return boto3.session.Session(
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        aws_session_token=os.getenv('AWS_SESSION_TOKEN'),
        region_name=os.getenv('AWS_REGION')
    )

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
    deployed = {}

    # open yaml config and load as dict
    with open(filepath) as file:
        config = yaml.load(file, Loader=SafeLoader)
        
    output_file = config['output']['file']
    if os.path.exists(output_file):
        with open(output_file, "r") as file:
            deployed = dict(json.load(file))
    
    return config, deployed
    
# Copy keys and values from changes dict to deployed dict and write to output file
def updateDeployed(g, changes):
    deployed = g['deployed']
    config = g['config']
    
    deployed.update(changes)
    
    output_file = config['output']['file']
    with os.fdopen(os.open(output_file, os.O_WRONLY | os.O_CREAT), "w+") as handle:
        handle.write(json.dumps(deployed, indent=4, sort_keys=True)) 

# Delete output file if it exists
def clearDeployed(g):
    config = g['config']

    file = config['output']['file']
    if os.path.exists(file):
        os.remove(file)

# Scan live infrastructure and return dictionary of values
def scanInfra(g):
    return {}

# Delete all resources and update 'deployed' file
def teardown(g):
    deployed = g['deployed']
    region = g['deployed']['region']

    os.system("python vpc_destroy.py --services ec2 --region " + region + " --vpc_id " + deployed['vpc_id'])
    clearDeployed(g)

