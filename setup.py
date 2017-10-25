from setuptools import setup

def readme():
    with open('README.rst') as f:
        return f.read()

setup(name='rdk',
      version='0.2.4',
      description='Rule Development Kit CLI for AWS Config',
      long_description=readme(),
      url='https://github.com/michaelborchert/rdk',
      author='Michael Borchert',
      author_email='mborch@amazon.com',
      license='Apache License Version 2.0',
      packages=['rdk'],
      install_requires=[
          'boto3',
      ],
      scripts=['bin/rdk'],
      zip_safe=False,
      include_package_data=True)
