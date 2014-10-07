# Copyright 2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import dateutil
import datetime

from cement.utils.misc import minimal_logger

from ebcli.core import io
from ebcli.objects.solutionstack import SolutionStack
from ebcli.objects.exceptions import NotFoundError, InvalidStateError, \
    AlreadyExistsError
from ebcli.objects.tier import Tier
from ebcli.lib import utils
from ebcli.lib import aws
from ebcli.lib.aws import InvalidParameterValueError
from ebcli.objects.event import Event
from ebcli.objects.environment import Environment
from ebcli.objects.application import Application
from ebcli.resources.strings import strings, responses

LOG = minimal_logger(__name__)


DEFAULT_ROLE_NAME = 'aws-elasticbeanstalk-ec2-role'


def _make_api_call(operation_name, region=None, **operation_options):

    return aws.make_api_call('elasticbeanstalk',
                               operation_name,
                               region=region,
                               **operation_options)


def create_application(app_name, descrip, region=None):
    LOG.debug('Inside create_application api wrapper')
    try:
        result = _make_api_call('create-application',
                                  application_name=app_name,
                                  description=descrip,
                                  region=region)
    except InvalidParameterValueError as e:
        if e.message == responses['app.exists'].replace('{app-name}',
                                                        app_name):
            raise AlreadyExistsError(e.message)
        else:
            raise e

    return result


def create_application_version(app_name, vers_label, descrip, s3_bucket,
                               s3_key, region=None):
    LOG.debug('Inside create_application_version api wrapper')
    return _make_api_call('create-application-version',
                          application_name=app_name,
                          version_label=vers_label,
                          description=descrip,
                          source_bundle={'S3Bucket': s3_bucket,
                                         'S3Key': s3_key},
                          region=region)


def create_environment(app_name, env_name, cname, description, solution_stck,
                       tier, label, single, key_name, profile, region=None):
    """
    Creates an Elastic Beanstalk environment
    :param app_name: Name of application where environment will live
    :param env_name: Desired name of environment
    :param cname: cname prefix, if None, a cname will be auto-generated
    :param description: a string description (optional)
    :param solution_stck: a solution_stack object
    :param tier: a tier object
    :param label: version label of app version to deploy. If None, a
                        sample app will be launched
    :param single: True if you would like environment to be a SingleInstance.
                            If False, the environment will be launched as LoadBalanced
    :param key_name: EC2 SSH Keypair name
    :param profile: IAM Instance profile name
    :param region: region in which to create the environment
    :return: environment_object, request_id
    """
    LOG.debug('Inside create_environment api wrapper')

    assert app_name is not None, 'App name can not be empty'
    assert env_name is not None, 'Environment name can not be empty'
    assert solution_stck is not None, 'Solution stack can not be empty'

    settings = []

    # ToDo : should we default to t2.micro?

    kwargs = {
        'application_name': app_name,
        'environment_name': env_name,
        'solution_stack_name': solution_stck.name,
        'option_settings': settings,
    }
    if description:
        kwargs['description'] = description
    if cname:
        kwargs['cname_prefix'] = cname
    if tier:
        kwargs['tier'] = tier.to_struct()
    if label:
        kwargs['version_label'] = label
    if profile:
        settings.append(
            {'Namespace': 'aws:autoscaling:launchconfiguration',
             'OptionName': 'IamInstanceProfile',
             'Value': profile}
        )
    if single:
        settings.append(
            {'Namespace': 'aws:elasticbeanstalk:environment',
             'OptionName': 'EnvironmentType',
             'Value': 'SingleInstance'}
        )
    if key_name:
        settings.append(
            {'Namespace': 'aws:autoscaling:launchconfiguration',
            'OptionName': 'EC2KeyName',
            'Value': key_name},
        )

    result = _make_api_call('create-environment', region=region, **kwargs)

    # convert to object
    env = _api_to_environment(result)
    request_id = result['ResponseMetadata']['RequestId']
    return env, request_id


