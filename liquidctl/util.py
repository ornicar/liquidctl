"""Assorted utilities used by drivers and the CLI.

Copyright (C) 2018–2020  Jonas Malaco
Copyright (C) 2018–2020  each contribution's author

SPDX-License-Identifier: GPL-3.0-or-later
"""

import base64
import colorsys
import logging
import os
import re
import sys
import tempfile

from ast import literal_eval
from enum import Enum, unique

LOGGER = logging.getLogger(__name__)
XDG_RUNTIME_DIR = os.getenv('XDG_RUNTIME_DIR')
HUE2_MAX_ACCESSORIES_IN_CHANNEL = 6


@unique
class Hue2Accessory(Enum):
    """Mapping of HUE 2 accessory IDs and names.

    >>> Hue2Accessory(4)
    <Hue2Accessory.HUE2_LED_STRIP_300: 4>
    >>> str(Hue2Accessory(4))
    'HUE 2 LED Strip 300 mm'

    Unknown IDs are automatically translated to equivalent pseudo-names.

    >>> Hue2Accessory(59)
    <Hue2Accessory.UNKNOWN_59: 59>
    >>> Hue2Accessory(59).value == Hue2Accessory(59).value
    True
    >>> Hue2Accessory(59) != Hue2Accessory(58)
    True
    """

    HUE_PLUS_LED_STRIP = (0x01, 'HUE+ LED Strip')
    AER_RGB1_FAN = (0x02, 'AER RGB 1')
    HUE2_LED_STRIP_300 = (0x04, 'HUE 2 LED Strip 300 mm')
    HUE2_LED_STRIP_250 = (0x05, 'HUE 2 LED Strip 250 mm')
    HUE2_LED_STRIP_200 = (0x06, 'HUE 2 LED Strip 200 mm')
    HUE2_CABLE_COMB = (0x07, 'HUE 2 Cable Comb')
    HUE2_UNDERGLOW_300 = (0x09, 'HUE 2 Underglow 300 mm')
    HUE2_UNDERGLOW_200 = (0x0a, 'HUE 2 Underglow 200 mm')
    AER_RGB2_120 = (0x0b, 'AER RGB 2 120 mm')
    AER_RGB2_140 = (0x0c, 'AER RGB 2 140 mm')
    KRAKENX_GEN4_RING = (0x10, 'Kraken X (X53, X63 or X73) Pump Ring')
    KRAKENX_GEN4_LOGO = (0x11, 'Kraken X (X53, X63 or X73) Pump Logo')

    def __new__(cls, value, pretty_name):
        member = object.__new__(cls)
        member.pretty_name = pretty_name
        member._value_ = value
        return member

    @classmethod
    def _missing_(cls, value):
        dummy = object.__new__(cls)
        dummy.pretty_name = 'Unknown'
        dummy._name_ = f'UNKNOWN_{value}'
        dummy._value_ = value
        return dummy

    def __str__(self):
        return self.pretty_name

    def __eq__(self, other):
        return self.value == other.value


def clamp(value, clampmin, clampmax):
    """Clamp numeric `value` to interval [`clampmin`, `clampmax`]."""
    clamped = max(clampmin, min(clampmax, value))
    if clamped != value:
        LOGGER.debug('clamped %s to interval [%s, %s]', value, clampmin, clampmax)
    return clamped


def fraction_of_byte(ratio=None, percentage=None):
    """Return `ratio` xor `percentage` expressed as a fraction of 255.

    >>> fraction_of_byte(ratio=.8)
    204
    >>> fraction_of_byte(percentage=20)
    51
    """
    if percentage is not None:
        ratio = percentage / 100
    if ratio is not None:
        if ratio < 0 or ratio > 1:
            raise ValueError('Cannot express ratios outside of [0, 1]')
        return round(ratio * 255)
    raise ValueError('Either ratio or percentage must not be None')


def u16le_from(buffer, offset=0):
    """Read an unsigned 16-bit little-endian integer from `buffer`.

    >>> u16le_from(b'\x45\x05\x03')
    1349
    >>> u16le_from(b'\x45\x05\x03', offset=1)
    773
    """
    return int.from_bytes(buffer[offset : offset + 2], byteorder='little')


def delta(profile):
    """Compute a profile's Δx and Δy."""
    return [(cur[0]-prev[0], cur[1]-prev[1])
            for cur,prev in zip(profile[1:], profile[:-1])]


