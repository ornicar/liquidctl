# NVIDIA graphics cards
_Driver API and source code available in [`liquidctl.driver.nvidia`](../liquidctl/driver/nvidia.py)._

Support for these cards in only available on Linux.

Additional requirements must also be met:

- optional Python dependency `smbus` is available
- `i2c-dev` kernel module has been loaded
- specific unsafe features have been opted in
- r/w permissions to card-specific `/dev/i2c-*` devices

---

Jump to a specific card:

* _Series 10/Pascal:_
    - [EVGA GTX 1080 FTW](#evga-gtx-1080-ftw)
<!-- - [EVGA GTX 1070 FTW](#evga-gtx-1070-1080-ftw) -->
<!-- - [EVGA GTX 1080 FTW](#evga-gtx-1070-1080-ftw) -->


## EVGA GTX 1080 FTW
<!-- EVGA GTX 1070/1080 FTW -->

Experimental.  Only RGB lighting supported.

Unsafe features:

- `smbus`: enable SMBus support; SMBus devices may not tolerate writes or reads
  they do not expect
- `evga_pascal`: enable access to the specific graphics cards

### Initialization

Not required for this device.

### Retrieving the current RGB lighting mode and color

In verbose mode `status` reports the current RGB lighting settings.

```
$ liquidctl status --verbose --unsafe=smbus,evga_pascal
EVGA GTX 1080 FTW (experimental)
├── Mode      Fixed  
└── Color    2aff00  
```

### Controlling the LED

The table bellow summarizes the available channels, modes and their
associated number of required colors.

| Channel    | Mode        | Required colors |
| ---------- | ----------- | --------------- |
| `led`      | `off`       |               0 |
| `led`      | `fixed`     |               1 |
| `led`      | `breathing` |               1 |
| `led`      | `rainbow`   |               0 |

```
$ liquidctl set led color off --unsafe=smbus,evga_pascal
$ liquidctl set led color fixed ff8000 --unsafe=smbus,evga_pascal
$ liquidctl set led color breathing "hsv(90,85,70)" --unsafe=smbus,evga_pascal
$ liquidctl set led color rainbow --unsafe=smbus,evga_pascal
```

The settings configured on the device are normally volatile, and are
cleared whenever the graphics card is powered down.

It is possible to store them in non-volatile controller memory by
passing `--non-volatile`.  But as this memory has some unknown yet
limited maximum number of write cycles, volatile settings are
preferable, if the use case allows for them.

```
$ liquidctl set led color fixed 00ff00 --non-volatile --unsafe=smbus,evga_pascal
```
