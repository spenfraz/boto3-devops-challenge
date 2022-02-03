import os, time
import traceback, sys
from pprint import pprint
from operator import attrgetter

from aws.resources.iam.iam import createInstanceProfile
from aws.resources.vpc.vpc import getSubnetsByTag
from aws.resources.ec2.userdata.userdata import USERDATA_SCRIPT

from aws.utils.utils import updateDeployed

def getRunningInstances(g):
    ec2_client = g['session'].client('ec2')
    ec2_resource = g['session'].resource('ec2')

    # check for existing ec2 instances
    # get instances that are running in vpc
    filters = [
        {"Name": "instance-state-name", "Values": ["running"]},
        {"Name": "vpc-id", "Values": [g['deployed']['vpc_id']]},
    ]

    # add instances to list
    ec2_instances = ec2_client.describe_instances(Filters=filters)
    instance_ids = []
    for reservation in ec2_instances["Reservations"]:
        instance_ids += [instance["InstanceId"] for instance in reservation["Instances"]]
    
    return ec2_resource.instances.filter(
        InstanceIds=instance_ids,
    ), len(instance_ids)

def updateEC2Deployed(g, instances):
    config = g['config']
    deployed = g['deployed']
    ec2_client = g['session'].client('ec2')
    changes = {}

    path = config['ssh_keys']['directory'] + os.sep
    keyfile = config['server']['admin']['ssh_key']['name']
    admin_user = config['server']['admin']['login']
            
    # iterate over ec2 instances and write ec2 instance public dns, ssh, subnet and volume info to output file
    changes['ec2_instances'] = []
    for inst in instances:
        ec2data = {}
        ec2data['public_dns'] = inst.public_dns_name
        ec2data['ssh'] = []
        ec2data['ssh'].append('ssh -i ' + path + keyfile + " " + admin_user + '@' + inst.public_dns_name)
        for users in g['config']['server']['users']:
            ec2data['ssh'].append('ssh -i ' + path + users['login'] + '-key.pem' + " " + users['login'] + '@' + inst.public_dns_name)
        changes['ec2_instances'].append(ec2data)

        changes['subnets'] = {}
        # iterate over subnets and update output file volume data per instance
        for sn_id in deployed['subnets']:
            changes['subnets'][sn_id] = {}
            if sn_id == inst.subnet_id:
                changes['subnets'][sn_id][inst.id] = {}
                changes['subnets'][sn_id][inst.id]['public_dns'] = inst.public_dns_name
                
                for v in inst.volumes.all():
                    volume_details = ec2_client.describe_volumes(
                        VolumeIds=[
                            v.volume_id
                        ]
                    )
                    changes['subnets'][sn_id][inst.id][v.volume_id] = []
                    vdata = {}
                    vdata['size'] = v.size
                    vdata['type'] = v.volume_type
                    vdata['device'] = volume_details['Volumes'][0]['Attachments'][0]['Device']
                    vdata['state'] = volume_details['Volumes'][0]['Attachments'][0]['State']
                    changes['subnets'][sn_id][inst.id][v.volume_id].append(vdata)
        
        updateDeployed(g, changes)

