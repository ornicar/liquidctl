"""Monitor and control liquid coolers and other devices.

Copyright (C) 2018–2020  Jonas Malaco
Copyright (C) 2018–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

from liquidctl.driver_tree import find_devices

# make all drivers available for find_devices
import liquidctl.asetek
import liquidctl.corsair_hid_psu
import liquidctl.hydro_platinum
import liquidctl.kraken2
import liquidctl.kraken3
import liquidctl.nzxt_epsu
import liquidctl.smart_device
