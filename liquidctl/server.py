import logging
import time

from liquidctl.util import color_from_str

LOGGER = logging.getLogger(__name__)

ambiance=""
pump_profile = [
    (20, 20), 
    (27, 70), 
    (28, 100)
]

def start_server(dev, opts):
    LOGGER.info(f'Server: {dev.description} {dev.get_status(**opts)}')

    set_ambiance(dev, "init")

    dev.set_speed_profile("pump", pump_profile)

    while True:
        status = dev.get_status(**opts)
        temp = float(status[0][1])
        txt = str(f'{temp} {status[1][1]} {status[2][1]}')
        # print(txt)
        with open("/tmp/kraken", "w") as f:
            f.write(txt)

        if temp >= 29:
            set_ambiance(dev, "fusion")
        elif temp >= 27:
            set_ambiance(dev, "warm")
        else:
            set_ambiance(dev, "cool")

        time.sleep(opts['sleep'] if 'sleep' in opts else 1)

def set_ambiance(dev, a):
    global ambiance
    if a == ambiance:
        return
    ambiance = a
    LOGGER.info(f'Switching to {ambiance}')
    if a == "cool":
        set_ring(dev, "fading", "330000 ff0000 ff1100 ff0000")
        set_logo(dev, "fading", "660000 330000")
    elif a == "warm":
        set_ring(dev, "covering-marquee", "ff0000 ff1100", "faster")
        set_logo(dev, "fading", "880000 881100", "fastest")
    elif a == "fusion":
        set_ring(dev, "wings", "0000ff")
        set_logo(dev, "fading", "0000ff 666666")
    else:
        set_ring(dev, "fixed", "000000")
        set_logo(dev, "fading", "660000 000000", "fastest")

def set_ring(dev, mode, colors, speed = "normal"):
    dev.set_color("ring", mode, map(color_from_str, colors.split(' ')), speed=speed)

def set_logo(dev, mode, colors, speed = "normal"):
    dev.set_color("logo", mode, map(color_from_str, colors.split(' ')), speed=speed)
