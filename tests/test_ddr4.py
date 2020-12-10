from liquidctl.driver.ddr4 import *
from liquidctl.error import *
import pytest

from _testutils import VirtualSmbus


# SPD samples


def patch_spd_dump(spd_dump, slice, new):
    spd_dump = bytearray(spd_dump)
    spd_dump[slice] = new
    return bytes(spd_dump)


_VENGEANCE_RGB_SAMPLE = bytes.fromhex(
    '23100c028521000800000003090300000000080cfc0300006c6c6c110874f00a'
    '2008000500a81e2b2b0000000000000000000000000000000000000016361636'
    '1636163600002b0c2b0c2b0c2b0c000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000edb5ce0000000000c24da7'
    '1111010100000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000de27'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '029e00000000000000434d5233324758344d32433333333343313620200080ce'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '0c4a01200000000000a3000005fc3f04004d575710ac03f00a2008000500b022'
    '2c00000000000000009cceb5b5b5e7e700000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
)

# clear the part number; the Vengeance RGB sample already didn't set the TS bit
_NON_TS_SPD = patch_spd_dump(_VENGEANCE_RGB_SAMPLE, slice(0x149, 0x15d), b' ' * 20)

# set the TS bit
_TS_SPD = patch_spd_dump(_NON_TS_SPD, 0x0e, 0x80)


# DDR4 SPD decoding


@pytest.fixture
def cmr_spd():
    return Ddr4Spd(_VENGEANCE_RGB_SAMPLE)


def test_spd_bytes_used(cmr_spd):
    assert cmr_spd.spd_bytes_used == 384


def test_spd_bytes_total(cmr_spd):
    assert cmr_spd.spd_bytes_total == 512


def test_spd_revision(cmr_spd):
    assert cmr_spd.spd_revision == (1, 0)


def test_dram_device_type(cmr_spd):
    assert cmr_spd.dram_device_type == Ddr4Spd.DramDeviceType.DDR4_SDRAM


def test_module_type(cmr_spd):
    assert cmr_spd.module_type == (Ddr4Spd.BaseModuleType.UDIMM, None)


def test_module_thermal_sensor(cmr_spd):
    assert not cmr_spd.module_thermal_sensor


def test_module_manufacturer(cmr_spd):
    assert cmr_spd.module_manufacturer == 'Corsair'


def test_module_part_number(cmr_spd):
    assert cmr_spd.module_part_number == 'CMR32GX4M2C3333C16'


def test_dram_manufacturer(cmr_spd):
    assert cmr_spd.dram_manufacturer == 'Samsung'


def emulate_spd_at(bus, address, cmr_spd):
    # hack: preload cmr_spd eeprom data
    bus._data[address] = cmr_spd


# DDR4 modules using a TSE2004av-compatible SPD EEPROM with temperature sensor


@pytest.fixture
def smbus():
    smbus = VirtualSmbus(parent_driver='i801_smbus')

    # hack: clear all spd addresses
    for address in range(0x50, 0x58):
        smbus._data[address] = None

    return smbus


def test_generic_ignores_not_allowed_buses(smbus, monkeypatch):
    emulate_spd_at(smbus, 0x51, _TS_SPD)

    checks = [
        ('parent_driver', 'other'),
    ]

    for attr, val in checks:
        with monkeypatch.context() as m:
            m.setattr(smbus, attr, val)
            assert list(Ddr4Temperature.probe(smbus)) == [], \
                    f'changing {attr} did not cause a mismatch'


def test_generic_doest_match_non_ts_devices(smbus):
    emulate_spd_at(smbus, 0x51, _NON_TS_SPD)
    assert list(map(type, Ddr4Temperature.probe(smbus))) == []


def test_generic_finds_ts_devices(smbus):
    emulate_spd_at(smbus, 0x51, _TS_SPD)
    emulate_spd_at(smbus, 0x53, _TS_SPD)
    emulate_spd_at(smbus, 0x55, _TS_SPD)
    emulate_spd_at(smbus, 0x57, _TS_SPD)

    devs = list(Ddr4Temperature.probe(smbus))

    assert list(map(type, devs)) == [Ddr4Temperature] * 4
    assert devs[1].description == 'Corsair DIMM4 (experimental)'


