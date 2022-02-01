import os, sys, io, time
from pprint import pprint
import paramiko

### NOTE: keypair (name) and key(file)name should be the same.
##   If the key pair is for the admin key, use create_key_pair method from boto3
## else use paramiko's RSAKey.generate. 
### NOTE: create_key_pair from boto3 returns the private key, but provides no 
###    convenient way to get the public key.
def create_key_pair(path, keypair, is_admin, session):
    ssh_keys_path = path

    if not os.path.exists(ssh_keys_path + keypair):
        if is_admin:
            key_pair = session.client('ec2').create_key_pair(KeyName=keypair)
            private_key = key_pair["KeyMaterial"]
        else:
            key = paramiko.RSAKey.generate(4096)
            # print public key
            #print(key.get_base64())
            public_key = key.get_base64()
            
            # print private key
            #key.write_private_key(sys.stdout)
        
            out = io.StringIO()
            key.write_private_key(out)
            #print(out.getvalue())

            private_key = out.getvalue()
        # write private key to file with permissions 400
        with os.fdopen(os.open(ssh_keys_path + keypair, os.O_WRONLY | os.O_CREAT, 0o400), "w+") as handle:
            handle.write(private_key)
        
        if not is_admin:
            #w write public key to file with permissions 400
            with os.fdopen(os.open(ssh_keys_path + keypair.replace('.pem','.pub'), os.O_WRONLY | os.O_CREAT, 0o400), "w+") as handle:
                handle.write(public_key)

# Deletes admin key via boto3's delete_key_pair, and 
#  directly deletes the .pem and .pub files for user keys.
def delete_key_pair(path, keypair, session):
    ssh_keys_path = path

    response = session.client('ec2').delete_key_pair(KeyName=keypair)
    
    if os.path.exists(ssh_keys_path + keypair):
        os.remove(ssh_keys_path + keypair)
    
    if os.path.exists(ssh_keys_path + keypair.replace('.pem','.pub')):
        os.remove(ssh_keys_path + keypair.replace('.pem','.pub'))

# Iterates over admin and users and creates their respective keypairs.
def createSshKeys(g):
    config = g['config']
    
    ssh_keys_directory = config['ssh_keys']['directory'] + os.sep
    admin_keyfile = config['server']['admin']['ssh_key']['name']

    IS_ADMIN_KEY = True
    NOT_ADMIN_KEY = False

    create_key_pair(ssh_keys_directory, admin_keyfile, IS_ADMIN_KEY, g['session'])
    
    for user in config['server']['users']:
        create_key_pair(ssh_keys_directory, user['ssh_key']['name'], NOT_ADMIN_KEY, g['session'])

# Iterates over admin and users and deletes their respective keypairs.
def deleteSshKeys(g):
    config = g['config']

    ssh_keys_directory = config['ssh_keys']['directory'] + os.sep
    admin_keyfile = config['server']['admin']['ssh_key']['name']

    delete_key_pair(ssh_keys_directory, admin_keyfile, g['session'])
    
    for user in config['server']['users']:
        delete_key_pair(ssh_keys_directory, user['ssh_key']['name'], g['session'])

### NOTE: a temporary plaintext password is used (see config.yaml) for admin account, but 
#     the admin password is expired immediately after, and will be prompted to be changed on 
#     next login. 
# Uses paramiko ssh client to connect (as admin user) and run a bash shell command copying the 
#  public keys for (non-admin) users to their respective ~/.ssh/authorized_keys file. 
def send_key(g, public_key_path, hostname, user):
    private_key_file = g['config']['server']['admin']['ssh_key']['name']
    ssh_keys_directory = g['root_path'] + g['config']['ssh_keys']['directory']
    private_key_full_path =  ssh_keys_directory + os.sep + private_key_file

    admin_username = g['config']['server']['admin']['login']

    if os.path.exists(public_key_path):
        public_key_string = open(public_key_path,'r').read()
    else:
        print('public key not found')

    private_key_string = open(private_key_full_path,'r').read()
    pkey = io.StringIO()
    pkey.write(private_key_string)
    pkey.seek(0)

    k = paramiko.RSAKey.from_private_key(pkey)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    c.connect(hostname=hostname, username=admin_username, pkey=k)
    print()
    print('connecting to ' + admin_username + '@' + hostname)
    
    temp_password = g['config']['server']['admin']['initial_sudo_password']

    #command = 'echo ' + temp_password + ' | sudo -S echo ssh-rsa' + public_key_string
    cmd = 'echo ' + temp_password + ' | sudo -S -k bash -c \'echo' + temp_password +' | sudo -S -k echo ssh-rsa ' + public_key_string + ' ' + user + '-key.pem' + ' >> /home/' + user + '/.ssh/authorized_keys\''
    #print(cmd)
    print('  copying public key for ' + user + ' to ~/.ssh/authorized_keys')
    (stdin, stdout, stderr) = c.exec_command(cmd)
    print()
    for line in stdout.readlines():
        print('    ' + line)
    c.close()

#  Uses paramiko ssh client to connect (as admin user) and run a bash shell command to force
#  admin user password change on next ssh login.
def force_admin_pass_change(g):
    private_key_file = g['config']['server']['admin']['ssh_key']['name']
    ssh_keys_directory = g['root_path'] + g['config']['ssh_keys']['directory']
    private_key_full_path =  ssh_keys_directory + os.sep + private_key_file

    admin_username = g['config']['server']['admin']['login']

    private_key = open(private_key_full_path,'r').read()
    pkey = io.StringIO()
    pkey.write(private_key)
    pkey.seek(0)

    k = paramiko.RSAKey.from_private_key(pkey)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    hostname = g['deployed']['ec2_instances'][0]['public_dns']
    c.connect(hostname=hostname, username=admin_username, pkey=k)
    print('connecting to ' + admin_username + '@' + hostname)

    temp_password = g['config']['server']['admin']['initial_sudo_password']
    print('  forcing password reset for ' + admin_username + ' on next ssh login')
    print()
    cmd = 'echo ' + temp_password + ' | sudo -S passwd --expire admin'
    (stdin, stdout, stderr) = c.exec_command(cmd)
    for line in stdout.readlines():
        print('    ' + line)
    c.close()

# iterate over (non-admin) users and call send_key for each respective public key
def sendKeys(g):
    ssh_keys_directory = g['root_path'] + g['config']['ssh_keys']['directory']
    for host in g['deployed']['ec2_instances']:
        hostname = host['public_dns']
        
        for user in g['config']['server']['users']:
            user_login_name = user['login']
            public_key_file_name = user['ssh_key']['name'].replace('pem', 'pub')
            public_key_full_path = ssh_keys_directory + os.sep + public_key_file_name

            attempts = 0
            print('sending public keys for users to server...')
            while(attempts < 5):
                try:
                    send_key(g, public_key_full_path, hostname, user_login_name)
                    break
                except Exception:
                     print('  server must not be ready yet, retrying...')
                finally:
                    time.sleep(20)
                    attempts += 1