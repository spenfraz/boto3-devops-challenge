import time
from aws.utils.utils import updateDeployed


# Check for an existing default vpc, if none, create new default vpc, else update vpcID and sgID.
# After creating default vpc save its vpcID and sgID to ('deployed' json) output file.
def createDefaultVPC(g):
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')
    
    changes = {}

    filters = [{'Name':'is-default', 'Values':['true']}]
    vpcs = list(ec2_resource.vpcs.filter(Filters=filters))

    default_vpc = None
    if len(vpcs):
        # Every AWS account has one default VPC per AWS Region.
        default_vpc = vpcs[0]
    
    if default_vpc:
        changes['vpc_id'] = default_vpc.id
        changes['sg_id'] = [sg.id for sg in default_vpc.security_groups.all()][0]
        changes['subnets'] = {}
        for sn in default_vpc.subnets.all():
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block
    else:
        vpc_id = ec2_client.create_default_vpc()['Vpc']['VpcId']
        default_vpc = list(ec2_resource.vpcs.filter(VpcIds=[vpc_id]))[0]

        changes['vpc_id'] = vpc_id
        changes['sg_id'] = [sg.id for sg in default_vpc.security_groups.all()][0]
        changes['subnets'] = {}
        for sn in default_vpc.subnets.all():
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block

    updateDeployed(g, changes)


# check if vpc exists, filtering on cidr and tag:Name
def getVpcByTagsAndCidr(g):
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')

    vpc_tags = []
    for _tag in g['config']['vpc']['tags']:
        tag = {}
        tag['Key'] = _tag['key']
        tag['Value'] = _tag['value']
        vpc_tags.append(tag)
    
    response = ec2_client.describe_vpcs(
        Filters=[
            {
                'Name': 'tag:Name',
                'Values': [
                    vpc_tags[0]['Value'],
                ]
            },
            {
                'Name': 'cidr-block-association.cidr-block',
                'Values': [
                    g['config']['vpc']['cidr'],
                ]
            },        
        ]
    )

    if response['Vpcs']:
        filters = [{'Name':'cidr-block-association.cidr-block', 'Values':[g['config']['vpc']['cidr']]}]
        vpcs = list(ec2_resource.vpcs.filter(Filters=filters))
        return vpcs[0]
    else:
        return None


def createCustomVpc(g):
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')

    vpc = ec2_resource.create_vpc(CidrBlock=g['config']['vpc']['cidr'])
    vpc.wait_until_available()

    # enable for public dns for ec2
    ec2_client.modify_vpc_attribute(
        EnableDnsHostnames = {
            'Value': True
        },
        VpcId=vpc.id
    )
    # enable for public dns for ec2
    ec2_client.modify_vpc_attribute(
        EnableDnsSupport = {
            'Value': True
        },
        VpcId=vpc.id
    )
    
    # tag the vpc
    vpc_tags = []
    for _tag in g['config']['vpc']['tags']:
        tag = {}
        tag['Key'] = _tag['key']
        tag['Value'] = _tag['value']
        vpc_tags.append(tag)
    vpc.create_tags(Tags=vpc_tags) #(Tags=[{"Key": "Name", "Value": "default_vpc"}])

    # create and attach internet gateway
    ig = ec2_resource.create_internet_gateway()
    vpc.attach_internet_gateway(InternetGatewayId=ig.id)

    # add route to routetable (one created by default for vpc) for internet gateway
    for route_table in vpc.route_tables.all():
        route_table.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)
    
    subnets = []
    # create subnets
    for sn in g['config']['vpc']['subnets']:
        # create subnet
        subnet = ec2_resource.create_subnet(CidrBlock=sn['cidr'], VpcId=vpc.id, AvailabilityZone=sn['availability_zone'])
        time.sleep(2)
        subnets.append(subnet)
    
    for sn in subnets:
        # associate the route table with the subnet
        route_table.associate_with_subnet(SubnetId=sn.id)
        time.sleep(2)

    # tag subnets
    i = 0
    for sn in subnets:
        subnet_tags = []
        for _tag in g['config']['vpc']['subnets'][i]['tags']:
            tag = {}
            tag['Key'] = _tag['key']
            tag['Value'] = _tag['value']
            subnet_tags.append(tag)
            i += 1

        subnet.create_tags(Tags=subnet_tags)
    
    # create sec group
    sec_group = ec2_resource.create_security_group(
        GroupName='inbound-ssh', Description='inbound ssh access', VpcId=vpc.id)

    '''
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
    )'''
    
    # add inbound ssh sec group rule
    sec_group.authorize_ingress(
        CidrIp='0.0.0.0/0',
        IpProtocol='tcp',
        FromPort=22,
        ToPort=22)
    

    return vpc, subnets, sec_group


# create a custom vpc
def createVPC(g):
    changes = {}

    vpc = getVpcByTagsAndCidr(g)
    # if vpc exists, update output file
    if vpc:
        print('vpc exists')

        changes['vpc_id'] = vpc.id
        changes['vpc_cidr'] = vpc.cidr_block
        updateDeployed(g, changes)

        changes['subnets'] = {}
        for sn in vpc.subnets.all():
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block

        changes['sg_id'] = [sg.id for sg in vpc.security_groups.all()][0]

    else:
        print('creating vpc')
        # create vpc
        vpc, subnets, sec_group = createCustomVpc(g)

        # update changes
        changes['vpc_id'] = vpc.id
        updateDeployed(g, changes)

        changes['vpc_cidr'] = vpc.cidr_block
        
        changes['subnets'] = {}
                
        for sn in subnets:
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block

        changes['sg_id'] = sec_group.id

    updateDeployed(g, changes)
