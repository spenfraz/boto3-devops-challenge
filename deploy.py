import os, argparse
from pprint import pprint
from aws.utils.utils import readFromConfig, loadAwsCredentials, clearDeployed
from aws.resources.iam.iam import deleteInstanceProfile
from aws.resources.vpc.vpc import createVPC, teardown
from aws.utils.ssh import createSshKeys, deleteSshKeys, force_admin_pass_change, sendKeys
from aws.resources.ec2.ec2 import createEc2Instances

def run(root_path):
    config = readFromConfig(root_path, args.filename)
    session, region = loadAwsCredentials(root_path, config)

    g = {}
    g['root_path'] = root_path
    g['config'] = config
    g['config']['region'] = region
    g['deployed'] = {}
    g['session'] = session

    print()
    if args.destroy:
        teardown(g)
        deleteInstanceProfile(g)
        deleteSshKeys(g)
        clearDeployed(g)
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
