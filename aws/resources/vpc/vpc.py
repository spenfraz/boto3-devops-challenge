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
        # Every AWS account has one default VPC for each AWS Region.
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
        changes['vpc_id'] = vpc_id
        default_vpc = list(ec2_resource.vpcs.filter(VpcIds=[vpc_id]))[0]
        changes['sg_id'] = [sg.id for sg in default_vpc.security_groups.all()][0]
        changes['subnets'] = {}
        for sn in default_vpc.subnets.all():
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block

    updateDeployed(g, changes)


#def getVpcByTagsAndCidr():
    

# create a custom vpc
def createVPC(g):
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')
    
    changes = {}

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

    vpc = None
    vpc_id = None
    vpc_cidr = None
    
    # vpc already exists
    if response['Vpcs']:
        print('vpc exists')
        #print(response['Vpcs'])
        vpc_id = response['Vpcs'][0]['VpcId']
        vpc_cidr = response['Vpcs'][0]['CidrBlock']
        filters = [{'Name':'cidr-block-association.cidr-block', 'Values':[g['config']['vpc']['cidr']]}]
        vpcs = list(ec2_resource.vpcs.filter(Filters=filters))
        vpc = vpcs[0]
        #ig_id = [ig for ig in vpc.internet_gateways.all()][0].id
        #changes['ig_id'] = ig_id
        
        changes['subnets'] = {}
        subnet = {}
        for sn in vpc.subnets.all():
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block
        
        changes['vpc_id'] = {}
        changes['vpc_id']['subnets'] = []
        changes['vpc_id']['subnets'].append(subnet)
        
        changes['vpc_id'] = {}
        changes['vpc_id'] = vpc_id
        changes['vpc_cidr'] = vpc_cidr

        changes['sg_id'] = [sg.id for sg in vpc.security_groups.all()][0]
        
    else:
        print('creating vpc')
        # create vpc
        vpc = ec2_resource.create_vpc(CidrBlock=g['config']['vpc']['cidr'])
        time.sleep(2)
        vpc.wait_until_available()

        response = ec2_client.modify_vpc_attribute(
            EnableDnsHostnames = {
                'Value': True
            },
            VpcId=vpc.id
        )

        response = ec2_client.modify_vpc_attribute(
            EnableDnsSupport = {
                'Value': True
            },
            VpcId=vpc.id
        )

        # tag the vpc 
        vpc.create_tags(Tags=vpc_tags) #(Tags=[{"Key": "Name", "Value": "default_vpc"}])
        changes['vpc_id'] = {}
        changes['vpc_id'] = vpc.id
        changes['vpc_cidr'] = vpc.cidr_block
        #print(vpc.id)
        
        # create and attach internet gateway
        ig = ec2_resource.create_internet_gateway()
        vpc.attach_internet_gateway(InternetGatewayId=ig.id)
        #changes['ig_id'] = ig.id
        #print(ig.id)

        # add route to routetable (one created by default for vpc) for internet gateway
        for route_table in vpc.route_tables.all():
            route_table.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=ig.id)

        subnets = []
        i = 0
        for sn in g['config']['vpc']['subnets']:
            # create subnet
            subnet = ec2_resource.create_subnet(CidrBlock=sn['cidr'], VpcId=vpc.id, AvailabilityZone=sn['availability_zone'])
            time.sleep(2)
            subnet_tags = []
            for _tag in g['config']['vpc']['subnets'][i]['tags']:
                tag = {}
                tag['Key'] = _tag['key']
                tag['Value'] = _tag['value']
                subnet_tags.append(tag)
                i += 1

            for _tag in sn['tags']:
                subnet.create_tags(Tags=subnet_tags)
            subnets.append(subnet)
        
        changes['subnets'] = {}
        subnet = {}

        subnet = {}
        for sn in subnets:
            # associate the route table with the subnet
            route_table.associate_with_subnet(SubnetId=sn.id)
            
            changes['subnets'][sn.id] = {}
            changes['subnets'][sn.id]['az'] = sn.availability_zone
            changes['subnets'][sn.id]['cidr'] = sn.cidr_block

        # create sec group
        sec_group = ec2_resource.create_security_group(
            GroupName='inbound-ssh', Description='inbound ssh access', VpcId=vpc.id)

        # add inbound ssh sec group rule
        sec_group.authorize_ingress(
            CidrIp='0.0.0.0/0',
            IpProtocol='tcp',
            FromPort=22,
            ToPort=22)
        
        changes['sg_id'] = sec_group.id

    updateDeployed(g, changes)