# Create EC2 instances from config dict and write changes to output file
def createEc2Instances(g):
    config = g['config']
    deployed = g['deployed']
    ec2_client = g['session'].client('ec2')

    instances, instance_count = getRunningInstances(g)
    max_count = g['config']['server']['max_count']
    # check that server.max_count is not already exceeded
    if max_count <= instance_count:
        print('max_count: ' + str(max_count) + ' for ec2 instances has already been reached ' + '(' + str(instance_count) + ')')
        updateEC2Deployed(g, instances)
        print('exiting...')
        sys.exit(1)

    volumes = config['server']['volumes']
    MODIFIED_USERDATA_SCRIPT = USERDATA_SCRIPT
    
    # volume configuration for ec2 instance(s)
    blockDeviceMappings = []
    for volume in volumes:
        block_device = {}
        device_type = {}
        block_device['DeviceName'] = volume['device']
        device_type['DeleteOnTermination'] = True
        device_type['VolumeSize'] = volume['size_gb']
        #device_type['VolumeType'] = volume['type']
        block_device['Ebs'] = device_type
        blockDeviceMappings.append(block_device)
        
        # mount non / volumes
        if not volume['mount'] == '/':
            # edit userdata script to make call to bash function
            # TODO: utilize more robust templating instead
            MODIFIED_USERDATA_SCRIPT += "\n" +  "formatAndMount \"" + volume['device'] + "\" \"" + volume['type'] + "\" \"" + volume['mount'] + "\""
        
    # create admin user
    admin_user = config['server']['admin']['login']
    # edit userdata script to make call to bash function
    # TODO: utilize more robust templating instead
    MODIFIED_USERDATA_SCRIPT += "\n" + "createAdminUser \"" + admin_user + "\""

    # create non-admin users
    for user in config['server']['users']:
        # edit userdata script to make call to bash function
        # TODO: utilize more robust templating instead
        MODIFIED_USERDATA_SCRIPT += "\n" + "createRegularUser \"" + user['login'] + "\""
    
    # make user specific shared (read) directories on mounted volumes 
    for user in config['server']['users']:
        for volume in volumes:
            if volume['mount'] != '/':
                # edit userdata script to make call to bash function
                # TODO: utilize more robust templating instead
                MODIFIED_USERDATA_SCRIPT += "\n" + "makeSharedDirectory \"" + user['login'] + "\" \"" + volume['mount'] + "\" &"
    
    # give sudo to users configured to have it
    for user in config['server']['users']:
        if user['can_sudo']:
            MODIFIED_USERDATA_SCRIPT += "\n" + "giveUserSudo \"" + user['login'] + "\" &"

    iam_instance_profile = createInstanceProfile(g)
    
    subnet_id = getSubnetsByTag(g)[0].id

    print('getting ami image id')
    image_id = getLatestAMI(g)

    if image_id:
        print('creating ec2 instance(s)')
        while(True):
            try:
                reservation = ec2_client.run_instances(
                    KeyName=config['server']['admin']['ssh_key']['name'],
                    InstanceType=config['server']['instance_type'],
                    ImageId=image_id,
                    MinCount=config['server']['min_count'],
                    MaxCount=config['server']['max_count'],
                    UserData=MODIFIED_USERDATA_SCRIPT,
                    IamInstanceProfile=iam_instance_profile,
                    BlockDeviceMappings=blockDeviceMappings,
                    NetworkInterfaces=[
                        {
                            "DeviceIndex": 0,
                            "Groups": [deployed['sg_id']],
                            'AssociatePublicIpAddress': True,
                            'SubnetId': subnet_id
                        }
                    ]
                )
                break
            except Exception as e:
                print()
                print(traceback.format_exception(None, # <- type(e) by docs, but ignored 
                                     e, e.__traceback__),
                        file=sys.stderr, flush=True)
                print()
                print('See: https://forums.aws.amazon.com/thread.jspa?messageID=593651')
                print('\"The delay you are seeing for AWS::IAM::InstanceProfile is intended; this is to account for and ensure the IAM service has propagated the profile fully. We do apologize for any inconvenience this may cause.\"')
                print('Retrying...')
                print()
                time.sleep(5)

        instance_ids = []
        for inst in reservation['Instances']:
            instance_ids.append(inst['InstanceId'])
        
        # wait for ec2 instances to be ready/running
        waiter = ec2_client.get_waiter('instance_running')
        waiter.wait(InstanceIds=instance_ids)
        
        instances, instance_count = getRunningInstances(g)
        updateEC2Deployed(g, instances)

    else:
        print('ImageId not found. Check filter values.')
        exit()

# Get newest AMI filtered on config values
def getLatestAMI(g):
    config = g['config']

    images = g['session'].resource('ec2').images.filter(
        Filters=[
            {
                'Name': 'name',
                'Values': [config['server']['ami_type']+'*']
            },
            {
                'Name': 'architecture',
                'Values': [config['server']['architecture']]
            },
            {
                'Name': 'virtualization-type',
                'Values': [config['server']['virtualization_type']]
            },
            {
                'Name': 'root-device-name',
                'Values': [config['server']['volumes'][0]['device']]
            },
            {
                'Name': 'root-device-type',
                'Values': [config['server']['root_device_type']]
            },
            {
                'Name': 'owner-alias',
                'Values': ['amazon']
            }
        ]
    )
    image_details = sorted(list(images), key=attrgetter('creation_date'), reverse=True)
    #print(f'Latest AMI: {image_details[0].id}')
    if image_details[0].id:
        return image_details[0].id
    else: return False