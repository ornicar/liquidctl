"""Compatibility shim with users of the old liquidctl.driver package.

This should not be used in new code; instead, prefer the new module and class
names.

Copyright (C) 2020–2020  Jonas Malaco
Copyright (C) 2020–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

import logging
import sys

# deprecated aiases
import liquidctl.asetek as asetek
import liquidctl.corsair_hid_psu as corsair_hid_psu
import liquidctl.kraken2 as kraken_two
import liquidctl.nzxt_epsu as seasonic
import liquidctl.smart_device as smart_device
from liquidctl.driver_tree import find_devices as find_liquidctl_devices

# allow old protocol/driver imports to continue to work by manually placing
# these into the module cache, so import liquidctl.driver.foo does not need to
# check the filesystem for foo
sys.modules['liquidctl.driver.asetek'] = asetek
sys.modules['liquidctl.driver.corsair_hid_psu'] = corsair_hid_psu
sys.modules['liquidctl.driver.kraken_two'] = kraken_two
sys.modules['liquidctl.driver.seasonic'] = seasonic
sys.modules['liquidctl.driver.smart_device'] = smart_device

logger = logging.getLogger(__name__)
logger.debug('using deprecated liquidctl.driver names')
