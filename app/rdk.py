import os
import sys
import shutil
import boto3
import json
import time
import imp
import argparse

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
example_ci_dir = 'example_ci'

class RDK():
    def __init__(self, args):
        self.args = args

    def process_command(self):
        method_to_call = getattr(self, self.args.command)
        exit_code = method_to_call()

        return(exit_code)

    def init(self):
        #parser = argparse.ArgumentParser()
        #self.args = parser.parse_args(self.args.command_args, self.args)

        #run the init code
        print ("Running init!")

        #if the .rdk directory exists, delete it.
        if  os.path.exists(rdk_dir):
            shutil.rmtree(rdk_dir)

        #copy contents of template directory into .rdk directory
        src = os.path.join(os.path.dirname(sys.argv[0]), 'app', 'template')
        dst = rdk_dir
        shutil.copytree(src, dst)


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

        #wait for changes to propagate. TODO: only do this if we had to create the role.
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

    #TODO: roll-back directory creation on failure.
    def create(self):
        print ("Running create!")
        parser = argparse.ArgumentParser(prog='rdk create')
        parser.add_argument('--runtime','-R', required=True, help='Runtime for lambda function', choices=['nodejs','nodejs4.3','nodejs6.10','java8','python2.7','python3.6','dotnetcore1.0','nodejs4.3-edge'])
        parser.add_argument('--periodic','-P', help='Execution period', choices=['One_Hour','Three_Hours','Six_Hours','Twelve_Hours','TwentyFour_Hours'])
        parser.add_argument('--event','-E', help='Resources that trigger event-based rule evaluation') #TODO - add full list of supported resources
        parser.add_argument('rulename', metavar='<rulename>', nargs='*', help='Rule name(s) (required for some commands)')
        self.args = parser.parse_args(self.args.command_args, self.args)

        if len(self.args.rulename) > 1:
            print("'create' command requires only one rule name.")
            return 1

        #if self.args.event and self.args.periodic:
        #    print("Either the 'Event' flag or the 'Periodic' flag may be set, but not both.")
        #    return 1

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
        shutil.copyfile(src, dst)

        src = os.path.join(os.path.dirname(sys.argv[0]), rdk_dir, util_filename)
        dst = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0], util_filename)
        shutil.copyfile(src, dst)

        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        #get accountID
        my_sts = my_session.client('sts')
        response = my_sts.get_caller_identity()
        account_id = response['Account']

        #create config file and place in rule directory
        parameters = {
            'RuleName': self.args.rulename[0],
            'SourceRuntime': self.args.runtime,
            'CodeBucket': code_bucket_prefix + account_id,
            'CodeKey': self.args.rulename[0]+'.zip'
        }

        if self.args.event:
            parameters['SourceEvents'] = self.args.event
        if self.args.periodic:
            parameters['SourcePeriodic'] = self.args.periodic

        my_params = {"Parameters": parameters}
        params_file_path = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, self.args.rulename[0], parameter_file_name)
        parameters_file = open(params_file_path, 'w')
        json.dump(my_params, parameters_file)
        parameters_file.close()

        return 0

    def deploy(self):
        #run the deploy code
        print ("Running deploy!")

        parser = argparse.ArgumentParser(prog='rdk create')
        parser.add_argument('rulename', metavar='<rulename>', nargs='*', help='Rule name(s) to deploy')
        parser.add_argument('--all','-a', help="All rules in the working directory will be deployed.")
        self.args = parser.parse_args(self.args.command_args, self.args)

        rule_names = self.get_rule_list_for_command()

        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        #get accountID
        my_sts = my_session.client('sts')
        response = my_sts.get_caller_identity()
        account_id = response['Account']

        for rule_name in rule_names:
            print ("Zipping " + rule_name)
            #zip rule code files and upload to s3 bucket
            s3_src_dir = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, rule_name)
            s3_dst = os.path.join(rule_name, rule_name+".zip")
            s3_src = shutil.make_archive(rule_name, 'zip', s3_src_dir)
            code_bucket_name = code_bucket_prefix + account_id
            my_s3 = my_session.resource('s3')

            print ("Uploading " + rule_name)
            my_s3.meta.client.upload_file(s3_src, code_bucket_name, s3_dst)

            #create CFN Parameters
            #read rest of params from file in rule directory
            params_file_path = os.path.join(os.path.dirname(sys.argv[0]), rules_dir, rule_name, parameter_file_name)
            parameters_file = open(params_file_path, 'r')
            my_json = json.load(parameters_file)
            parameters_file.close()

            my_params = [
                {
                    'ParameterKey': 'SourceBucket',
                    'ParameterValue': code_bucket_name,
                },
                {
                    'ParameterKey': 'SourcePath',
                    'ParameterValue': s3_dst,
                },
                {
                    'ParameterKey': 'SourceRuntime',
                    'ParameterValue': my_json['Parameters']['SourceRuntime'],
                },
                {
                    'ParameterKey': 'SourceEvents',
                    'ParameterValue': my_json['Parameters']['SourceEvents'],
                },
                {
                    'ParameterKey': 'SourcePeriodic',
                    'ParameterValue': my_json['Parameters']['SourcePeriodic'],
                }]

            #deploy config rule
            cfn_body = os.path.join(os.path.dirname(sys.argv[0]), rdk_dir, "configRole.json")
            my_cfn = my_session.client('cloudformation')

            try:
                my_stack = my_cfn.describe_stacks(StackName=rule_name)
                #If we've gotten here, stack exists and we should update it.
                print ("Updating CloudFormation Stack for " + rule_name)
                response = my_cfn.update_stack(
                    StackName=rule_name,
                    TemplateBody=open(cfn_body, "r").read(),
                    Parameters=my_params,
                    Capabilities=[
                        'CAPABILITY_IAM',
                    ],
                )
            except Exception as e:
                print(e)
                #If we're in the exception, the stack does not exist and we should create it.  Try/Catch blocks are not meant for flow control, but I'm not about to list all of the CFN stacks in an account just to see if this one stack exists every time we do a deploy.
                print ("Creating CloudFormation Stack for " + rule_name)
                response = my_cfn.create_stack(
                    StackName=rule_name,
                    TemplateBody=open(cfn_body, "r").read(),
                    Parameters=my_params,
                    Capabilities=[
                        'CAPABILITY_IAM',
                    ],
                )

            #wait for changes to propagate.
            in_progress = True
            while in_progress:
                print("Waiting for CloudFormation stack deployment...")
                time.sleep(5)
                my_stack = my_cfn.describe_stacks(StackName=rule_name)
                #print(my_stack)
                if 'IN_PROGRESS' not in my_stack['Stacks'][0]['StackStatus']:
                    in_progress = False

        print('Config deploy complete.')

        return 0

    def test_local(self):
        print ("Running test_local!")
        parser = argparse.ArgumentParser(prog='rdk test-local')
        parser.add_argument('rulenames', metavar='<rulename>[,<rulename>,...]', nargs='*', help='Rule name(s) to test')
        parser.add_argument('--all','-a', help="Test will be run against all rules in the working directory.")
        parser.add_argument('--test-ci-json', '-j', help="[optional] JSON for test CI for testing.")
        parser.add_argument('--test-ci-types', '-t', help="[optional] CI type to use for testing.")
        parser.add_argument('--test-parameters', '-p', help="[optional] JSON for Config parameters for testing.")
        self.args = parser.parse_args(self.args.command_args, self.args)

        if self.args.all and self.args.rulename[0]:
            print("You may specify either a single rule or --all, but not both.")
            return 1

        #Dynamically import the shared rule_util module.
        util_path = os.path.join(rdk_dir, "rule_util.py")
        imp.load_source('rule_util', util_path)

        #Construct our list of rules to test.
        rule_names = self.get_rule_list_for_command()

        for rule_name in rule_names:
            #Dynamically import the custom rule code, so that we can run the evaluate_compliance function.
            module_path = os.path.join(".", os.path.dirname(rules_dir), rule_name, rule_name+".py")
            module_name = str(rule_name).lower()
            module = imp.load_source(module_name, module_path)

            #Get CI JSON from either the CLI or one of the stored templates.
            my_ci = {}
            if self.args.test_ci_json:
                my_ci = self.args.test_ci_json
            else:
                if self.args.test_ci_type:
                    my_ci_obj = TestCI(self.args.test_ci_type)
                    my_ci = my_ci_obj.get_json()
                else:
                    print("You must specify either a test CI resource type or provide a valid JSON document")
                    return 1

            #Get Config parameters from the CLI if provided, otherwise leave dict empty.
            #TODO: currently very picky about JSON punctuation - can we make this more generous on inputs?
            my_parameters = {}
            if self.args.test_parameters:
                print (self.args.test_parameters)
                my_parameters = json.loads(self.args.test_parameters)

            #Execute the evaluate_compliance function
            print(my_ci)
            print(my_parameters)
            result = getattr(module, 'evaluate_compliance')(my_ci, my_parameters)
            print(result)

        return 0

    def test_remote(self):
        print ("Running test_remote!")
        return 0

    def status(self):
        print ("Running status!")
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

    def get_rule_list_for_command(self):
        rule_names = []
        if self.args.all:
            for dir_name in os.listdir('.'):
                code_file = dir_name + ".py"
                if code_file in os.listdir(dir_name):
                    rule_names.append(dir_name)
        else:
            rule_names.append(self.args.rulename[0])

        return rule_names

class TestCI():
    def __init__(self, ci_type):
        #convert ci_type string to filename format
        ci_file = ci_type.replace('::','_') + '.json'
        self.ci_json = json.load(open(os.path.join(rdk_dir, example_ci_dir, ci_file), 'r'))

    def get_json(self):
        return self.ci_json
