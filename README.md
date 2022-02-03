# fetch-devops-challenge
#### Fetch Rewards Coding Assessment - DevOps Engineer
-------

#### NOTE: tested on Windows 10, python version: 3.9.1, using ```cmd```
#### NOTE: tested on MacOS 10.15.7, python version: 3.7.9, using ```terminal```
#### NOTE: steps are the same except for "activate virtual environment"

-------

###### NOTE: after ```(venv) $ python deploy.py config.yaml``` completes, output file ```deployed.json``` will be created in ```fetch-devops-challenge``` directory.
###### NOTE: after ```(venv) $ python deploy.py config.yaml``` completes, ssh commands will be printed to terminal and will be in output file ```deployed.json```.
###### NOTE: deployed ec2 instance(s) will have two 'extra' mounted partitions at ```/extra``` and ```/data```. Both are configured to give readonly access (recursively) to all users on the instance and will contain user specific directories, excluding ```admin``` (such as ```/extra/user1``` or ```/data/user1```) that give write permission to its respective (similarly named) user.

### Steps:

1. Clone this repo:
    - git clone https://github.com/spenfraz/fetch-devops-challenge.git

2. Create virtual environment, activate and install dependencies.
    - ```cd fetch-devops-challenge```
    - ```python -m venv venv```
    - activate virtual environment
      - Windows: 
        - ```venv\Scripts\activate```
      - MacOS:
        - ```source venv/bin/activate``` 
    - ```pip install -r requirements.txt```

3. Create and add values to ```aws.env``` file (in ```fetch-devops-challenge``` project directory).
   ###### NOTE: no spaces or quotes in values.

        AWS_ACCESS_KEY_ID=
        AWS_SECRET_ACCESS_KEY=
        AWS_REGION=us-east-1
        
4. Run ```deploy.py```
    - ```python deploy.py config.yaml```
    - OR
    - ```python deploy.py config.yaml --destroy```




