#!/bin/bash
set -x #mode of the shell where all executed commands are printed to the terminal.
set -e #mode of the shell that immediately exits if any command [1] has a non-zero exit status.

EC2_INSTANCE_ID=$(curl -s http://instance-data/latest/meta-data/instance-id)
REGION=$(curl -s http://instance-data/latest/meta-data/placement/region)

# install aws cli (2)
sudo yum install -y unzip
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
./aws/install


### createAdminUser(username)
##  NOTE: 
##      This function copies over the public key from the ec2-user
##    .ssh/authorized_keys to the the new (admin) user's authorized_keys.
##  --> Deletes the ec2-user. 
#
# $1 ==> username (eg. admin or user1)
createAdminUser () {

    # add user with -m and -s options
    useradd --shell /bin/bash $1 --create-home
    
    # add user to wheel group (for sudo usage on CentOS based systems)
    usermod -aG wheel $1
    
    # create .ssh directory for user and apply appropriate permissions
    mkdir /home/$1/.ssh
    chmod 700 /home/$1/.ssh
    
    # copy over public key used during instance creation (ec2-user's public key)
    # to new user's .ssh/authorized_keys and apply permissions
    mv /home/ec2-user/.ssh/authorized_keys /home/$1/.ssh/authorized_keys
    chmod 600 /home/$1/.ssh/authorized_keys
    
    # change (recursive) ownership from root:root to new user for .ssh/
    chown $1:$1 -R /home/$1/.ssh

    # set new admin users password to temp password
    echo $1:"36skip74up36dog" | chpasswd

    # delete ec2-user (and home directory)
    userdel -r ec2-user
}


### createUser(username)
##  NOTE:
##      This function does not create/handle ssh keys for new users. 
##    It does create an initial empty authorized_keys file.
#
# $1 ==> username
createRegularUser () {

    # add new user with -s and -m options
    useradd --shell /bin/bash $1 --create-home

    # create new user's .ssh directory with appropriate permissions
    mkdir /home/$1/.ssh
    chmod 700 /home/$1/.ssh

    # create new user's .ssh/authorized_keys file with appropriate permissions
    touch /home/$1/.ssh/authorized_keys
    chmod 600 /home/$1/.ssh/authorized_keys

    # change (recursive) ownership from root:root to new user for .ssh/
    chown $1:$1 -R /home/$1/.ssh
}


### makeSharedDirectory(username, directory)
##      This function creates a user owned directory
##    (of the same name) within a specific parent directory.
##    It also ensures that the parent directory is owned by root.
##
##  The purpose of this function is to give each user their own
##  folder (exclusive write access) within a shared read parent
##      directory owned by root.
##  NOTE:
##      All files within the shared parent directory
##   (including all sub-directories) can be read by all non-root users.
#
# $1 ==> username
# $2 ==> directory
makeSharedDirectory () {

    # make directory (eg. /data/user1 )
    mkdir $2/$1

    # change ownership (recursively) to user's group
    chown -R root:$1 $2/$1

    # give group write access
    chmod -R g+w $2/$1

}


### formatAndMount(device_name, device_type, mount_path)
##       This function checks that the device is attached,
##    then creates formatted partition and mounts it.
##    Lastly, an entry is appended to /etc/fstab to 
##   mount volume on reboot.
#
# $1 ==> device_name (eg. /dev/xvdf or /dev/xvdc)
# $2 ==> type (filesystem) (eg. ext4 or xfs)
# $3 ==> mount (path) (eg. /data or /extra)
formatAndMount () {

    # Volume device_name ==> $1
    VOLUME_STATE="unknown"
    until [ "${VOLUME_STATE}" == "attached" ]; do
        VOLUME_STATE=$(aws ec2 describe-volumes \
        --region ${REGION} \
        --filters \
            Name=attachment.instance-id,Values=${EC2_INSTANCE_ID} \
            Name=attachment.device,Values=$1 \
        --query Volumes[].Attachments[].State \
        --output text)

        sleep 5
    done

    # Format $1 if it does not contain a partition yet
    if [ "$(file -b -s $1)" == "data" ]; then
        mkfs -t $2 $1
    fi

    mkdir -p $3
    mount $1 $3

    # Persist the volume in /etc/fstab so it gets mounted again
    echo $1 $3 $2 defaults,nofail 0 2 >> /etc/fstab

}