import os, json
from pprint import pprint

from aws.utils.utils import readFromFile


# check if role exists by name
def roleExists(g, role_name):
    iam = g['session'].resource('iam')
    
    roles = iam.roles.filter(
        PathPrefix='/'
    )

    for role in roles:
        if role_name == role.role_name:
            return True
    return False

# check if policy exists by name
def policyExists(g, policy_name):
    policy_arn = getPolicyArn(g, policy_name)

    if policy_arn:
        return True
    else:
        return False

# check if profile exists by name
def profileExists(g, profile_name):
    iam = g['session'].resource('iam')

    instance_profiles = iam.instance_profiles.filter(
        PathPrefix='/'
    )
    for instance_profile in instance_profiles:
        if instance_profile.name == profile_name:
            return True
    return False

# get policy arn from policy name
def getPolicyArn(g, policy_name):
    iam = g['session'].client('iam')

    paginator = iam.get_paginator('list_policies')
    for response in paginator.paginate(Scope="Local"):
        for policy in response["Policies"]:
            if policy_name == policy['PolicyName']:
                return policy['Arn']
    return None

# get policy dictionary
def getPolicy(g, policy_name):
    iam = g['session'].client('iam')

    paginator = iam.get_paginator('list_policies')
    for response in paginator.paginate(Scope="Local"):
        for policy in response["Policies"]:
            if policy_name == policy['PolicyName']:
                return policy
    return None

# check if policy has more than 0 attachments
def policyIsAttached(g, policy_name):
    if policyExists(g, policy_name):
        if getPolicy(g, policy_name)['AttachmentCount']:
            return True
    else:
        return False

# create iam role
def create_iam_role(g, role_name, json_file_path):
    iam = g['session'].client('iam')

    assume_role_policy_document = readFromFile(json_file_path)

    response = iam.create_role(
        RoleName = role_name,
        AssumeRolePolicyDocument = assume_role_policy_document
    )
    #print(response)
    return response["Role"]["RoleName"]

# delete iam role
def delete_iam_role(g, role_name):
    iam = g['session'].resource('iam')

    role = iam.Role(
        role_name
    )
    role.delete()

# create iam policy
def create_iam_policy(g, role_name, json_file_path):
    iam = g['session'].client('iam')

    # Create a policy
    policy = readFromFile(json_file_path)
    
    response = iam.create_policy(
        PolicyName=role_name,
        PolicyDocument=policy
    )
    #print(response)
    return response['Policy']['Arn']

# delete iam policy
def delete_iam_policy(g, policy_name):
    iam = g['session'].resource('iam')

    policy = iam.Policy(
        getPolicyArn(g, policy_name)
    )
    policy.delete()

# attach iam policy to role
def attach_iam_policy(g, policy_name, role_name):
    iam = g['session'].client('iam')

    response = iam.attach_role_policy(
        RoleName=role_name,
        PolicyArn=getPolicyArn(g,policy_name)
    )
    #print(response)

# detach iam policy from role
def detach_iam_policy(g, policy_name, role_name):
    iam = g['session'].resource('iam')

    role = iam.Role(role_name)

    response = role.detach_policy(
        PolicyArn=getPolicyArn(g, policy_name)
    )
    #print(response)

# create instance profile (container for an iam role that is attached to ec2 instance)
def createInstanceProfile(g):
    config = g['config']
    iam = g['session'].client('iam')
    
    instance_profile = config['server']['iam']['instance_profile']

    roles_directory_path = g['root_path'] + g['config']['server']['iam']['roles_directory'].replace('_', os.sep) + os.sep
    role_file = g['config']['server']['iam']['instance_profile']['role']['file']
    role_file_path = roles_directory_path + role_file

    role_name = instance_profile['role']['name']

    policy_directory_path = g['root_path'] + g['config']['server']['iam']['policy_directory'].replace('_', os.sep) + os.sep
    policy_file = g['config']['server']['iam']['instance_profile']['policy']['file']
    policy_file_path = policy_directory_path + policy_file

    policy_name = instance_profile['policy']['name']
    instance_profile_name = instance_profile['name']

    if not roleExists(g, role_name):
        create_iam_role(g, role_name, role_file_path)
    if not policyExists(g, policy_name):
        create_iam_policy(g, policy_name, policy_file_path)
    attach_iam_policy(g, policy_name, role_name)

    
    if not profileExists(g, instance_profile_name):
        response = iam.create_instance_profile (
            InstanceProfileName = instance_profile_name 
        )

    response = iam.get_instance_profile(
        InstanceProfileName=instance_profile_name
    )
    if not response['InstanceProfile']['Roles']:
        iam.add_role_to_instance_profile (
            InstanceProfileName = instance_profile_name,
            RoleName            = role_name 
        )
    
    return { 'Arn': response['InstanceProfile']['Arn'] }

# delete instance profile
def deleteInstanceProfile(g):
    config = g['config']
    iam = g['session'].resource('iam')
    iam_client = g['session'].client('iam')
    
    instance_profile = config['server']['iam']['instance_profile']

    role_name = instance_profile['role']['name']
    policy_name = instance_profile['policy']['name']
    instance_profile_name = instance_profile['name']

    if profileExists(g, instance_profile_name):
        response = iam_client.get_instance_profile(
            InstanceProfileName=instance_profile_name
        )
        
        if response['InstanceProfile']['Roles']:
            instance_profile = iam.InstanceProfile(instance_profile_name)
            instance_profile.remove_role(
                RoleName=role_name
            )
            instance_profile.delete()
        else:
            instance_profile.delete()

    if policyIsAttached(g, policy_name):
        detach_iam_policy(g, policy_name, role_name)
    if roleExists(g, role_name):
        delete_iam_role(g, role_name)
    if policyExists(g, policy_name):
        delete_iam_policy(g, policy_name)