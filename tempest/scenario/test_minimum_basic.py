# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 NEC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from tempest.common.utils.data_utils import rand_name
from tempest.openstack.common import log as logging
from tempest.scenario import manager
from tempest.test import services


LOG = logging.getLogger(__name__)


class TestMinimumBasicScenario(manager.NetworkScenarioTest):

    """
    This is a basic minimum scenario test.

    This test below:
    * across the multiple components
    * as a regular user
    * with and without optional parameters
    * check command outputs

    """
    
    @classmethod
    def check_preconditions(cls):
        super(TestMinimumBasicScenario, cls).check_preconditions()
        cfg = cls.config.network
        if not (cfg.tenant_networks_reachable or cfg.public_network_id):
            msg = ('Either tenant_networks_reachable must be "true", or '
                   'public_network_id must be defined.')
            cls.enabled = False
            raise cls.skipException(msg)

    @classmethod
    def setUpClass(cls):
        super(TestMinimumBasicScenario, cls).setUpClass()
        cls.check_preconditions()
        # TODO(mnewby) Consider looking up entities as needed instead
        # of storing them as collections on the class.
        cls.floating_ips = {}
        
    def _wait_for_server_status(self, status):
        server_id = self.server.id
        self.status_timeout(
            self.compute_client.servers, server_id, status)

    def _wait_for_volume_status(self, status):
        volume_id = self.volume.id
        self.status_timeout(
            self.volume_client.volumes, volume_id, status)

    def _image_create(self, name, fmt, fmt2, path, properties={}):
        name = rand_name('%s-' % name)
        image_file = open(path, 'rb')
        self.addCleanup(image_file.close)
        params = {
            'name': name,
            'container_format': fmt2,
            'disk_format': fmt,
            'is_public': 'True',
        }
        params.update(properties)
        image = self.image_client.images.create(**params)
        self.addCleanup(self.image_client.images.delete, image)
        self.assertEqual("queued", image.status)
        image.update(data=image_file)
        return image.id

    def glance_image_create(self):
        ami_img_path = self.config.scenario.img_dir + "/" + \
            self.config.scenario.ami_img_file
        LOG.debug("paths: ami: %s"
                  % (ami_img_path))
        
        properties = {}
        self.image = self._image_create('scenario-qcow2', 'qcow2', 'ovf',
                                        path=ami_img_path,
                                        properties=properties)

    def nova_keypair_add(self):
        self.keypair = self.create_keypair()

    def nova_boot(self):
        create_kwargs = {'key_name': self.keypair.name}
        self.server = self.create_server(image=self.image,
                                         create_kwargs=create_kwargs)

    def nova_list(self):
        servers = self.compute_client.servers.list()
        LOG.debug("server_list:%s" % servers)
        self.assertIn(self.server, servers)

    def nova_show(self):
        got_server = self.compute_client.servers.get(self.server)
        LOG.debug("got server:%s" % got_server)
        self.assertEqual(self.server, got_server)

    def cinder_create(self):
        self.volume = self.create_volume()

    def cinder_list(self):
        volumes = self.volume_client.volumes.list()
        self.assertIn(self.volume, volumes)

    def cinder_show(self):
        volume = self.volume_client.volumes.get(self.volume.id)
        self.assertEqual(self.volume, volume)

    def nova_volume_attach(self):
        attach_volume_client = self.compute_client.volumes.create_server_volume
        volume = attach_volume_client(self.server.id,
                                      self.volume.id,
                                      '/dev/vdb')
        self.assertEqual(self.volume.id, volume.id)
        self._wait_for_volume_status('in-use')

    def nova_reboot(self):
        self.server.reboot()
        self._wait_for_server_status('ACTIVE')

    def nova_floating_ip_create(self):
        public_network_id = self.config.network.public_network_id
        server = self.server
        self.floating_ip = self._create_floating_ip(server, public_network_id)
        floating_ip = self.floating_ip
        self.floating_ips.setdefault(server, [])
        self.floating_ips[server].append(floating_ip)

    def nova_floating_ip_add(self):
        self.server.add_floating_ip(self.floating_ip)

    def ssh_to_server(self):
        self.linux_client = self.get_remote_client(self.floating_ip.floating_ip_address)

    def check_partitions(self):
        partitions = self.linux_client.get_partitions()
        self.assertEqual(1, partitions.count('vdb'))

    def nova_volume_detach(self):
        detach_volume_client = self.compute_client.volumes.delete_server_volume
        detach_volume_client(self.server.id, self.volume.id)
        self._wait_for_volume_status('available')

        volume = self.volume_client.volumes.get(self.volume.id)
        self.assertEqual('available', volume.status)

    @services('compute', 'volume', 'image', 'network')
    def test_minimum_basic_scenario(self):
        self.glance_image_create()
        #self.image="9ce97f3b-2303-4d7c-9728-5fd48a0426e5"
        self.nova_keypair_add()
        self.nova_boot()
        self.nova_list()
        self.nova_show()
        self.cinder_create()
        self.cinder_list()
        self.cinder_show()
        self.nova_volume_attach()
        self.cinder_show()
        self.nova_reboot()

        self.nova_floating_ip_create()
        #self.nova_floating_ip_add()
        self.create_loginable_secgroup_rule()
        self.ssh_to_server()
        self.check_partitions()

        self.nova_volume_detach()