def test_generic_get_status_is_unsafe(smbus):
    emulate_spd_at(smbus, 0x51, _TS_SPD)
    dimm = next(Ddr4Temperature.probe(smbus))
    assert dimm.get_status() == []


def test_generic_get_status_reads_temperature(smbus):
    enable = ['smbus', 'ddr4_temperature']
    emulate_spd_at(smbus, 0x51, _TS_SPD)
    dimm = next(Ddr4Temperature.probe(smbus))

    with dimm.connect(unsafe=enable):
        smbus.write_block_data(0x19, 0x05, 0xe19c)

        status = dimm.get_status(unsafe=enable)
        expected = [
            ('Temperature', 25.75, '°C'),
        ]

        assert status == expected


def test_generic_get_status_reads_negative_temperature(smbus):
    enable = ['smbus', 'ddr4_temperature']
    emulate_spd_at(smbus, 0x51, _TS_SPD)
    dimm = next(Ddr4Temperature.probe(smbus))

    with dimm.connect(unsafe=enable):
        smbus.write_block_data(0x19, 0x05, 0x1e74)

        status = dimm.get_status(unsafe=enable)
        expected = [
            ('Temperature', -24.75, '°C'),
        ]

        assert status == expected


# Corsair Vengeance RGB


@pytest.fixture
def vengeance_rgb(smbus):
    emulate_spd_at(smbus, 0x51, _VENGEANCE_RGB_SAMPLE)
    dimm = next(VengeanceRgb.probe(smbus))
    return (smbus, dimm)


def test_vengeance_rgb_finds_devices(smbus):
    emulate_spd_at(smbus, 0x51, _VENGEANCE_RGB_SAMPLE)
    emulate_spd_at(smbus, 0x53, _VENGEANCE_RGB_SAMPLE)
    emulate_spd_at(smbus, 0x55, _VENGEANCE_RGB_SAMPLE)
    emulate_spd_at(smbus, 0x57, _VENGEANCE_RGB_SAMPLE)

    devs = list(VengeanceRgb.probe(smbus))

    assert list(map(type, devs)) == [VengeanceRgb] * 4
    assert devs[1].description == 'Corsair Vengeance RGB DIMM4 (experimental)'