def clone_environment(app_name, env_name, clone_name, cname,
                      description, region=None):
    LOG.debug('Inside clone_environment api wrapper')

    assert app_name is not None, 'App name can not be empty'
    assert env_name is not None, 'Environment name can not be empty'
    assert clone_name is not None, 'Clone name can not be empty'

    settings = []

    kwargs = {
        'application_name': app_name,
        'environment_name': clone_name,
        'template-specification': [{'template-source':{'environment-name':env_name,}}],
    }
    if description:
        kwargs['description'] = description
    if cname:
        kwargs['cname_prefix'] = cname

    result = _make_api_call('create-environment', region=region, **kwargs)

    # convert to object
    env = _api_to_environment(result)
    request_id = result['ResponseMetadata']['RequestId']
    return env, request_id


def _api_to_environment(api_dict):
    try:
        cname = api_dict['CNAME']
    except KeyError:
        cname = 'UNKNOWN'
    try:
        version_label = api_dict['VersionLabel']
    except KeyError:
        version_label = None
    try:
        description = api_dict['Description']
    except KeyError:
        description = None

    # Convert solution_stack and tier to objects
    solution_stack = SolutionStack(api_dict['SolutionStackName'])
    tier = api_dict['Tier']
    tier = Tier(tier['Name'], tier['Type'], tier['Version'])

    env = Environment(
        version_label=version_label,
        status=api_dict['Status'],
        app_name=api_dict['ApplicationName'],
        health=api_dict['Health'],
        id=api_dict['EnvironmentId'],
        date_updated=api_dict['DateUpdated'],
        solution_stack=solution_stack,
        description=description,
        name=api_dict['EnvironmentName'],
        date_created=api_dict['DateCreated'],
        tier=tier,
        cname=cname,
    )
    return env


def delete_application(app_name, region=None):
    LOG.debug('Inside delete_application api wrapper')
    result = _make_api_call('delete-application',
                            application_name=app_name,
                            region=region)
    return result['ResponseMetadata']['RequestId']


def delete_application_and_envs(app_name, region=None):
    LOG.debug('Inside delete_application_and_envs')
    result = _make_api_call('delete-application',
                          application_name=app_name,
                          terminate_env_by_force=True,
                          region=region)
    return result['ResponseMetadata']['RequestId']


def describe_application(app_name, region=None):
    LOG.debug('Inside describe_application api wrapper')
    result = _make_api_call('describe-applications',
                            application_names=[app_name],
                            region=region)
    apps = result['Applications']
    if len(apps) != 1:
        raise NotFoundError('Application not found')
    return apps[0]


def is_cname_available(cname, region=None):
    LOG.debug('Inside is_cname_available api wrapper')
    result = _make_api_call('check-dns-availability',
                            cname_prefix=cname,
                            region=region)
    return result['Available']


def describe_applications(region=None):
    LOG.debug('Inside describe_applications api wrapper')
    result = _make_api_call('describe-applications', region=region)
    return result['Applications']


def describe_configuration_settings(app_name, env_name, region=None):
    LOG.debug('Inside describe_configuration_settings api wrapper')
    result = _make_api_call('describe-configuration-settings',
                            application_name=app_name,
                            environment_name=env_name,
                            region=region)
    return result['ConfigurationSettings'][0]


def get_available_solution_stacks(region=None):
    LOG.debug('Inside get_available_solution_stacks api wrapper')
    result = _make_api_call('list-available-solution-stacks', region=region)
    stack_strings = result['SolutionStacks']

    LOG.debug('Solution Stack result size = ' + str(len(stack_strings)))
    if len(stack_strings) == 0:
        raise NotFoundError(strings['sstacks.notfound'])

    solution_stacks = []
    for s in stack_strings:
        stack = SolutionStack(s)
        solution_stacks.append(stack)

    return solution_stacks


def get_application_versions(app_name, region=None):
    LOG.debug('Inside get_application_versions api wrapper')
    result = _make_api_call('describe-application-versions',
                            application_name=app_name,
                            region=region)
    return result['ApplicationVersions']


