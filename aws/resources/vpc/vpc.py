import time

from botocore.exceptions import ClientError


# check if vpc exists by vpc_id
def vpc_exists(g, vpc_id):
    ec2_client = g['session'].client('ec2')
    try:
        ec2_client.describe_vpcs(VpcIds=[vpc_id])
    except ClientError as e:
        print('\n' + e + '\n')
        return False
    return True

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

# get subnets by tags from config.yaml
def getSubnetsByTag(g):
    ec2_resource = g['session'].resource('ec2')

    subnet_filters = []
    for _tag in g['config']['server']['subnet']['tags']:
        tag_filter = {}
        tag_filter['Name'] = 'tag:' +_tag['key']
        tag_filter['Values'] = []
        tag_filter['Values'].append(_tag['value'])
        subnet_filters.append(tag_filter)
    #filters = [{'Name': 'tag:Name', 'Values':['fetch-devops-challenge-subnet-1']}]
    subnets = list(ec2_resource.subnets.filter(Filters=subnet_filters))
    return subnets

# destroy vpc and all ec2 instances in it
def teardown(g):
    ec2_client = g['session'].client('ec2')

    vpc = getVpcByTagsAndCidr(g)
    if not vpc:
        print('vpc doesn\'t exist')
    else:
        print(vpc)
        vpc_id = vpc.id

        try:
            # disassociate and release EIPs from EC2 instances
            for subnet in vpc.subnets.all():
                print(subnet)
                for instance in subnet.instances.all():
                    print(instance)
                    filters = [{"Name": "instance-id", "Values": [instance.id]}]
                    eips = ec2_client.describe_addresses(Filters=filters)["Addresses"]
                    for eip in eips:
                        ec2_client.disassociate_address(AssociationId=eip["AssociationId"])
                        ec2_client.release_address(AllocationId=eip["AllocationId"])
                        print('    disassociating and releasing EIPs from ec2 instances')
            
            ## terminate EC2 instances

            # get instances that are running in vpc
            filters = [
                {"Name": "instance-state-name", "Values": ["running"]},
                {"Name": "vpc-id", "Values": [vpc_id]},
            ]

            # add instances to list
            ec2_instances = ec2_client.describe_instances(Filters=filters)
            instance_ids = []
            for reservation in ec2_instances["Reservations"]:
                instance_ids += [instance["InstanceId"] for instance in reservation["Instances"]]
            
            # begin terminating instances and wait for completion
            print('terminating ec2 instances')
            print('waiting for ec2 instances to be terminated')
            if instance_ids:
                waiter = ec2_client.get_waiter("instance_terminated")
                ec2_client.terminate_instances(InstanceIds=instance_ids)
                waiter.wait(InstanceIds=instance_ids)
            print('ec2 instances terminated')
            
            ## move on to other VPC specific resources
            print('deleting other vpc specific subresources')
            # delete transit gateway attachment for this vpc
            # note - this only handles vpc attachments, not vpn
            for attachment in ec2_client.describe_transit_gateway_attachments()[
                "TransitGatewayAttachments"
            ]:
                if attachment["ResourceId"] == vpc_id:
                    ec2_client.delete_transit_gateway_vpc_attachment(
                        TransitGatewayAttachmentId=attachment["TransitGatewayAttachmentId"]
                    )
                    print('  deleting transit gateway attachement for this vpc')

            # delete NAT Gateways
            # attached ENIs are automatically deleted
            # EIPs are disassociated but not released
            filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
            for nat_gateway in ec2_client.describe_nat_gateways(Filters=filters)["NatGateways"]:
                ec2_client.delete_nat_gateway(NatGatewayId=nat_gateway["NatGatewayId"])
                print('  deleting nat gateway')

            ec2_resource = g['session'].resource('ec2')

            # detach default dhcp_options if associated with the vpc
            dhcp_options_default = ec2_resource.DhcpOptions("default")
            if dhcp_options_default:
                dhcp_options_default.associate_with_vpc(VpcId=vpc.id)
                print('  detaching default dhcp_options associated with vpc')

            # delete any vpc peering connections
            for vpc_peer in ec2_client.describe_vpc_peering_connections()[
                "VpcPeeringConnections"
            ]:
                if vpc_peer["AccepterVpcInfo"]["VpcId"] == vpc_id:
                    ec2_resource.VpcPeeringConnection(vpc_peer["VpcPeeringConnectionId"]).delete()
                    print('  deleting vpc peering connection')
                if vpc_peer["RequesterVpcInfo"]["VpcId"] == vpc_id:
                    ec2_resource.VpcPeeringConnection(vpc_peer["VpcPeeringConnectionId"]).delete()
                    print('  deleting vpc peering connection')

            # delete our endpoints
            for ep in ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )["VpcEndpoints"]:
                ec2_client.delete_vpc_endpoints(VpcEndpointIds=[ep["VpcEndpointId"]])
                print('  deleting vpc endpoint')

            # delete custom security groups
            for sg in vpc.security_groups.all():
                if sg.group_name != "default":
                    sg.delete()
                    print('  deleting security group')

            # delete custom NACLs
            for netacl in vpc.network_acls.all():
                if not netacl.is_default:
                    netacl.delete()
                    print('  deleting nacl')

            # ensure ENIs are deleted before proceding
            timeout = time.time() + 300
            filter = [{"Name": "vpc-id", "Values": [vpc_id]}]
            reached_timeout = True
            while time.time() < timeout:
                if not ec2_client.describe_network_interfaces(Filters=filters)[
                    "NetworkInterfaces"
                ]:
                    print('  no enis remaining')
                    reached_timeout = False
                    break
                else:
                    print('    waiting for enis to delete') 
                    time.sleep(30)

            if reached_timeout:
                print('     ENI deletion timed out')

            # delete subnets
            for subnet in vpc.subnets.all():
                for interface in subnet.network_interfaces.all():
                    interface.delete()
                    print('  deleting network interface')
                subnet.delete()

            # Delete routes, associations, and routing tables
            filter = [{"Name": "vpc-id", "Values": [vpc_id]}]
            route_tables = ec2_client.describe_route_tables(Filters=filter)["RouteTables"]
            for route_table in route_tables:
                for route in route_table["Routes"]:
                    if route["Origin"] == "CreateRoute":
                        ec2_client.delete_route(
                            RouteTableId=route_table["RouteTableId"],
                            DestinationCidrBlock=route["DestinationCidrBlock"],
                        )
                        print('  deleting route in route table')
                    for association in route_table["Associations"]:
                        if not association["Main"]:
                            ec2_client.disassociate_route_table(
                                AssociationId=association["RouteTableAssociationId"] #### ERROR encountered #### botocore.exceptions.ClientError: An error occurred (InvalidAssociationID.NotFound) when calling the DisassociateRouteTable operation: The association ID 'rtbassoc-02082ff9ee5b78c6c' does not exist
                            )
                            print('  disassociating route table\'s association to subnet')
                            
                            ec2_client.delete_route_table(
                                RouteTableId=route_table["RouteTableId"]  ##### ERROR encountered #####
                            )
                            print('  deleting route table')

            # delete routing tables without associations
            for route_table in route_tables:
                if route_table["Associations"] == []:
                    ec2_client.delete_route_table(RouteTableId=route_table["RouteTableId"])
                    print('  deleting route table without associations')

            # destroy NAT gateways
            filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
            nat_gateway_ids = [
                nat_gateway["NatGatewayId"]
                for nat_gateway in ec2_client.describe_nat_gateways(Filters=filters)[
                    "NatGateways"
                ]
            ]
            for nat_gateway_id in nat_gateway_ids:
                ec2_client.delete_nat_gateway(NatGatewayId=nat_gateway_id)
                print('  deleting nat gateway')

            # detach and delete all IGWs associated with the vpc
            for gw in vpc.internet_gateways.all():
                vpc.detach_internet_gateway(InternetGatewayId=gw.id)
                print('  detaching internet gateway from vpc')
                gw.delete()
                print('  deleting internet gateway')

            ec2_client.delete_vpc(VpcId=vpc_id)
            print('  deleting vpc')
            print('vpc deleted')
        except Exception as e:
            print()
            print(e)
            print('error occurred, retrying...')
            time.sleep(6)
            print()
            teardown(g)