def normalize_profile(profile, critx):
    """Normalize a [(x:int, y:int), ...] profile.

    The normalized profile will ensure that:

     - the profile is a monotonically increasing function
       (i.e. for every i, i > 1, x[i] - x[i-1] > 0 and y[i] - y[i-1] >= 0)
     - the profile is sorted
     - a (critx, 100) failsafe is enforced
     - only the first point that sets y := 100 is kept

    >>> normalize_profile([(30, 40), (25, 25), (35, 30), (40, 35), (40, 80)], 60)
    [(25, 25), (30, 40), (35, 40), (40, 80), (60, 100)]
    >>> normalize_profile([(30, 40), (25, 25), (35, 30), (40, 100)], 60)
    [(25, 25), (30, 40), (35, 40), (40, 100)]
    >>> normalize_profile([(30, 40), (25, 25), (35, 100), (40, 100)], 60)
    [(25, 25), (30, 40), (35, 100)]
    >>> normalize_profile([], 60)
    [(60, 100)]
    """
    profile = sorted(list(profile) + [(critx, 100)], key=lambda p: (p[0], -p[1]))
    mono = profile[0:1]
    for (x, y), (xb, yb) in zip(profile[1:], profile[:-1]):
        if x == xb:
            continue
        if y < yb:
            y = yb
        mono.append((x, y))
        if y == 100:
            break
    return mono


def interpolate_profile(profile, x):
    """Interpolate y given x and a [(x: int, y: int), ...] profile.

    Requires the profile to be sorted by x, with no duplicate x values (see
    normalize_profile).  Expects profiles with integer x and y values, and
    returns duty rounded to the nearest integer.

    >>> interpolate_profile([(20, 50), (50, 70), (60, 100)], 33)
    59
    >>> interpolate_profile([(20, 50), (50, 70)], 19)
    50
    >>> interpolate_profile([(20, 50), (50, 70)], 51)
    70
    >>> interpolate_profile([(20, 50)], 20)
    50
    """
    lower, upper = profile[0], profile[-1]
    for step in profile:
        if step[0] <= x:
            lower = step
        if step[0] >= x:
            upper = step
            break
    if lower[0] == upper[0]:
        return lower[1]
    return round(lower[1] + (x - lower[0])/(upper[0] - lower[0])*(upper[1] - lower[1]))


def color_from_str(x):
    """Parse a color, and, if necessary, translate it into the RGB model.

    The input string can be encoded in several formats:

     - ffffff: hexadecimal RGB implicit tuple
     - rgb(255, 255, 255): explicit RGB, R,G,B ∊ [0, 255]
     - hsv(360, 100, 100): explicit HSV, H ∊ [0, 360], SV ∊ [0, 100]
     - hsl(360, 100, 100): explicit HSL, H ∊ [0, 360], SV ∊ [0, 100]

    >>> color_from_str('fF7f3f')
    [255, 127, 63]
    >>> color_from_str('Rgb(255, 127, 63)')
    [255, 127, 63]
    >>> color_from_str('Hsv(20, 75, 100)')
    [255, 128, 64]
    >>> color_from_str('Hsl(20, 100, 62)')
    [255, 126, 61]

    >>> color_from_str('fF7f3f1f')
    Traceback (most recent call last):
        ...
    ValueError: Cannot parse color: fF7f3f1f
    >>> color_from_str('rgb()')
    Traceback (most recent call last):
        ...
    ValueError: Expected 3-element triple: rgb()
    >>> color_from_str('rgb(255)')
    Traceback (most recent call last):
        ...
    ValueError: Expected 3-element triple: rgb(255)
    >>> color_from_str('rgb(300, 255, 255)')
    Traceback (most recent call last):
        ...
    ValueError: Expected value in range [0, 255]: 300 in rgb(300, 255, 255)
    >>> color_from_str('hsv(360, 150, 100)')
    Traceback (most recent call last):
        ...
    ValueError: Expected value in range [0, 100]: 150 in hsv(360, 150, 100)
    >>> color_from_str('hsl(360, 100, 150)')
    Traceback (most recent call last):
        ...
    ValueError: Expected value in range [0, 100]: 150 in hsl(360, 100, 150)
    """

    def parse_triple(sub, maxvalues):
        literal = literal_eval(sub)
        if not isinstance(literal, tuple) or len(literal) != 3:
            raise ValueError(f'Expected 3-element triple: {x}')
        for value, maxvalue in zip(literal, maxvalues):
            if not isinstance(value, int) and not isinstance(value, float):
                raise ValueError(f'Expected float or int: {value} in {x}')
            if value < 0 or value > maxvalue:
                raise ValueError(f'Expected value in range [0, {maxvalue}]: {value} in {x}')
        return literal

    if x.lower().startswith('rgb('):
        r, g, b = parse_triple(x[3:], (255, 255, 255))
        return [r, g, b]
    elif x.lower().startswith('hsv('):
        h, s, v = parse_triple(x[3:], (360, 100, 100))
        return list(map(lambda b: round(b*255), colorsys.hsv_to_rgb(h/360, s/100, v/100)))
    elif x.lower().startswith('hsl('):
        h, s, l = parse_triple(x[3:], (360, 100, 100))
        return list(map(lambda b: round(b*255), colorsys.hls_to_rgb(h/360, l/100, s/100)))
    elif len(x) == 6:
        return list(bytes.fromhex(x))
    else:
        raise ValueError(f'Cannot parse color: {x}')


