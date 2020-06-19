# The liquidctl API

The liquidctl API is currently being overhauled.  While backwards compatibility
(on the stable interfaces) will be ensured, this document approaches the API
using the new paths and constructs, which have not yet been stabilized.

For now this only shows how the API _could_ look like.

## Getting started with the Python REPL

Let's begin by starting a Python 3 REPL and importing the `liquidctl` package.

    $ python3
    >>> import liquidctl

Now let's try to print all devices that liquidctl can control in this system.
To detect compatible devices, we can use `liquidctl.find_devices`; it's a
generator that yields liquidctl devices.

All liquidctl devices have a `description` attribute that describes the
physical device as precisely _as possible._

    >>> for dev in liquidctl.find_devices():
    ...     print(f'{dev.description}')
    NZXT Smart Device (V1)
    NZXT Kraken X (X42, X52, X62 or X72)

Notice how the specific Kraken X model is not known: in some cases the exact
model is simply _not_ available to the operating system, liquidctl or the
software that ships with the device.

So far we handle all devices generically, but sometimes we're looking for a
particular type of device.  For example, let's import the `Kraken2` class.

    >>> from liquidctl.kraken2 import Kraken2

Now we can search directly for devices of the `Kraken2` class.  Notice how we
call `next` on the result of `find_devices` to get the first result.

    >>> kraken = next(liquidctl.find_devices(cls=Kraken2))
    >>> print(kraken.description)
    NZXT Kraken X (X42, X52, X62 or X72)

Since we have a handle to a device, let's try to print the current status
information.

    >>> with kraken:
    ...     status = kraken.get_status()
    ...     for field, value, unit in status:
    ...         print(f'{field}: {value} {unit}')
    Liquid temperature: ...
    Fan speed: ...
    Pump speed: ...
    Firmware version: ...

The first step was actually to connect to the device.  There is a specific
method for this – `connect` – but instead we used the handle as a context
manager.  The context manage also automatically called `disconnect` for us,
which is mandatory even in the case of errors.

So far we've only printed read-only data from the device.  Before moving on to
more precise descriptions of the API, let's do a simple experiment and change
the color of the cooler according to what time it is right now.

Let's begin by computing, with sensible precision and using only standard
library functions, the `fraction_of_day`.

    >>> import time
    >>> now = time.localtime()
    >>> fraction_of_day = now.tm_hour/24 + now.tm_min/3600

Next, let's decide how to map this to a color.  For example, we can consider a
hue–saturation–value color model, and simply set the hue to `fraction_of_day`.

However, liquidctl methods expect colors to be RGB triples.  So, again using
standard library constructs, let's convert our desired HSV color to RGB.

    >>> import colorsys
    >>> hsv_fractions = (fraction_of_day, 1, 1)
    >>> rgb_fractions = colorsys.hsv_to_rgb(*hsv_fractions)

Notice how we indicated that those tuples hold fractions.  That's because we
need to do a final adjustment: our triple has values in the interval (0, 1),
but the liquidctl method we're going to call expects RGB triples with the
integer red/blue/green values in the range 0–255.

    >>> rgb = tuple(int(x * 255) for x in rgb_fractions)

The conversion is straightforward, but should not be necessary.  In fact, it
wont be in a future version of liquidctl.

Now that we have successfully computed our desired color, let's send it to the
cooler.

    >>> with kraken:
    ...     kraken.set_color(channel='sync', mode='fixed', colors=[rgb])