def get_all_applications(region=None):
    LOG.debug('Insise get_all_applications api wrapper')
    result = _make_api_call('describe-applications',
                            region=region)
    app_list = []
    for app in result['Applications']:
        try:
            description = app['Description']
        except KeyError:
            description = None

        try:
            versions = app['Versions']
        except KeyError:
            versions = None
        app_list.append(
            Application(
                name=app['ApplicationName'],
                date_created=app['DateCreated'],
                date_updated=app['DateUpdated'],
                description=description,
                versions=versions,
                templates=app['ConfigurationTemplates'],
            )
        )

    return app_list


def get_all_environments(app_name, region=None):
    LOG.debug('Inside get_all_environments api wrapper')
    result = _make_api_call('describe-environments',
                          application_name=app_name,
                          region=region)
    # convert to object
    envs = []
    for env in result['Environments']:
        envs.append(_api_to_environment(env))
    return envs


def get_environment(app_name, env_name, region=None):
    LOG.debug('Inside get_environment api wrapper')
    result = _make_api_call('describe-environments',
                          application_name=app_name,
                          environment_names=[env_name],
                          region=region)

    envs = result['Environments']
    if len(envs) < 1:
        raise NotFoundError('Environment ' + env_name + ' Not Found')
    else:
        return _api_to_environment(envs[0])


def get_environment_resources(env_name, region=None):
    LOG.debug('Inside get_environment_resources api wrapper')
    result = _make_api_call('describe-environment-resources',
                            environment_name=env_name,
                            region=region)
    return result


def get_new_events(app_name, env_name, request_id,
                   last_event_time=None, region=None):
    LOG.debug('Inside get_new_events api wrapper')
    # make call
    if last_event_time is not None:
        time = last_event_time
        new_time = time + datetime.timedelta(0, 0, 1000)
    else:
        new_time = None
    kwargs = {}
    if app_name:
        kwargs['application_name'] = app_name
    if env_name:
        kwargs['environment_name'] = env_name
    if request_id:
        kwargs['request_id'] = request_id
    if new_time:
        kwargs['start_time'] = str(new_time)

    result = _make_api_call('describe-events',
                          region=region,
                          **kwargs)

    # convert to object
    events = []
    for event in result['Events']:
        try:
            version_label = event['VersionLabel']
        except KeyError:
            version_label = None

        try:
            environment_name = event['EnvironmentName']
        except KeyError:
            environment_name = None

        events.append(
            Event(message=event['Message'],
                  event_date=event['EventDate'],
                  version_label=version_label,
                  app_name=event['ApplicationName'],
                  environment_name=environment_name,
                  severity=event['Severity'],
                  )
        )
    return events


def get_storage_location(region=None):
    LOG.debug('Inside get_storage_location api wrapper')
    response = _make_api_call('create-storage-location', region=region)
    return response['S3Bucket']


def update_environment(env_name, options, region=None, remove=[]):
    LOG.debug('Inside update_environment api wrapper')
    try:
        response = _make_api_call('update-environment',
                              environment_name=env_name,
                              option_settings=options,
                              options_to_remove=remove,
                              region=region)
    except aws.InvalidParameterValueError as e:
        if e.message == responses['env.invalidstate'].replace('{env-name}',
                                                              env_name):
            raise InvalidStateError(e.message)
    return response['ResponseMetadata']['RequestId']


def update_env_application_version(env_name,
                                   version_label, region=None):
    LOG.debug('Inside update_env_application_version api wrapper')
    response = _make_api_call('update-environment',
                              environment_name=env_name,
                              version_label=version_label,
                              region=region)
    return response['ResponseMetadata']['RequestId']


def request_environment_info(env_name, info_type, region=None):
    result = _make_api_call('request-environment-info',
                          environment_name=env_name,
                          info_type=info_type,
                          region=region)
    return result


def retrieve_environment_info(env_name, info_type, region=None):
    result = _make_api_call('retrieve-environment-info',
                          environment_name=env_name,
                          info_type=info_type,
                          region=region)
    return result


def terminate_environment(env_name, region=None):
    result = _make_api_call('terminate-environment',
                            environment_name=env_name,
                            region=region)
    return result['ResponseMetadata']['RequestId']