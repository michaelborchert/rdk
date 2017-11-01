rdk
===
Rule Development Kit - Version 2
Extremely Alpha.  Do not use if you haven't personally talked to me.

The RDK is designed to support a "Compliance-as-Code" workflow that is intuitive and productive.  It abstracts away much of the undifferentiated heavy lifting associated with deploying AWS Config rules backed by custom lambda functions, and provides a streamlined dev-test-deploy iterative process.

Getting Started
===============
Uses python 2.7 and is installed via pip.  Requires you to have an AWS account and sufficient permissions to manage the Config service, and to create S3 Buckets, Roles, and Lambda Functions.  Under the hood, rdk uses boto3 to make API calls to AWS, so you can set your credentials any way that boto3 recognizes (options 3 through 8 here: http://boto3.readthedocs.io/en/latest/guide/configuration.html) or pass them in with the command-line parameters --profile, --region, --access-key, or --secret-access-key

If you just want to use the RDK, go ahead and install it using pip::

$ pip install rdk

Alternately, if you want to see the code and/or contribute you can clone the git repo, and then from the repo directory use pip to install the package.  Use the '-e' flag to generate symlinks so that any edits you make will be reflected when you run the installed package.

::

  $ pip install -e .

To make sure the rdk is installed correctly, running the package from the command line without any arguments should display help information.

::

  $ rdk
  usage: rdk [-h] [--profile PROFILE] [--access-key ACCESS_KEY]
           [--secret-access-key SECRET_ACCESS_KEY] [--region REGION]
           [--verbose]
           <command> ...
  rdk: error: too few arguments

Usage
=====

Configure your env
------------------
To use the RDK, create a directory that will be your working directory.  This should be committed to a source code repo.  In that directory, run the ``init`` command to set up your AWS Config environment and copy template files into a .rdk directory in your working directory.

::

  $ rdk init
  Running init!
  Waiting for IAM role to propagate
  Config setup complete.
  Config Service is ON

Create Rules
------------
In your working directory, use the ``create`` command to start creating a new custom rule.  You must specify the runtime for the lambda function that will back the Rule, and you must also specify a resource type (or comma-separated list of types) that the Rule will evaluate.  This will add a new directory for the rule and populate it with several files, including a skeleton of your Lambda code.

::

  $ rdk create MyRule --runtime python2.7 --periodic One_Hour --input-parameters '{"desiredInstanceType":"t2.micro"}' --event AWS::EC2::Instance
  Running create!

Edit and Test Rules Locally
---------------------------
Once you have created the rule, edit the python file in your rule directory (in the above example it would be ``MyRule/MyRule.py``) to add whatever logic your Rule requires in the ``evaluate_compliance`` function.  You will have access to the CI that was sent by Config, as well as any parameters configured for the Config Rule.  Your function should return either ``COMPLIANT``, ``NONCOMPLIANT``, or ``NOT_APPLICABLE``.

While you are editing your Rule code you can test against generic CI's (custom CI specification is coming) using the ``test-local`` command::

  $ rdk test-local MyRule --test-parameters '{"desiredInstanceType":"t2.micro"}'
  Running test_local!
  Testing MyRule
  	Testing with generic CI for configured Resource Type(s)
  		Testing CI AWS::EC2::Instance
  			COMPLIANT

you can run the same test on all Rules in the working directory using the ``--all`` flag.

If you want to see what the JSON structure of a CI looks like for creating your logic, you can use

::

$ rdk sample-ci <Resource Type>

to dump a formatted JSON document.


Modify Rule
-----------
If you need to change the parameters of a Config rule in your working directory you can use the ``modify`` command.  Any parameters you specify will overwrite existing values, any that you do not specify will not be changed.

::

  $ rdk modify MyRule --runtime python2.7 --periodic TwentyFour_Hours --input-parameters '{"desiredInstanceType":"t2.micro"}'
  Running modify!
  Modified Rule 'MyRule'

It is worth noting that until you actually call the ``deploy`` command your rule only exists in your working directory, none of the Rule commands discussed thus far actually makes changes to your account.

Deploy Rule
-----------
Once you have completed your compliance validation code and set your Rule's configuration, you can deploy the Rule to your account using the ``deploy`` command.  This will zip up your code (and the other associated code files) into a deployable package, copy that Zip file to S3, and then launch or update a CloudFormation stack that defines your Config Rule, Lambda function, and the necessary permissions and IAM Roles for it to function.  Since CloudFormation does not deeply inspect Lambda code objects in S3 to construct its changeset, the ``deploy`` command will also directly update the Lambda function for any subsequent deployments to make sure code changes are propagated correctly.

::

  $ rdk deploy MyRule
  Running deploy!
  Zipping MyRule
  Uploading MyRule
  Creating CloudFormation Stack for MyRule
  Waiting for CloudFormation stack operation to complete...
  ...
  Waiting for CloudFormation stack operation to complete...
  Config deploy complete.

Just like with ``test-local``, you can use the --all flag to deploy all of the rules in your working directory.

Test Deployed Rule
------------------
Work in progress.  Currently you can use the ``test-remote`` command to exercise the Lambda function that's been created, however there are still some issues to work out.

Running the tests
=================

No tests yet.

Contributing
============

email me at mborch@amazon.com if you are interested in contributing.

Versioning
==========

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the [tags on this repository](https://github.com/your/project/tags).

Authors
=======

* **Greg Kim and Chris Gutierrez** - *Initial work and CI definitions*
* **Michael Borchert** - *Python version*
* **Henry Huang** - *CFN templates and other code*
* **Jonathan Rault** - *Design, testing, feedback*

See also the list of [contributors](https://github.com/your/project/contributors) who participated in this project.

License
=======

This project is licensed under the Apache 2.0 License - see the [LICENSE.md](LICENSE.md) file for details

Acknowledgments
===============

* the boto3 team makes all of this magic possible.
