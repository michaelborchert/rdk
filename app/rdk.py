import os
import sys
from shutil import copyfile
import boto3
import json
import time

rdk_dir = '.rdk'
rules_dir = ''
tests_dir = ''
util_filename = 'rule_util.py'
rule_handler = 'rule_code.py'
rule_template = 'rdk-rule.template'
config_bucket_prefix = 'config-bucket-'
config_role_name = 'config-role'
assume_role_policy_file = 'configRoleAssumeRolePolicyDoc.json'
delivery_permission_policy_file = 'deliveryPermissionsPolicy.json'
code_bucket_prefix = 'config-rule-code-bucket-'
parameter_file_name = 'parameters.json'

class RDK():
    def __init__(self, args):
        self.args = args

    def process_command(self):
        method_to_call = getattr(self, self.args.command)
        exit_code = method_to_call()

        return(exit_code)

    def init(self):
        #run the init code
        print ("Running init!")

        #create .rdk directory
        if not os.path.exists(rdk_dir):
            os.makedirs(rdk_dir)

        #copy contents of template directory into .rdk directory
        src_path = os.path.join(os.path.dirname(sys.argv[0]), 'app', 'template')

        for f in os.listdir(src_path):
            if not os.path.exists(os.path.join(rdk_dir, f)):
                src = os.path.join(src_path, f)
                dst = os.path.join(rdk_dir, f)
                copyfile(src, dst)


        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        #get accountID
        my_sts = my_session.client('sts')
        response = my_sts.get_caller_identity()
        account_id = response['Account']

        #create config bucket
        config_bucket_name = config_bucket_prefix + account_id
        my_s3 = my_session.client('s3')
        response = my_s3.list_buckets()
        bucket_exists = False
        for bucket in response['Buckets']:
            if bucket['Name'] == config_bucket_name:
                bucket_exists = True

        if not bucket_exists:
            print('Creating Config bucket '+config_bucket_name )
            my_s3.create_bucket(Bucket=config_bucket_name)

        #create config role
        my_iam = my_session.client('iam')
        response = my_iam.list_roles()
        role_exists = False
        for role in response['Roles']:
            if role['RoleName'] == config_role_name:
                role_exists = True

        if not role_exists:
            print('Creating IAM role config-role')
            assume_role_policy = open(os.path.join(rdk_dir, assume_role_policy_file), 'r').read()
            my_iam.create_role(RoleName=config_role_name, AssumeRolePolicyDocument=assume_role_policy)

        #attach role policy
        my_iam.attach_role_policy(RoleName=config_role_name, PolicyArn='arn:aws:iam::aws:policy/service-role/AWSConfigRole')
        policy_template = open(os.path.join(rdk_dir, delivery_permission_policy_file), 'r').read()
        delivery_permissions_policy = policy_template.replace('ACCOUNTID', account_id)
        my_iam.put_role_policy(RoleName=config_role_name, PolicyName='ConfigDeliveryPermissions', PolicyDocument=delivery_permissions_policy)

        #wait for changes to propagate.
        print('Waiting for IAM role to propagate')
        time.sleep(16)

        #create config recorder
        my_config = my_session.client('config')
        role_arn = "arn:aws:iam::"+account_id+":role/config-role"
        my_config.put_configuration_recorder(ConfigurationRecorder={'name':'default', 'roleARN':role_arn, 'recordingGroup':{'allSupported':True, 'includeGlobalResourceTypes': True}})

        #create delivery channel
        my_config.put_delivery_channel(DeliveryChannel={'name':'default', 's3BucketName':config_bucket_name, 'configSnapshotDeliveryProperties':{'deliveryFrequency':'Six_Hours'}})

        print('Config setup complete.')

        #start config recorder
        my_config.start_configuration_recorder(ConfigurationRecorderName='default')
        print('Config Service is ON')

        #create code bucket
        code_bucket_name = code_bucket_prefix + account_id
        response = my_s3.list_buckets()
        bucket_exists = False
        for bucket in response['Buckets']:
            if bucket['Name'] == code_bucket_name:
                bucket_exists = True

        if not bucket_exists:
            print('Creating Code bucket '+code_bucket_name )
            my_s3.create_bucket(Bucket=code_bucket_name)

        #make sure lambda execution role exists - TODO
        return 0

    def create(self):
        print ("Running create!")

        if len(self.args.rulename) > 1:
            print("'create' command requires only one rule name.")
            return 1

        if self.args.event and self.args.periodic:
            print("Either the 'Event' flag or the 'Periodic' flag may be set, but not both.")
            return 1

        if not self.args.runtime:
            print("Runtime is required for 'create' command.")
            return 1

        #create rule directory.
        rule_path = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0])
        if os.path.exists(rule_path):
            print("Rule already exists.")
            return 1

        os.makedirs(os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0]))

        #copy rule.py template into rule directory
        src = os.path.join(os.path.dirname(sys.argv[0]), rdk_dir, rule_handler)
        dst = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0], self.args.rulename[0]+".py")
        copyfile(src, dst)

        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        #get accountID
        my_sts = my_session.client('sts')
        response = my_sts.get_caller_identity()
        account_id = response['Account']

        #create config file and place in rule directory
        parameters = {
            'RuleName': self.args.rulename[0],
            'Runtime': self.args.runtime,
            'CodeBucket': code_bucket_prefix + account_id,
            'CodeKey': self.args.rulename[0]+'.zip'
        }

        if self.args.event:
            parameters['Event'] = self.args.event
        elif self.args.periodic:
            parameters['Periodic'] = self.args.periodic

        my_params = {"Parameters": parameters}
        params_file_path = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0], parameter_file_name)
        parameters_file = open(params_file_path, 'w')
        json.dump(my_params, parameters_file)
        parameters_file.close()

        return 0

    def test_local(self):
        print ("Running create!")
        return 0
    def test_remote(self):
        print ("Running create!")
        return 0
    def deploy(self):
        print ("Running create!")
        return 0
    def status(self):
        print ("Running create!")
        return 0

    def get_boto_session(self):
        session_args = {}

        if self.args.region:
            session_args['region_name'] = self.args.region

        if self.args.profile:
            session_args['profile_name']=self.args.profile
        elif self.args.access_key and self.args.secret_access_key:
            session_args['aws_access_key_id']=self.args.access_key
            session_args['aws_secret_access_key']=self.args.secret_access_key

        return boto3.session.Session(**session_args)
