import os
from os import path
import sys
import shutil
import boto3
import json
import time
import imp
import argparse
from botocore.exceptions import ClientError
from datetime import datetime
import base64

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
test_ci_filename = 'test_ci.json'
event_template_filename = 'test_event_template.json'

class rdk():
    def __init__(self, args):
        self.args = args

    def process_command(self):
        method_to_call = getattr(self, self.args.command.replace('-','_'))
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
        src = os.path.join(path.dirname(__file__), 'template')
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
            my_s3.create_bucket(
                Bucket=config_bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': my_session.region_name
                }
            )

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
            my_s3.create_bucket(
                Bucket=code_bucket_name,
                CreateBucketConfiguration={
                    'LocationConstraint': my_session.region_name
                }
            )

        #make sure lambda execution role exists - TODO
        return 0

    #TODO: roll-back directory creation on failure.
    def create(self):
        print ("Running create!")

        #Parse the command-line arguments relevant for creating a Config Rule.
        self._parse_rule_args()

        if not self.args.runtime:
            print("Runtime is required for 'create' command.")
            return 1

        #create rule directory.
        rule_path = os.path.join(os.getcwdu(), rules_dir, self.args.rulename)
        if os.path.exists(rule_path):
            print("Rule already exists.")
            return 1

        os.makedirs(os.path.join(os.getcwdu(), rules_dir, self.args.rulename))

        #copy rule.py template into rule directory
        src = os.path.join(os.getcwdu(), rdk_dir, rule_handler)
        dst = os.path.join(os.getcwdu(), rules_dir, self.args.rulename, self.args.rulename+".py")
        shutil.copyfile(src, dst)

        src = os.path.join(os.getcwdu(), rdk_dir, util_filename)
        dst = os.path.join(os.getcwdu(), rules_dir, self.args.rulename, util_filename)
        shutil.copyfile(src, dst)

        #Write the parameters to a file in the rule directory.
        self._write_params_file()

        print ("Local Rule files created.")
        return 0

    def modify(self):
        #TODO: Allow for modifying a single attribute
        print("Running modify!")

        #Parse the command-line arguments necessary for modifying a Config Rule.
        self._parse_rule_args()

        #Should no longer be needed
        #if len(self.args.rulename) > 1:
        #    print("'modfy' command requires only one rule name.")
        #    return 1

        if not self.args.runtime:
            print("Runtime is required for 'modify' command.")
            return 1

        #Write the parameters to a file in the rule directory.
        self._write_params_file()

        print ("Modified Rule '"+self.args.rulename+"'")

    def deploy(self):
        #run the deploy code
        print ("Running deploy!")

        parser = argparse.ArgumentParser(prog='rdk create')
        parser.add_argument('rulename', metavar='<rulename>', nargs='*', help='Rule name(s) to deploy')
        parser.add_argument('--all','-a', action='store_true', help="All rules in the working directory will be deployed.")
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
            s3_src_dir = os.path.join(os.getcwdu(), rules_dir, rule_name)
            s3_dst = os.path.join(rule_name, rule_name+".zip")
            s3_src = shutil.make_archive(os.path.join(rule_name, rule_name), 'zip', s3_src_dir)
            code_bucket_name = code_bucket_prefix + account_id
            my_s3 = my_session.resource('s3')

            print ("Uploading " + rule_name)
            my_s3.meta.client.upload_file(s3_src, code_bucket_name, s3_dst)

            #create CFN Parameters
            #read rest of params from file in rule directory
            my_rule_params = self._get_rule_parameters(rule_name)

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
                    'ParameterValue': my_rule_params['SourceRuntime'],
                },
                {
                    'ParameterKey': 'SourceEvents',
                    'ParameterValue': my_rule_params['SourceEvents'],
                },
                {
                    'ParameterKey': 'SourcePeriodic',
                    'ParameterValue': my_rule_params['SourcePeriodic'],
                },
                {
                    'ParameterKey': 'SourceInputParameters',
                    'ParameterValue': my_rule_params['InputParameters'],
                }]

            #deploy config rule TODO: better detection of existing rules and update/create decision logic
            cfn_body = os.path.join(os.getcwdu(), rdk_dir, "configRole.json")
            my_cfn = my_session.client('cloudformation')

            try:
                my_stack = my_cfn.describe_stacks(StackName=rule_name)
                #If we've gotten here, stack exists and we should update it.
                print ("Updating CloudFormation Stack for " + rule_name)
                try:
                    response = my_cfn.update_stack(
                        StackName=rule_name,
                        TemplateBody=open(cfn_body, "r").read(),
                        Parameters=my_params,
                        Capabilities=[
                            'CAPABILITY_IAM',
                        ],
                    )
                except ClientError as e:
                    if e.response['Error']['Code'] == 'ValidationError':
                        if 'No updates are to be performed.' in str(e):
                            #No changes made to Config rule definition, so CloudFormation won't do anything.
                            print("No changes to Config Rule.")
                        else:
                            #Something unexpected has gone wrong.  Emit an error and bail.
                            print(e)
                            return 1
                    else:
                        raise

                my_lambda_arn = self._get_lambda_arn_for_rule(rule_name)

                print("Publishing Lambda code...")
                my_lambda_client = my_session.client('lambda')
                my_lambda_client.update_function_code(
                    FunctionName=my_lambda_arn,
                    S3Bucket=code_bucket_name,
                    S3Key=s3_dst,
                    Publish=True
                )
                print("Lambda code updated.")
                return 0
            except ClientError as e:
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

            #wait for changes to propagate. TODO: detect and report failures
            self._wait_for_cfn_stack(my_cfn, rule_name)

        print('Config deploy complete.')

        return 0

    def test_local(self):
        print ("Running test_local!")
        self._parse_test_args()

        #Dynamically import the shared rule_util module.
        util_path = os.path.join(rdk_dir, "rule_util.py")
        imp.load_source('rule_util', util_path)

        #Construct our list of rules to test.
        rule_names = self.get_rule_list_for_command()

        for rule_name in rule_names:
            print("Testing "+rule_name)
            #Dynamically import the custom rule code, so that we can run the evaluate_compliance function.
            module_path = os.path.join(".", os.path.dirname(rules_dir), rule_name, rule_name+".py")
            module_name = str(rule_name).lower()
            module = imp.load_source(module_name, module_path)

            #Get CI JSON from either the CLI or one of the stored templates.
            my_cis = self._get_test_CIs(rule_name)

            #Get Config parameters from the CLI if provided, otherwise leave dict empty.
            #TODO: currently very picky about JSON punctuation - can we make this more generous on inputs?
            #TODO: Need better error outputs to make it clear that issues are in the lambda code, not the RDK.
            my_parameters = {}
            if self.args.test_parameters:
                #print (self.args.test_parameters)
                my_parameters = json.loads(self.args.test_parameters)

            #Execute the evaluate_compliance function
            for my_ci in my_cis:
                #print(my_ci)
                #print(my_parameters)
                print ("\t\tTesting CI " + my_ci['resourceType'])
                result = getattr(module, 'evaluate_compliance')(my_ci, my_parameters)
                print("\t\t\t"+result)

        return 0

    def test_remote(self):
        print ("Running test_remote!")
        self._parse_test_args()

        #Construct our list of rules to test.
        rule_names = self.get_rule_list_for_command()

        #Create our Lambda client.
        my_session = self.get_boto_session()
        my_lambda_client = my_session.client('lambda')

        for rule_name in rule_names:
            print("Testing "+rule_name)

            #Get CI JSON from either the CLI or one of the stored templates.
            my_cis = self._get_test_CIs(rule_name)

            my_parameters = {}
            if self.args.test_parameters:
                #print (self.args.test_parameters)
                my_parameters = json.loads(self.args.test_parameters)

            for my_ci in my_cis:
                print ("\t\tTesting CI " + my_ci['resourceType'])

                #Generate test event from templates
                test_event = json.load(open(os.path.join(os.getcwdu(), rdk_dir, event_template_filename), 'r'), strict=False)
                my_invoking_event = json.loads(test_event['invokingEvent'])
                my_invoking_event['configurationItem'] = my_ci
                my_invoking_event['notificationCreationTime'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
                test_event['invokingEvent'] = json.dumps(my_invoking_event)
                test_event['ruleParameters'] = json.dumps(my_parameters)

                #Get the Lambda function associated with the Rule
                my_lambda_arn = self._get_lambda_arn_for_rule(rule_name)

                #Call Lambda function with test event.
                result = my_lambda_client.invoke(
                    FunctionName=my_lambda_arn,
                    InvocationType='RequestResponse',
                    LogType='Tail',
                    Payload=json.dumps(test_event)
                )

                #If there's an error dump execution logs to stdout, if not print out the value returned by the lambda function.
                if 'FunctionError' in result:
                    print(base64.b64decode(str(result['LogResult'])))
                else:
                    print("\t\t\t" + result['Payload'].read())
                    if self.args.verbose:
                        print(base64.b64decode(str(result['LogResult'])))
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
            d = '.'
            for obj_name in os.listdir('.'):
                if os.path.isdir(os.path.join('.', obj_name)) and not obj_name == 'rdk':
                    code_file = obj_name + ".py"
                    if code_file in os.listdir(obj_name):
                        rule_names.append(obj_name)
        else:
            rule_names.append(self.args.rulename[0])

        return rule_names

    def _get_rule_parameters(self, rule_name):
        params_file_path = os.path.join(os.getcwdu(), rules_dir, rule_name, parameter_file_name)
        parameters_file = open(params_file_path, 'r')
        my_json = json.load(parameters_file)
        parameters_file.close()
        return my_json['Parameters']

    def _parse_rule_args(self):
        parser = argparse.ArgumentParser(prog='rdk '+self.args.command)
        parser.add_argument('--runtime','-R', required=True, help='Runtime for lambda function', choices=['nodejs','nodejs4.3','nodejs6.10','java8','python2.7','python3.6','dotnetcore1.0','nodejs4.3-edge'])
        parser.add_argument('--periodic','-P', help='Execution period', choices=['One_Hour','Three_Hours','Six_Hours','Twelve_Hours','TwentyFour_Hours'])
        parser.add_argument('--event','-E', required=True, help='Resources that trigger event-based rule evaluation') #TODO - add full list of supported resources
        parser.add_argument('--input-parameters', '-i', help="[optional] JSON for Config parameters for testing.")
        parser.add_argument('rulename', metavar='<rulename>', help='Rule name to create/modify')
        self.args = parser.parse_args(self.args.command_args, self.args)

    def _parse_test_args(self):
        parser = argparse.ArgumentParser(prog='rdk '+self.args.command)
        parser.add_argument('rulename', metavar='<rulename>[,<rulename>,...]', nargs='*', help='Rule name(s) to test')
        parser.add_argument('--all','-a', action='store_true', help="Test will be run against all rules in the working directory.")
        parser.add_argument('--test-ci-json', '-j', help="[optional] JSON for test CI for testing.")
        parser.add_argument('--test-ci-types', '-t', help="[optional] CI type to use for testing.")
        parser.add_argument('--test-parameters', '-p', help="[optional] JSON for Config parameters for testing.")
        parser.add_argument('--verbose', '-v', action='store_true', help='Enable full log output')
        self.args = parser.parse_args(self.args.command_args, self.args)

        if self.args.all and self.args.rulename:
            print("You may specify either specific rules or --all, but not both.")
            return 1

    def _write_params_file(self):
        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        #get accountID
        my_sts = my_session.client('sts')
        response = my_sts.get_caller_identity()
        account_id = response['Account']

        #create config file and place in rule directory
        parameters = {
            'RuleName': self.args.rulename,
            'SourceRuntime': self.args.runtime,
            'CodeBucket': code_bucket_prefix + account_id,
            'CodeKey': self.args.rulename+'.zip',
            'InputParameters': self.args.input_parameters
        }

        if self.args.event:
            parameters['SourceEvents'] = self.args.event
        if self.args.periodic:
            parameters['SourcePeriodic'] = self.args.periodic

        my_params = {"Parameters": parameters}
        params_file_path = os.path.join(os.getcwdu(), rules_dir, self.args.rulename, parameter_file_name)
        parameters_file = open(params_file_path, 'w')
        json.dump(my_params, parameters_file, indent=2)
        parameters_file.close()

    def _wait_for_cfn_stack(self, cfn_client, stackname):
        in_progress = True
        while in_progress:
            my_stack = cfn_client.describe_stacks(StackName=stackname)
            #print(my_stack)
            if 'IN_PROGRESS' not in my_stack['Stacks'][0]['StackStatus']:
                in_progress = False
            else:
                print("Waiting for CloudFormation stack operation to complete...")
                time.sleep(5)

    def _get_test_CIs(self, rulename):
        test_ci_list = []
        if self.args.test_ci_json:
            print ("Testing with supplied CI JSON - NOT YET IMPLEMENTED") #TODO
            #if "file://" in self.args.test_ci_json:
            #    tests_path  = os.path.join(os.path.dirname(str(self.args.test_ci_json).replace('file://','')))
            #    if os.path.exists(test_path):
            #        test_ci_list = self._load_cis_from_file(test_path)
            #    else:
            #        print("Could not find specified file.")
            #        sys.exit(1)
            #else:
            #    test_ci_list = json.loads()
        elif self.args.test_ci_types:
            print("\tTesting with generic CI for supplied Resource Type(s)")
            ci_types = self.args.test_ci_types.split(",")
            for ci_type in ci_types:
                my_test_ci = TestCI(ci_type)
                test_ci_list.append(my_test_ci.get_json())
        else:
            #Check to see if there is a test_ci.json file in the Rule directory
            tests_path = os.path.join(os.getcwdu(), rules_dir, rulename, test_ci_filename)
            if os.path.exists(tests_path):
                print("\tTesting with CI's provided in test_ci.json file. NOT YET IMPLEMENTED") #TODO
            #    test_ci_list self._load_cis_from_file(tests_path)
            else:
                print("\tTesting with generic CI for configured Resource Type(s)")
                my_rule_params = self._get_rule_parameters(rulename)
                ci_types = str(my_rule_params['SourceEvents']).split(",")
                for ci_type in ci_types:
                    my_test_ci = TestCI(ci_type)
                    test_ci_list.append(my_test_ci.get_json())

        return test_ci_list

    def _get_lambda_arn_for_rule(self, rulename):
        #create custom session based on whatever credentials are available to us
        my_session = self.get_boto_session()

        my_cfn = my_session.client('cloudformation')

        #Since CFN won't detect changes to the lambda code stored in S3 as a reason to update the stack, we need to manually update the code reference in Lambda once the CFN has run.
        self._wait_for_cfn_stack(my_cfn, rulename)

        #Lamba function is an output of the stack.
        my_updated_stack = my_cfn.describe_stacks(StackName=rulename)
        cfn_outputs = my_updated_stack['Stacks'][0]['Outputs']
        my_lambda_arn = 'NOTFOUND'
        for output in cfn_outputs:
            if output['OutputKey'] == 'RuleCodeLambda':
                my_lambda_arn = output['OutputValue']

        if my_lambda_arn == 'NOTFOUND':
            print("Could not read CloudFormation stack output to find Lambda function.")
            sys.exit(1)

        return my_lambda_arn

    #def _load_cis_from_file(self, filename):
    #    my_cis = []
    #    return my_cis

class TestCI():
    def __init__(self, ci_type):
        #convert ci_type string to filename format
        ci_file = ci_type.replace('::','_') + '.json'
        self.ci_json = json.load(open(os.path.join(rdk_dir, example_ci_dir, ci_file), 'r'))

    def get_json(self):
        return self.ci_json
