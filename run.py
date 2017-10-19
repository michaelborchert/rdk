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
    parser.add_argument('command', metavar='<command>', help='Command to run.', choices=['init', 'create', 'deploy', 'test_local', 'test_remote', 'status'])
    parser.add_argument('command_args', metavar='<command arguments>', nargs=argparse.REMAINDER)

    args = parser.parse_args()

    rdk = rdk.RDK(args)
    return_val = rdk.process_command()
    exit(return_val)
