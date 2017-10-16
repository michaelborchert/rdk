import argparse

from app import rdk

if __name__ == "__main__":
    #Set up command-line argument parser.
    parser = argparse.ArgumentParser(description='CLI for authoring, deploying, and testing custom AWS Config rules.')
    parser.add_argument('--profile','-p', help="[optional] indicate which Profile to use.")
    parser.add_argument('--access-key','-k', help="[optional] Access Key ID to use.")
    parser.add_argument('--secret-access-key', '-s', help="[optional] Secret Access Key to use.")
    parser.add_argument('--region','-r', default='ap-southeast-1', help='Select the region to run against.  Defaults to ap-southeast-1.')
    parser.add_argument('--verbose','-v', action='count')
    parser.add_argument('--all','-a', help="[optional] indicates that the command will be run against all rules in the working directory.")
    parser.add_argument('command', metavar='<command>', help='Command to run.', choices=['init', 'create', 'deploy', 'test_local', 'test_remote', 'status'])
    parser.add_argument('rulename', metavar='<rulename>', nargs='*', help='Rule name(s) (required for some commands)')
    parser.add_argument('--runtime','-R', help='Runtime for lambda function', choices=['nodejs','nodejs4.3','nodejs6.10','java8','python2.7','python3.6','dotnetcore1.0','nodejs4.3-edge'])
    parser.add_argument('--periodic','-P', help='Execution period', choices=['One_Hour','Three_Hours','Six_Hours','Twelve_Hours','TwentyFour_Hours'])
    parser.add_argument('--event','-E', help='Resources that trigger event-based rule evaluation') #TODO - add full list of supported resources
    parser.add_argument('--test-ci-json', '-j', help="JSON for test CI for testing.")
    parser.add_argument('--test-ci-type', '-t', help="CI type to use for testing.")
    parser.add_argument('--test-parameters', '-T', help="JSON for Config parameters for testing.")

    args = parser.parse_args()

    rdk = rdk.RDK(args)
    return_val = rdk.process_command()
    exit(return_val)
