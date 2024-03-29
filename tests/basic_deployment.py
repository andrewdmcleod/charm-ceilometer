# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import amulet
import ceilometerclient.v2.client as ceilo_client

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)

from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)


class CeilometerBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic ceilometer deployment."""

    no_origin = ['memcached', 'percona-cluster', 'rabbitmq-server',
                 'ceph-mon', 'ceph-osd']

    def __init__(self, series, openstack=None, source=None, stable=False):
        """Deploy the entire test environment."""
        super(CeilometerBasicDeployment, self).__init__(series, openstack,
                                                        source, stable)
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        self.exclude_services = ['mongodb', 'memcached']
        if self._get_openstack_release() >= self.xenial_pike:
            # Ceilometer will come up blocked until the ceilometer-upgrade
            # action is run
            self.exclude_services.append("ceilometer")
        self._auto_wait_for_status(exclude_services=self.exclude_services)

        self.d.sentry.wait()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where ceilometer is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        # Note: Revert back to cs:mongodb when it supports current UCA pockets
        #       https://bugs.launchpad.net/charm-ceilometer/+bug/1671865
        this_service = {'name': 'ceilometer'}
        other_services = [
            self.get_percona_service_entry(),
            {'name': 'rabbitmq-server'},
            {'name': 'keystone'},
            {'name': 'glance'},  # to satisfy workload status
            {'name': 'ceilometer-agent'},
            {'name': 'nova-compute'},
            {'name': 'nova-cloud-controller'},
        ]
        if self._get_openstack_release() >= self.xenial_pike:
            other_services.extend([
                {'name': 'gnocchi'},
                {'name': 'memcached', 'location': 'cs:memcached'},
                {'name': 'ceph-mon', 'units': 3},
                {'name': 'ceph-osd', 'units': 3,
                 'storage': {'osd-devices': 'cinder,10G'}}])
        else:
            other_services.append({
                'name': 'mongodb',
                'location': 'cs:~thedac/{}/mongodb'.format(self.series)})
        super(CeilometerBasicDeployment, self)._add_services(
            this_service,
            other_services,
            no_origin=self.no_origin)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'ceilometer:amqp': 'rabbitmq-server:amqp',
            'ceilometer:identity-notifications': 'keystone:'
                                                 'identity-notifications',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'ceilometer:ceilometer-service': 'ceilometer-agent:'
                                             'ceilometer-service',
            'ceilometer-agent:amqp': 'rabbitmq-server:amqp',
            'nova-compute:nova-ceilometer': 'ceilometer-agent:nova-ceilometer',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'glance:identity-service': 'keystone:identity-service',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:amqp': 'rabbitmq-server:amqp',
            'nova-compute:image-service': 'glance:image-service',
            'nova-cloud-controller:shared-db': 'percona-cluster:shared-db',
            'nova-cloud-controller:amqp': 'rabbitmq-server:amqp',
            'nova-cloud-controller:identity-service': 'keystone:'
                                                      'identity-service',
            'nova-cloud-controller:cloud-compute': 'nova-compute:'
                                                   'cloud-compute',
            'nova-cloud-controller:image-service': 'glance:image-service',
        }
        if self._get_openstack_release() >= self.xenial_pike:
            additional_relations = {
                'ceilometer:metric-service': 'gnocchi:metric-service',
                'ceph-mon:osd': 'ceph-osd:mon',
                'gnocchi:identity-service': 'keystone:identity-service',
                'gnocchi:shared-db': 'percona-cluster:shared-db',
                'gnocchi:storage-ceph': 'ceph-mon:client',
                'gnocchi:coordinator-memcached': 'memcached:cache',
            }

            if self._get_openstack_release() >= self.xenial_queens:
                identity_relations = {'ceilometer:identity-credentials':
                                      'keystone:identity-credentials'}
            else:
                identity_relations = {'ceilometer:identity-service':
                                      'keystone:identity-service'}
            additional_relations.update(identity_relations)
        else:
            additional_relations = {
                'ceilometer:shared-db': 'mongodb:database',
                'ceilometer:identity-service': 'keystone:identity-service'}
        relations.update(additional_relations)
        super(CeilometerBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        keystone_config = {'admin-password': 'openstack',
                           'admin-token': 'ubuntutesting'}
        pxc_config = {
            'dataset-size': '25%',
            'max-connections': 1000,
            'root-password': 'ChangeMe123',
            'sst-password': 'ChangeMe123',
        }
        configs = {
            'keystone': keystone_config,
            'percona-cluster': pxc_config,
        }
        super(CeilometerBasicDeployment, self)._configure_services(configs)

    def _get_token(self):
        return self.keystone.service_catalog.catalog['token']['id']

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.ceil_sentry = self.d.sentry['ceilometer'][0]
        self.ceil_agent_sentry = self.d.sentry['ceilometer-agent'][0]
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.nova_sentry = self.d.sentry['nova-compute'][0]
        if self._get_openstack_release() >= self.xenial_pike:
            self.gnocchi_sentry = self.d.sentry['gnocchi'][0]
            self.run_ceilometer_upgrade_action()
        else:
            self.mongodb_sentry = self.d.sentry['mongodb'][0]
        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate admin with keystone endpoint
        self.keystone_session, self.keystone = u.get_default_keystone_session(
            self.keystone_sentry,
            openstack_release=self._get_openstack_release())

        self.log.debug('Instantiating ceilometer client...')
        if self._get_openstack_release() >= self.xenial_pike:
            self.ceil = ceilo_client.Client(session=self.keystone_session,)
        else:
            # Authenticate admin with ceilometer endpoint
            ep = self.keystone.service_catalog.url_for(service_type='metering',
                                                       interface='publicURL')
            os_token = self.keystone.auth_token
            self.ceil = ceilo_client.Client(endpoint=ep, token=os_token)

    def test_100_services(self):
        """Verify the expected services are running on the corresponding
           service units."""
        u.log.debug('Checking system services on units...')
        release = self._get_openstack_release()
        ceilometer_svcs = [
            'ceilometer-agent-central',
            'ceilometer-agent-notification',
        ]
        if release < self.xenial_pike:
            ceilometer_svcs.append('ceilometer-collector')

        if (release >= self.xenial_ocata and release < self.xenial_pike):
            ceilometer_svcs.append('apache2')

        if release < self.xenial_ocata:
            ceilometer_svcs.append('ceilometer-api')

        if release < self.trusty_mitaka:
            ceilometer_svcs.append('ceilometer-alarm-evaluator')
            ceilometer_svcs.append('ceilometer-alarm-notifier')

        service_names = {
            self.ceil_sentry: ceilometer_svcs,
        }

        ret = u.validate_services_by_name(service_names)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        u.log.debug('OK')

    def test_105_memcache(self):
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping memcache test as memcache server is external'
                        ' to ceilometer')
            return
        u.validate_memcache(self.ceil_sentry,
                            '/etc/ceilometer/ceilometer.conf',
                            self._get_openstack_release(),
                            earliest_release=self.trusty_mitaka)

    def test_110_service_catalog(self):
        """Verify that the service catalog endpoint data is valid."""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping catalogue checks as ceilometer no longer '
                        'registers endpoints')
            return
        u.log.debug('Checking keystone service catalog data...')
        endpoint_check = {
            'adminURL': u.valid_url,
            'id': u.not_null,
            'region': 'RegionOne',
            'publicURL': u.valid_url,
            'internalURL': u.valid_url
        }
        expected = {
            'metering': [endpoint_check],
            'identity': [endpoint_check]
        }
        actual = self.keystone.service_catalog.get_endpoints()

        ret = u.validate_svc_catalog_endpoint_data(
            expected,
            actual,
            openstack_release=self._get_openstack_release())
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        u.log.debug('OK')

    def test_112_keystone_api_endpoint(self):
        """Verify the ceilometer api endpoint data."""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping catalogue checks as ceilometer no longer '
                        'registers endpoints')
            return
        u.log.debug('Checking keystone api endpoint data...')
        endpoints = self.keystone.endpoints.list()
        u.log.debug(endpoints)
        internal_port = public_port = '5000'
        admin_port = '35357'
        expected = {'id': u.not_null,
                    'region': 'RegionOne',
                    'adminurl': u.valid_url,
                    'internalurl': u.valid_url,
                    'publicurl': u.valid_url,
                    'service_id': u.not_null}

        ret = u.validate_endpoint_data(
            endpoints,
            admin_port,
            internal_port,
            public_port,
            expected,
            openstack_release=self._get_openstack_release())
        if ret:
            message = 'Keystone endpoint: {}'.format(ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_114_ceilometer_api_endpoint(self):
        """Verify the ceilometer api endpoint data."""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping catalogue checks as ceilometer no longer '
                        'registers endpoints')
            return
        u.log.debug('Checking ceilometer api endpoint data...')
        endpoints = self.keystone.endpoints.list()
        u.log.debug(endpoints)
        admin_port = internal_port = public_port = '8777'
        expected = {'id': u.not_null,
                    'region': 'RegionOne',
                    'adminurl': u.valid_url,
                    'internalurl': u.valid_url,
                    'publicurl': u.valid_url,
                    'service_id': u.not_null}

        ret = u.validate_endpoint_data(endpoints, admin_port, internal_port,
                                       public_port, expected)
        if ret:
            message = 'Ceilometer endpoint: {}'.format(ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_200_ceilometer_identity_relation(self):
        """Verify the ceilometer to keystone identity-service relation data"""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping identity-service checks as ceilometer no '
                        'longer has this rerlation')
            return
        u.log.debug('Checking ceilometer to keystone identity-service '
                    'relation data...')
        unit = self.ceil_sentry
        relation = ['identity-service', 'keystone:identity-service']
        ceil_ip = unit.relation('identity-service',
                                'keystone:identity-service')['private-address']
        ceil_endpoint = "http://%s:8777" % (ceil_ip)

        expected = {
            'admin_url': ceil_endpoint,
            'internal_url': ceil_endpoint,
            'private-address': ceil_ip,
            'public_url': ceil_endpoint,
            'region': 'RegionOne',
            'requested_roles': 'ResellerAdmin',
            'service': 'ceilometer',
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceilometer identity-service', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_201_keystone_ceilometer_identity_relation(self):
        """Verify the keystone to ceilometer identity-service relation data"""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping identity-service checks as ceilometer no '
                        'longer has this rerlation')
            return
        u.log.debug('Checking keystone:ceilometer identity relation data...')
        unit = self.keystone_sentry
        relation = ['identity-service', 'ceilometer:identity-service']
        id_relation = unit.relation('identity-service',
                                    'ceilometer:identity-service')
        id_ip = id_relation['private-address']
        expected = {
            'admin_token': 'ubuntutesting',
            'auth_host': id_ip,
            'auth_port': "35357",
            'auth_protocol': 'http',
            'private-address': id_ip,
            'service_host': id_ip,
            'service_password': u.not_null,
            'service_port': "5000",
            'service_protocol': 'http',
            'service_tenant': 'services',
            'service_tenant_id': u.not_null,
            'service_username': 'ceilometer',
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('keystone identity-service', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_202_keystone_ceilometer_identity_notes_relation(self):
        """Verify ceilometer to keystone identity-notifications relation"""
        u.log.debug('Checking keystone:ceilometer '
                    'identity-notifications relation data...')

        # Relation data may vary depending on timing of hooks and relations.
        # May be glance- or keystone- or another endpoint-changed value, so
        # check that at least one ???-endpoint-changed value exists.
        unit = self.keystone_sentry
        relation_data = unit.relation('identity-notifications',
                                      'ceilometer:identity-notifications')

        expected = '-endpoint-changed'
        found = 0
        for key in relation_data.keys():
            if expected in key and relation_data[key]:
                found += 1
                u.log.debug('{}: {}'.format(key, relation_data[key]))

        if not found:
            message = ('keystone:ceilometer identity-notification relation '
                       'error\n expected something like: {}\n actual: '
                       '{}'.format(expected, relation_data))
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_203_ceilometer_amqp_relation(self):
        """Verify the ceilometer to rabbitmq-server amqp relation data"""
        u.log.debug('Checking ceilometer:rabbitmq amqp relation data...')
        unit = self.ceil_sentry
        relation = ['amqp', 'rabbitmq-server:amqp']
        expected = {
            'username': 'ceilometer',
            'private-address': u.valid_ip,
            'vhost': 'openstack'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceilometer amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_204_amqp_ceilometer_relation(self):
        """Verify the rabbitmq-server to ceilometer amqp relation data"""
        u.log.debug('Checking rabbitmq:ceilometer amqp relation data...')
        unit = self.rabbitmq_sentry
        relation = ['amqp', 'ceilometer:amqp']
        expected = {
            'hostname': u.valid_ip,
            'private-address': u.valid_ip,
            'password': u.not_null,
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('rabbitmq amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_207_ceilometer_ceilometer_agent_relation(self):
        """Verify the ceilometer to ceilometer-agent relation data"""
        u.log.debug('Checking ceilometer:ceilometer-agent relation data...')
        unit = self.ceil_sentry
        relation = ['ceilometer-service',
                    'ceilometer-agent:ceilometer-service']
        expected = {
            'rabbitmq_user': 'ceilometer',
            'verbose': 'False',
            'rabbitmq_host': u.valid_ip,
            'use_syslog': 'False',
            'metering_secret': u.not_null,
            'rabbitmq_virtual_host': 'openstack',
            'private-address': u.valid_ip,
            'debug': 'False',
            'rabbitmq_password': u.not_null,
            'port': '8767'
        }
        if self._get_openstack_release() >= self.xenial_pike:
            expected['gnocchi_url'] = u.valid_url
            if self._get_openstack_release() >= self.xenial_queens:
                expected['port'] = '8777'
        else:
            expected['db_port'] = '27017'
            expected['db_name'] = 'ceilometer'
            expected['db_host'] = u.valid_ip
            expected['service_ports'] = "{'ceilometer_api': [8777, 8767]}"

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceilometer-service', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_208_ceilometer_agent_ceilometer_relation(self):
        """Verify the ceilometer-agent to ceilometer relation data"""
        u.log.debug('Checking ceilometer-agent:ceilometer relation data...')
        unit = self.ceil_agent_sentry
        relation = ['ceilometer-service', 'ceilometer:ceilometer-service']
        expected = {'private-address': u.valid_ip}

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('ceilometer-service', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_300_ceilometer_config(self):
        """Verify the data in the ceilometer config file."""
        u.log.debug('Checking ceilometer config file data...')
        unit = self.ceil_sentry
        conf = '/etc/ceilometer/ceilometer.conf'
        expected = {
            'DEFAULT': {
                'verbose': 'False',
                'debug': 'False',
                'use_syslog': 'False',
            },
            'api': {
                'port': '8767',
            },
        }
        if self._get_openstack_release() >= self.xenial_pike:
            relation = self.gnocchi_sentry.relation(
                'metric-service',
                'ceilometer:metric-service')
            expected['dispatcher_gnocchi'] = {'url': relation['gnocchi_url']}
            if self._get_openstack_release() >= self.xenial_queens:
                ks_rel = self.keystone_sentry.relation(
                    'identity-credentials',
                    'ceilometer:identity-credentials')
                ks_key_prefix = 'credentials'
            else:
                ks_rel = self.keystone_sentry.relation(
                    'identity-service',
                    'ceilometer:identity-service')
                ks_key_prefix = 'service'
        else:
            db_relation = self.mongodb_sentry.relation('database',
                                                       'ceilometer:shared-db')
            db_conn = 'mongodb://%s:%s/ceilometer' % (db_relation['hostname'],
                                                      db_relation['port'])
            expected['database'] = {'connection': db_conn}
            ks_rel = self.keystone_sentry.relation(
                'identity-service',
                'ceilometer:identity-service')
            ks_key_prefix = 'service'

        if self._get_openstack_release() < self.trusty_mitaka:
            auth_uri = '%s://%s:%s/v2.0' % (ks_rel['service_protocol'],
                                            ks_rel['service_host'],
                                            ks_rel['service_port'])
            expected['service_credentials'] = {'os_auth_url': auth_uri,
                                               'os_tenant_name': 'services',
                                               'os_username': 'ceilometer',
                                               'os_password':
                                               ks_rel['service_password']}
        else:
            auth_uri = '%s://%s:%s' % (
                ks_rel['{}_protocol'.format(ks_key_prefix)],
                ks_rel['{}_host'.format(ks_key_prefix)],
                ks_rel['{}_port'.format(ks_key_prefix)])
            # NOTE(dosaboy): os_ prefix is deprecated and no longer used as
            #                of Mitaka.
            project_domain_name = 'default'
            user_domain_name = 'default'
            if 'api_version' in ks_rel and float(ks_rel['api_version']) > 2:
                project_domain_name = 'service_domain'
                user_domain_name = 'service_domain'
            expected['service_credentials'] = {
                'auth_url': auth_uri,
                'project_name': 'services',
                'project_domain_name': project_domain_name,
                'user_domain_name': user_domain_name,
                'username': 'ceilometer',
                'password': ks_rel['{}_password'.format(ks_key_prefix)]}

        if self._get_openstack_release() >= self.xenial_ocata:
            del expected['api']

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "ceilometer config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

        u.log.debug('OK')

    def test_400_api_connection(self):
        """Simple api calls to check service is up and responding"""
        if self._get_openstack_release() >= self.xenial_pike:
            u.log.debug('Skipping API checks as ceilometer api has been '
                        'removed')
            return
        u.log.debug('Checking api functionality...')
        assert(self.ceil.samples.list() == [])
        assert(self.ceil.meters.list() == [])
        u.log.debug('OK')

    # NOTE(beisner): need to add more functional tests

    def test_900_restart_on_config_change(self):
        """Verify that the specified services are restarted when the config
           is changed.
           """
        sentry = self.ceil_sentry
        juju_service = 'ceilometer'

        # Expected default and alternate values
        set_default = {'debug': 'False'}
        set_alternate = {'debug': 'True'}

        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change
        conf_file = '/etc/ceilometer/ceilometer.conf'
        if self._get_openstack_release() >= self.xenial_pike:
            services = {
                'ceilometer-polling: AgentManager worker(0)': conf_file,
                'ceilometer-agent-notification: NotificationService worker(0)':
                    conf_file,
            }
        elif self._get_openstack_release() >= self.xenial_ocata:
            services = {
                'ceilometer-collector: CollectorService worker(0)': conf_file,
                'ceilometer-polling: AgentManager worker(0)': conf_file,
                'ceilometer-agent-notification: NotificationService worker(0)':
                    conf_file,
                'apache2': conf_file,
            }
        elif self._get_openstack_release() >= self.xenial_newton:
            services = {
                'ceilometer-collector - CollectorService(0)': conf_file,
                'ceilometer-polling - AgentManager(0)': conf_file,
                'ceilometer-agent-notification - NotificationService(0)':
                    conf_file,
                'ceilometer-api': conf_file,
            }
        else:
            services = {
                'ceilometer-collector': conf_file,
                'ceilometer-api': conf_file,
                'ceilometer-agent-notification': conf_file,
            }

            if self._get_openstack_release() < self.trusty_mitaka:
                services['ceilometer-alarm-notifier'] = conf_file
                services['ceilometer-alarm-evaluator'] = conf_file

            if self._get_openstack_release() >= self.trusty_liberty:
                # Liberty and later
                services['ceilometer-polling'] = conf_file
            else:
                # Juno and earlier
                services['ceilometer-agent-central'] = conf_file

        # Make config change, check for service restarts
        u.log.debug('Making config change on {}...'.format(juju_service))
        mtime = u.get_sentry_time(sentry)
        self.d.configure(juju_service, set_alternate)

        sleep_time = 40
        for s, conf_file in services.iteritems():
            u.log.debug("Checking that service restarted: {}".format(s))
            if not u.validate_service_config_changed(sentry, mtime, s,
                                                     conf_file,
                                                     retry_count=4,
                                                     retry_sleep_time=20,
                                                     sleep_time=sleep_time):
                self.d.configure(juju_service, set_default)
                msg = "service {} didn't restart after config change".format(s)
                amulet.raise_status(amulet.FAIL, msg=msg)
            sleep_time = 0

        self.d.configure(juju_service, set_default)
        u.log.debug('OK')

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed. """
        u.log.debug('Checking pause and resume actions...')
        unit = self.ceil_sentry
        juju_service = 'ceilometer'

        assert u.status_get(unit)[0] == "active"

        action_id = unit.run_action("pause")
        assert u.wait_on_action(action_id), "Pause action failed."
        assert u.status_get(unit)[0] == "maintenance"

        # trigger config-changed to ensure that services are still stopped
        u.log.debug("Making config change on ceilometer ...")
        self.d.configure(juju_service, {'debug': 'True'})
        assert u.status_get(unit)[0] == "maintenance"
        self.d.configure(juju_service, {'debug': 'False'})
        assert u.status_get(unit)[0] == "maintenance"

        action_id = unit.run_action("resume")
        assert u.wait_on_action(action_id), "Resume action failed."
        assert u.status_get(unit)[0] == "active"
        u.log.debug('OK')

    def run_ceilometer_upgrade_action(self):
        """Run ceilometer-upgrade

        This action will be run early to initialize ceilometer
        when gnocchi is related.
        Ceilometer will be in a blocked state until this runs.
        """
        if self._get_openstack_release() < self.xenial_pike:
            u.log.debug('Not checking ceilometer-upgrade')
            return
        u.log.debug('Checking ceilometer-upgrade')
        unit = self.ceil_sentry

        action_id = unit.run_action("ceilometer-upgrade")
        assert u.wait_on_action(action_id), "ceilometer-upgrade action failed"
        # Wait for acivte Unit is ready on ceilometer
        self.exclude_services.remove('ceilometer')
        self._auto_wait_for_status(exclude_services=self.exclude_services)
        u.log.debug('OK')
