#!/usr/bin/env python
# Copyright 2015-2017 Yelp Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import
from __future__ import unicode_literals

import argparse

from paasta_tools.cli.utils import figure_out_service_name
from paasta_tools.cli.utils import lazy_choices_completer
from paasta_tools.cli.utils import list_instances
from paasta_tools.cli.utils import list_clusters
from paasta_tools.cli.utils import list_services

from paasta_tools.utils import load_system_paasta_config
from paasta_tools.utils import paasta_print
from paasta_tools.utils import PaastaColors
from paasta_tools.utils import PaastaNotConfiguredError
from paasta_tools.utils import SystemPaastaConfig
from paasta_tools.utils import DEFAULT_SOA_DIR
from paasta_tools.utils import validate_service_instance

from paasta_tools.native_mesos_scheduler import create_driver_with
from paasta_tools.native_mesos_scheduler import compose_job_id
from paasta_tools.native_mesos_scheduler import load_paasta_native_job_config
from paasta_tools.frameworks.adhoc_scheduler import PaastaAdhocScheduler

def add_remote_run_args(parser):
    parser.add_argument(
        '-s', '--service',
        help='The name of the service you wish to inspect',
    ).completer = lazy_choices_completer(list_services)
    parser.add_argument(
        '-c', '--cluster',
        help=("The name of the cluster you wish to run your task on. "
              "If omitted, uses the default cluster defined in the paasta remote-run configs"),
    ).completer = lazy_choices_completer(list_clusters)
    parser.add_argument(
        '-y', '--yelpsoa-config-root',
        dest='yelpsoa_config_root',
        help='A directory from which yelpsoa-configs should be read from',
        default=DEFAULT_SOA_DIR,
    )
    parser.add_argument(
        '--json-dict',
        help='When running dry run, output the arguments as a json dict',
        action='store_true',
        dest='dry_run_json_dict',
    )
    parser.add_argument(
        '-C', '--cmd',
        help=('Run Docker container with particular command, '
              'for example: "bash". By default will use the command or args specified by the '
              'soa-configs or what was specified in the Dockerfile'),
        required=False,
        default=None,
    )
    parser.add_argument(
        '-i', '--instance',
        help=("Simulate a docker run for a particular instance of the service, like 'main' or 'canary'"),
        required=False,
        default=None,
    ).completer = lazy_choices_completer(list_instances)
    parser.add_argument(
        '-v', '--verbose',
        help='Show Docker commands output',
        action='store_true',
        required=False,
        default=True,
    )
    parser.add_argument(
        '-d', '--dry-run',
        help='Don\'t launch the task',
        action='store_true',
        required=False,
        default=False,
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(description='')
    add_remote_run_args(parser)
    return parser.parse_args(argv)


class UnknownPaastaRemoteServiceError(Exception):
    pass


def make_config_reader(instance_type):
    def reader(service, instance, cluster, soa_dir=DEFAULT_SOA_DIR):
        conf_file = '%s-%s' % (instance_type, cluster)
        full_path = '%s/%s/%s.yaml' % (soa_dir, service, conf_file)
        paasta_print("Reading paasta-remote configuration file: %s" % full_path)
        config = service_configuration_lib.read_extra_service_information(service, conf_file, soa_dir=soa_dir)

        if instance not in config:
            raise UnknownPaastaRemoteServiceError(
                'No job named "%s" in config file %s: \n%s' % (instance, full_path, open(full_path).read())
            )

        return config

    return reader


def run_framework(argv=None):
    args = parse_args(argv)
    try:
        system_paasta_config = load_system_paasta_config()
    except PaastaNotConfiguredError:
        paasta_print(
            PaastaColors.yellow(
                "Warning: Couldn't load config files from '/etc/paasta'. This indicates"
                "PaaSTA is not configured locally on this host, and remote-run may not behave"
                "the same way it would behave on a server configured for PaaSTA."
            ),
            sep='\n',
        )
        system_paasta_config = SystemPaastaConfig({"volumes": []}, '/etc/paasta')

    service = figure_out_service_name(args, soa_dir=args.yelpsoa_config_root)
    cluster = args.cluster or system_paasta_config.get_local_run_config().get('default_cluster', None)

    if not cluster:
        paasta_print(
            PaastaColors.red(
                "PaaSTA on this machine has not been configured with a default cluster."
                "Please pass one using '-c'."),
            sep='\n',
            file=sys.stderr,
        )
        return 1

    soa_dir = args.yelpsoa_config_root
    dry_run = args.dry_run
    instance = args.instance
    command = args.cmd

    if instance is None:
        instance_type = 'adhoc'
        instance = 'remote'
    else:
        instance_type = validate_service_instance(service, instance, cluster, soa_dir)

    paasta_print('Scheduling a task on Mesos')
    service_config = load_paasta_native_job_config(
        service=service,
        instance=instance,
        cluster=cluster,
        soa_dir=args.yelpsoa_config_root,
        reader_func=make_config_reader(instance_type)
    )
    scheduler = PaastaAdhocScheduler(
        command=command,
        service_config=service_config,
        system_paasta_config=system_paasta_config,
        dry_run=dry_run
    )
    driver = create_driver_with(
        framework_name="paasta-remote %s %s" % (
            compose_job_id(service, instance),
            datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        ),
        scheduler=scheduler,
        system_paasta_config=system_paasta_config,
        implicit_acks=True
    )
    driver.run()
    return scheduler.status


if __name__ == '__main__':
    main()
