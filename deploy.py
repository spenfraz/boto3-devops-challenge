import os, time, argparse
#from pprint import pprint
from aws.utils.utils import readFromConfig, loadAwsCredentials, teardown
from aws.resources.iam.iam import deleteInstanceProfile
from aws.utils.ssh import createSshKeys, deleteSshKeys, force_admin_pass_change, sendKeys
from aws.resources.vpc.vpc import createVPC
from aws.resources.ec2.ec2 import createEc2Instances

def run(root_path):
    config, deployed = readFromConfig(root_path, args.filename)

    g = {}
    g['config'] = config
    g['deployed'] = deployed
    g['root_path'] = root_path

    session = loadAwsCredentials(g)
    #logger = getLogger()
    
    g['session'] = session
    g['ec2_resource'] = session.resource('ec2')
    g['ec2_client'] = session.client('ec2')
    #g['logger'] = logger

    if args.destroy:
        teardown(g)
        deleteInstanceProfile(g)
        deleteSshKeys(g)
    else:
        createSshKeys(g)
        createVPC(g)
        createEc2Instances(g)
        sendKeys(g)
        # expire admin (sudo) password/force change on next login
        for host in g['deployed']['ec2_instances']:
            hostname = host['public_dns']
            force_admin_pass_change(g, hostname)
        
        i = 0
        for cmd in g['deployed']['ec2_instances'][i]['ssh']:
            print(cmd)
            i += 1
        print()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Deploy EC2 instance from yaml file configuration.')
    parser.add_argument('filename',
                    help='A yaml configuration file within the same directory.')
    parser.add_argument("--destroy", action='store_true', help="Teardown all resources.")
    args = parser.parse_args()

    if args.filename:
        path = os.getcwd() + os.sep
        run(path)
