#!/usr/bin/env python3
#
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

import os
import sys

_path = os.path.dirname(os.path.realpath(__file__))
_hooks = os.path.abspath(os.path.join(_path, '../hooks'))
_root = os.path.abspath(os.path.join(_path, '..'))


def _add_path(path):
    if path not in sys.path:
        sys.path.insert(1, path)

_add_path(_hooks)
_add_path(_root)


from charmhelpers.contrib.openstack.utils import (
    do_action_openstack_upgrade,
)

from ceilometer_hooks import (
    config_changed,
    CONFIGS,
)

from ceilometer_utils import (
    do_openstack_upgrade,
)


def openstack_upgrade():
    """Perform action-managed OpenStack upgrade.

    Upgrades packages to the configured openstack-origin version and sets
    the corresponding action status as a result.

    If the charm was installed from source we cannot upgrade it.
    For backwards compatibility a config flag (action-managed-upgrade) must
    be set for this code to run, otherwise a full service level upgrade will
    fire on config-changed."""

    if (do_action_openstack_upgrade('ceilometer-common',
                                    do_openstack_upgrade,
                                    CONFIGS)):
        config_changed()

if __name__ == '__main__':
    openstack_upgrade()
