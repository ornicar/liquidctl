import logging
import time
from dataclasses import dataclass

from liquidctl.util import color_from_str

@dataclass
class CoolerStatus:
    duty: int
    rpm: int

@dataclass
class AioStatus:
    water_temp: float
    pump: CoolerStatus

@dataclass
class CaseStatus:
    cpu_fan: CoolerStatus
    rear_fan: CoolerStatus
    top_fan: CoolerStatus

@dataclass
class CoolingStatus:
    aio: AioStatus
    case: CaseStatus

@dataclass
class CromStatus:
    cooling: CoolingStatus
    cpu_temp: int

PROFILE = [
    # water     aio     cpu     rear    top     RGB
    # tempº     pump%   duty%   duty%   duty%   theme
    [0,         30,     0,      0,      0,      "frost"],
    [26,        45,     30,     0,      0,      "cool"],
    [27,        60,     50,     40,     0,      "tepid"],
    [28,        75,     70,     40,     40,     "warm"],
    [29,        90,     100,    60,     60,     "toasty"],
    [30,        100,    100,    100,    100,    "fusion"]
]

class Server:

    mode = -1

    def __init__(self, aio, case):
        self.aio = aio
        self.case = case
        self.cooling = Cooling(aio, case)
        self.rgb = Rgb(aio, case)

        self.loop()

    def journal(self, msg):
        print(f'CROM Server - {msg}')

    def loop(self):
        while True:
            status = CromStatus(self.cooling.status(), self.read_cpu_temp())
            self.write_status(status)

            mode = self.mode_from_water_temp(status.cooling.aio.water_temp)

            manual = self.read_manual_mode()
            mode = manual if manual and mode - manual < 4 else mode

            if mode != self.mode:
                self.journal(f'Mode: {self.mode} -> {mode} ({PROFILE[mode]})')
                self.mode = mode
                self.rgb.set_mode(mode)
                self.cooling.set_mode(mode)

            time.sleep(1)

    def mode_from_water_temp(self, temp: float):
        for m, c in enumerate(PROFILE):
            if (temp == c[0] - 0.1 or temp == c[0] - 0.2) and m == self.mode:
                mode = m
                break
            if temp < c[0]:
                break
            mode = m
        return mode

    def write_status(self, status: CoolingStatus):
        k = status.cooling.aio
        ks = str(f'{k.water_temp} {k.pump.duty} {k.pump.rpm}')
        open("/tmp/aio-monitor", "w").write(ks)

        c = status.cooling.case
        cs = str(f'{c.cpu_fan.duty} {c.rear_fan.duty} {c.top_fan.duty}')
        open("/tmp/case-monitor", "w").write(cs)

    def read_cpu_temp(self):
        try:
            return int(open("/tmp/cpu-monitor").read().split(' ')[1])
        except Exception as e:
            self.journal(e)
            return 99 # assume the worst

    def read_manual_mode(self):
        try:
            mode = max(0, min(len(PROFILE) - 1, int(open("/tmp/crom-mode").read())))
            if mode != self.mode:
                self.journal(f'Manual mode: {mode}')
            return mode
        except:
            return None

class Cooling:

    def __init__(self, aio, case):
        self.aio = aio
        self.case = case

    def status(self):
        ks = self.aio.get_status()
        water_temp = float(ks[0][1])
        if not water_temp or water_temp < 15:
            print(f'ERROR bad water temperature: {water_temp}')
            water_temp = 28
        cs = self.case.get_status()
        def fan_value(fan_id: int, name: str):
            return int(next((f[1] for f in cs if f[0] == f'Fan {fan_id} {name}'), 0))
        return CoolingStatus(
            AioStatus(
                water_temp,
                CoolerStatus(int(ks[1][1]), int(ks[2][1]))
            ),
            CaseStatus(
                CoolerStatus(fan_value(1, "duty"), fan_value(1, "speed")),
                CoolerStatus(fan_value(2, "duty"), fan_value(2, "speed")),
                CoolerStatus(fan_value(3, "duty"), fan_value(3, "speed"))
            )
        )

    def set_mode(self, mode: int):
        _, pump, cpu, rear, top, *_ = PROFILE[mode]
        self.aio.set_fixed_speed("pump", pump)
        self.case.set_fixed_speed("fan1", cpu)
        self.case.set_fixed_speed("fan2", rear)
        self.case.set_fixed_speed("fan3", top)

class Rgb:

    def __init__(self, aio, case) -> None:
        self.aio = aio
        self.case = case

    def set_mode(self, mode: int):
        self.set_theme(PROFILE[mode][5])

    def set_theme(self, theme: str):
        self.strip("fading", "ffffff 0000ff 00ff00 ff0000")
        if theme == "frost":
            self.ring("fading", "000033 0011ff 0000ff")
            self.logo("fading", "000066 000033")
            self.strip("fixed", "0000ff")
        elif theme == "cool":
            self.ring("fading", "330000 ff1100 ff0000")
            self.logo("fading", "660000 330000")
        elif theme == "tepid":
            self.ring("fading", "330000 ff1100 ff0000", "fastest")
            self.logo("fading", "660000 330000", "faster")
        elif theme == "warm":
            self.ring("tai-chi", "ff0000 ff2a00", "fastest")
            self.logo("fading", "880000 881100", "fastest")
        elif theme == "toasty":
            self.ring("tai-chi", "ff0000 ff5500", "fastest")
            self.logo("fading", "aa0000 aa3300", "fastest")
            self.strip("fading", "ff0000 0000ff", "fastest")
        elif theme == "fusion":
            self.ring("wings", "0000ff")
            self.logo("spectrum-wave", None, "fastest")
            self.strip("spectrum-wave", None, "fastest")
        else: # error feedback
            self.ring("fixed", "000000")
            self.logo("fading", "660000 000000", "fastest")
            self.strip("alternating-3", "ffffff ff0000", "fastest")

    def ring(self, mode, colors, speed = "normal"):
        self.aio.set_color("ring", mode, self.color_map(colors), speed=speed)

    def logo(self, mode, colors, speed = "normal"):
        self.aio.set_color("logo", mode, self.color_map(colors), speed=speed)

    def strip(self, mode, colors = None, speed = "normal"):
        self.case.set_color("led1", mode, self.color_map(colors), speed=speed)

    def color_map(self, colors: str):
        return map(color_from_str, colors.split(' ') if colors else [])