# create custom vpc, handling when vpc already exists
def createCustomVpc(g):
    ec2_resource = g['session'].resource('ec2')
    ec2_client = g['session'].client('ec2')

    vpc = ec2_resource.create_vpc(CidrBlock=g['config']['vpc']['cidr'])
    time.sleep(5)
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
    security_group = ec2_resource.create_security_group(
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
    security_group.authorize_ingress(
        CidrIp='0.0.0.0/0',
        IpProtocol='tcp',
        FromPort=22,
        ToPort=22)
    

    return vpc, subnets, security_group


# create a custom vpc
def createVPC(g):
    from aws.utils.utils import updateDeployed
    changes = {}

    vpc = getVpcByTagsAndCidr(g)
    # if vpc exists, update output file
    if vpc:
        print('vpc exists')
        
        subnets = getSubnetsByTag(g)

        security_groups = []
        for sg in vpc.security_groups.all():
            if sg.group_name != "default":
                security_groups.append(sg)
        sec_group = security_groups[0]

    else:
        print('creating vpc')
        # create vpc
        vpc, subnets, sec_group = createCustomVpc(g)

    # update changes
    changes['vpc_id'] = vpc.id
    changes['vpc_cidr'] = vpc.cidr_block
    changes['subnets'] = {}
            
    for sn in subnets:
        changes['subnets'][sn.id] = {}
        changes['subnets'][sn.id]['az'] = sn.availability_zone
        changes['subnets'][sn.id]['cidr'] = sn.cidr_block
    
    changes['sg_id'] = sec_group.id
    updateDeployed(g, changes)
