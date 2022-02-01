import os, time
import traceback, sys
from pprint import pprint
from operator import attrgetter

from aws.resources.iam.iam import createInstanceProfile
from aws.resources.ec2.userdata.userdata import USERDATA_SCRIPT

from aws.utils.utils import updateDeployed


# Create EC2 instances from config dict and write changes to output file
def createEc2Instances(g):
    changes = {}
    config = g['config']
    deployed = g['deployed']
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')

    # Add inbound security group rule for ssh
    sg = ec2_resource.SecurityGroup(deployed['sg_id'])
    if sg.ip_permissions:
        sg.revoke_ingress(IpPermissions=sg.ip_permissions)
    response = sg.authorize_ingress(
        IpPermissions=[
            {
                "FromPort": 22,
                "ToPort": 22,
                "IpProtocol": "tcp",
                "IpRanges": [
                    {"CidrIp": "0.0.0.0/0", "Description": "internet"},
                ],
            }
        ]
    )

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

        if not volume['mount'] == '/':
            MODIFIED_USERDATA_SCRIPT += "\n" +  "formatAndMount \"" + volume['device'] + "\" \"" + volume['type'] + "\" \"" + volume['mount'] + "\""
        
    
    admin_user = config['server']['admin']['login']
    MODIFIED_USERDATA_SCRIPT += "\n" + "createAdminUser \"" + admin_user + "\""

    for user in config['server']['users']:
        MODIFIED_USERDATA_SCRIPT += "\n" + "createRegularUser \"" + user['login'] + "\""

    
    iam_instance_profile = createInstanceProfile(g)
    
    # if using a default vpc, just grab first subnet in deployed list
    subnet_id = None
    if g['config']['vpc']['use_default_vpc']:
        subnet_id = list(deployed['subnets'].keys())[0]
    # if using custom vpc, filter subnet by tag Name
    else:
        subnet_filters = []
        for _tag in g['config']['server']['subnet']['tags']:
            tag_filter = {}
            tag_filter['Name'] = 'tag:' +_tag['key']
            tag_filter['Values'] = []
            tag_filter['Values'].append(_tag['value'])
            subnet_filters.append(tag_filter)
        #filters = [{'Name': 'tag:Name', 'Values':['fetch-devops-challenge-subnet-1']}]
        subnet = list(ec2_resource.subnets.filter(Filters=subnet_filters))[0]
        subnet_id = subnet.id

    image_id = getLatestAMI(g)
    if image_id:
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
                #print(traceback.format_exception(None, # <- type(e) by docs, but ignored 
                #                     e, e.__traceback__),
                #        file=sys.stderr, flush=True)
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

        instances = ec2_resource.instances.filter(
            InstanceIds=instance_ids,
        )

        path = config['ssh_keys']['directory'] + os.sep
        keyfile = config['server']['admin']['ssh_key']['name']
        admin_user = config['server']['admin']['login']
        # print ssh login commands for users
        '''
        for inst in instances:
            print()
            print('ssh -i ' + './' + path + keyfile + " " + admin_user + '@' + inst.public_dns_name)
            for users in g['config']['server']['users']:
                print('ssh -i ' + './' + path + users['login'] + '-key.pem' + " " + users['login'] + '@' + inst.public_dns_name)
        '''
        # iterate over ec2 instances and write state to output file
        deployed['ec2_instances'] = []
        for inst in instances:
            ec2data = {}
            ec2data['public_dns'] = inst.public_dns_name
            ec2data['ssh'] = []
            ec2data['ssh'].append('ssh -i ' + path + keyfile + " " + admin_user + '@' + inst.public_dns_name)
            for users in g['config']['server']['users']:
                ec2data['ssh'].append('ssh -i ' + path + users['login'] + '-key.pem' + " " + users['login'] + '@' + inst.public_dns_name)
            deployed['ec2_instances'].append(ec2data)
            #pprint(inst.block_device_mappings)
            #volumes = ec2_client.describe_instance_attribute(
            #    InstanceId=inst.id,
            #    Attribute='blockDeviceMapping')

            # iterate over subnets in output file and fill in extra state info
            for sn_id in deployed['subnets']:
                if sn_id == inst.subnet_id:
                    deployed['subnets'][sn_id][inst.id] = {}
                    deployed['subnets'][sn_id][inst.id]['public_dns'] = inst.public_dns_name
                    
                    for v in inst.volumes.all():
                        volume_details = ec2_client.describe_volumes(
                            VolumeIds=[
                                v.volume_id
                            ]
                        )
                        deployed['subnets'][sn_id][inst.id][v.volume_id] = []
                        vdata = {}
                        vdata['size'] = v.size
                        vdata['type'] = v.volume_type
                        vdata['device'] = volume_details['Volumes'][0]['Attachments'][0]['Device']
                        vdata['state'] = volume_details['Volumes'][0]['Attachments'][0]['State']
                        deployed['subnets'][sn_id][inst.id][v.volume_id].append(vdata)
        
        updateDeployed(g, changes)
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