def test_vengeance_get_status_reads_temperature(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    def forbid(*args, **kwargs):
        assert False, 'should not reach here'

    smbus.read_block_data = forbid

    with dimm.connect(unsafe=enable):
        smbus.write_word_data(0x19, 0x05, 0x9ce1)

        status = dimm.get_status(unsafe=enable)
        expected = [
            ('Temperature', 25.75, '°C'),
        ]

        assert status == expected


def test_vengeance_rgb_set_color_is_unsafe(vengeance_rgb):
    _, dimm = vengeance_rgb

    with pytest.raises(UnsafeFeaturesNotEnabled):
        assert dimm.set_color('led', 'off', [])

    with pytest.raises(UnsafeFeaturesNotEnabled):
        assert dimm.set_color('led', 'off', [], unsafe='vengeance_rgb')

    with pytest.raises(UnsafeFeaturesNotEnabled):
        assert dimm.set_color('led', 'off', [], unsafe='smbus')


def test_vengeance_rgb_sets_color_to_off(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    with dimm.connect(unsafe=enable):
        # change registers to something other than 0
        smbus.write_byte_data(0x59, 0xa4, 0x10)
        smbus.write_byte_data(0x59, 0xa5, 0x20)
        smbus.write_byte_data(0x59, 0xb0, 0xaa)
        smbus.write_byte_data(0x59, 0xb1, 0xbb)
        smbus.write_byte_data(0x59, 0xb2, 0xcc)
        smbus.write_byte_data(0x59, 0xa6, 0xff)

        dimm.set_color('led', 'off', [], unsafe=enable)

        assert smbus.read_byte_data(0x59, 0xa4) == 0x00
        assert smbus.read_byte_data(0x59, 0xa5) == 0x00
        assert smbus.read_byte_data(0x59, 0xa7) == 0x01
        assert smbus.read_byte_data(0x59, 0xa6) == 0x00

        for color_component in range(0xb0, 0xb3):
            assert smbus.read_byte_data(0x59, color_component) == 0x00


def test_vengeance_rgb_sets_color_to_fixed(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    with dimm.connect(unsafe=enable):
        radical_red = [0xff, 0x35, 0x5e]
        dimm.set_color('led', 'fixed', [radical_red], unsafe=enable)

        assert smbus.read_byte_data(0x59, 0xa4) == 0x00
        assert smbus.read_byte_data(0x59, 0xa5) == 0x00
        assert smbus.read_byte_data(0x59, 0xa7) == 0x01
        assert smbus.read_byte_data(0x59, 0xa6) == 0x00

        assert smbus.read_byte_data(0x59, 0xb0) == 0xff
        assert smbus.read_byte_data(0x59, 0xb1) == 0x35
        assert smbus.read_byte_data(0x59, 0xb2) == 0x5e


def test_vengeance_rgb_sets_color_to_breathing(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    with dimm.connect(unsafe=enable):
        radical_red = [0xff, 0x35, 0x5e]
        mountain_meadow = [0x1a, 0xb3, 0x85]
        dimm.set_color('led', 'breathing', [radical_red, mountain_meadow],
                       unsafe=enable)

        # assert smbus.read_byte_data(0x59, 0xa4) == 0x00  # FIXME
        # assert smbus.read_byte_data(0x59, 0xa5) == 0x00  # FIXME
        assert smbus.read_byte_data(0x59, 0xa7) == 0x02
        assert smbus.read_byte_data(0x59, 0xa6) == 0x02

        assert smbus.read_byte_data(0x59, 0xb0) == 0xff
        assert smbus.read_byte_data(0x59, 0xb1) == 0x35
        assert smbus.read_byte_data(0x59, 0xb2) == 0x5e

        assert smbus.read_byte_data(0x59, 0xb3) == 0x1a
        assert smbus.read_byte_data(0x59, 0xb4) == 0xb3
        assert smbus.read_byte_data(0x59, 0xb5) == 0x85


def test_vengeance_rgb_sets_single_color_to_breathing(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    with dimm.connect(unsafe=enable):
        radical_red = [0xff, 0x35, 0x5e]
        dimm.set_color('led', 'breathing', [radical_red],
                       unsafe=enable)

        # assert smbus.read_byte_data(0x59, 0xa4) == 0x00  # FIXME
        # assert smbus.read_byte_data(0x59, 0xa5) == 0x00  # FIXME
        assert smbus.read_byte_data(0x59, 0xa7) == 0x01
        assert smbus.read_byte_data(0x59, 0xa6) == 0x00  # special case

        assert smbus.read_byte_data(0x59, 0xb0) == 0xff
        assert smbus.read_byte_data(0x59, 0xb1) == 0x35
        assert smbus.read_byte_data(0x59, 0xb2) == 0x5e


def test_vengeance_rgb_sets_color_to_fading(vengeance_rgb):
    enable = ['smbus', 'vengeance_rgb']
    smbus, dimm = vengeance_rgb

    with dimm.connect(unsafe=enable):
        radical_red = [0xff, 0x35, 0x5e]
        mountain_meadow = [0x1a, 0xb3, 0x85]
        dimm.set_color('led', 'fading', [radical_red, mountain_meadow],
                       unsafe=enable)

        # assert smbus.read_byte_data(0x59, 0xa4) == 0x00  # FIXME
        # assert smbus.read_byte_data(0x59, 0xa5) == 0x00  # FIXME
        assert smbus.read_byte_data(0x59, 0xa7) == 0x02
        assert smbus.read_byte_data(0x59, 0xa6) == 0x01

        assert smbus.read_byte_data(0x59, 0xb0) == 0xff
        assert smbus.read_byte_data(0x59, 0xb1) == 0x35
        assert smbus.read_byte_data(0x59, 0xb2) == 0x5e

        assert smbus.read_byte_data(0x59, 0xb3) == 0x1a
        assert smbus.read_byte_data(0x59, 0xb4) == 0xb3
        assert smbus.read_byte_data(0x59, 0xb5) == 0x85