def find_all_subclasses(cls):
    """Recursively find loaded subclasses of `cls`.

    Returns a set of subclasses of `cls`.
    """
    sub = set(cls.__subclasses__())
    return sub.union([s for c in cls.__subclasses__() for s in find_all_subclasses(c)])


def get_runtime_dirs(appname='liquidctl'):
    """Return base directories for application runtime data.

    Directories are returned in order of preference.
    """
    if sys.platform == 'win32':
        dirs = [os.path.join(os.getenv('ProgramData'), appname)]
    elif sys.platform == 'darwin':
        dirs = [os.path.join('/Library/Application Support', appname)]
    else:
        # threat all other platforms as *nix and conform to XDG basedir spec
        dirs = []
        if XDG_RUNTIME_DIR:
            dirs.append(os.path.join(XDG_RUNTIME_DIR, appname))
        # regardless whether XDG_RUNTIME_DIR is set, fallback to /var/run if it
        # is available; this allows a user with XDG_RUNTIME_DIR set to still
        # find data stored by another user as long as it is in the fallback
        # path (see #37 for a real world use case)
        if os.path.isdir('/var/run'):
            dirs.append(os.path.join('/var/run', appname))
        assert dirs, 'Could not get a suitable place to store runtime data'
    return dirs


class _FilesystemBackend:
    def _sanitize(self, key):
        if isinstance(key, int):
            return str(key)
        if isinstance(key, str):
            if self._safe.match(key):
                return key
            key = bytes(key, encoding='utf-8')
        if isinstance(key, bytes):
            return base64.urlsafe_b64encode(key).decode()
        raise TypeError('key must be int, str or bytes')

    def __init__(self, key_prefixes):
        self._safe = re.compile(r'^\w[\w.]+$', flags=re.ASCII)
        key_prefixes = map(self._sanitize, key_prefixes)
        # compute read and write dirs from base runtime dirs: the first base
        # dir is selected for writes and prefered for reads
        self._read_dirs = [os.path.join(x, *key_prefixes) for x in get_runtime_dirs()]
        self._write_dir = self._read_dirs[0]
        os.makedirs(self._write_dir, exist_ok=True)
        if XDG_RUNTIME_DIR and os.path.commonpath([XDG_RUNTIME_DIR, self._write_dir]):
            # set the sticky bit to prevent removal during cleanup
            os.chmod(self._write_dir, 0o1700)
            LOGGER.debug('data in %s (within XDG_RUNTIME_DIR)', self._write_dir)
        else:
            LOGGER.debug('data in %s', self._write_dir)

    def load(self, key):
        for base in self._read_dirs:
            path = os.path.join(base, key)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, mode='r') as f:
                    data = f.read().strip()
                    if len(data) == 0:
                        value = None
                    else:
                        value = literal_eval(data)
                    LOGGER.debug('loaded %s=%r (from %s)', key, value, path)
            except OSError as err:
                LOGGER.warning('%s exists but cannot be read: %s', path, err)
                continue
            return value
        LOGGER.debug('no data (file) found for %s', key)
        return None

    def store(self, key, value):
        data = repr(value)
        assert literal_eval(data) == value, 'encode/decode roundtrip fails'
        path = os.path.join(self._write_dir, key)
        fd, tmp = tempfile.mkstemp(dir=self._write_dir, text=True)
        with open(fd, mode='w') as f:
            f.write(data)
            f.flush()
        os.replace(tmp, path)
        LOGGER.debug('stored %s=%r (in %s)', key, value, path)


class RuntimeStorage:
    """Unstable API."""

    def __init__(self, key_prefixes):
        self._backend = _FilesystemBackend(key_prefixes)
        self._cache = {}

    def load(self, key, of_type=None, default=None):
        """Unstable API."""
        if key in self._cache:
            value = self._cache[key]
        else:
            value = self._backend.load(key)
            self._cache[key] = value
        if value is None:
            return default
        elif of_type and not isinstance(value, of_type):
            return default
        else:
            return value

    def store(self, key, value):
        """Unstable API."""
        self._backend.store(key, value)
        self._cache[key] = value
        return value

    def load_int(self, key, default=None):
        """Unstable API.  Soon to be removed."""
        return self.load(key, of_type=int, default=default)

    def store_int(self, key, value):
        """Unstable API.  Soon to be removed."""
        self.store(key, value)
