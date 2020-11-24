import signal
import time
from dataclasses import dataclass

# Control the pump duty, fans duty, and RGB
# using a Kraken pump and Smart Device V2
# -----------------------------------------
#
# Cooling mostly depends on the AIO water temperature,
# because that is what the radiator is cooling.
# However the CPU temperature is monitored as well
# and can trigger a cooling boost if necessary.
#
# This reads from /tmp/crom-cpu-monitor
# and writes to   /tmp/crom-aio-monitor and /tmp/crom-case-monitor
#
# Manual mode is available by writing it to /tmp/crom-mode.
# echo 3 > /tmp/crom-mode
#
# Goals:
# - silent during low CPU load
# - rapid ramp up during high load
# - avoid mode flickering
# - ensure positive pressure
# - safety by setting high cooling on error

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

BOOST_CPU_TEMP = 69
BOOST_CPU_MODE = 3
BOOST_CPU_TIME = 15
SAFE_MODE = 3
FAN_CPU = "fan1"
FAN_REAR = "fan2"
FAN_TOP = "fan3"

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

class Server:

    mode = -1
    boost_cooldown = 0
    keep_running = True

    def __init__(self, aio, case):
        self.cooling = Cooling(aio, case)
        self.rgb = Rgb(aio, case)

        signal.signal(signal.SIGTERM, self.exit_gracefully)

        try:
            self.loop()
        except Exception as e:
            self.journal(e)
            self.safe_mode()
            raise e

    def loop(self):
        while True:
            if not self.keep_running:
                self.safe_mode()
                break
            status = CromStatus(self.cooling.status(), self.read_cpu_temp())
            self.write_status(status)

            mode = self.mode_from_water_temp(status.cooling.aio.water_temp)

            manual = self.read_manual_mode()
            mode = manual if manual is not None and mode - manual < 2 else mode

            if self.boost_cooldown:
                if status.cpu_temp < BOOST_CPU_TEMP:
                    self.boost_cooldown -= 1
                mode = max(3, mode)
            elif status.cpu_temp >= BOOST_CPU_TEMP and mode < 3:
                self.journal("Boost cooling due to high CPU temp")
                self.boost_cooldown = BOOST_CPU_TIME
                mode = BOOST_CPU_MODE

            if mode != self.mode:
                self.journal(f'Mode: {self.mode} -> {mode} ({PROFILE[mode]})')
                self.mode = mode
                self.rgb.set_mode(mode)
                self.cooling.set_mode(mode)

            time.sleep(1)

    def mode_from_water_temp(self, temp: float):
        for m, c in enumerate(PROFILE):
            # wait for a 0.3º reduction to avoid switching modes too often
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
        open("/tmp/crom-aio-monitor", "w").write(ks)

        c = status.cooling.case
        cs = str(f'{c.cpu_fan.duty} {c.rear_fan.duty} {c.top_fan.duty}')
        open("/tmp/crom-case-monitor", "w").write(cs)

    def read_cpu_temp(self):
        try:
            return int(open("/tmp/crom-cpu-monitor").read().split(' ')[1])
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

    def exit_gracefully(self, signum, frame):
        self.journal("Stop")
        self.keep_running = False

    def safe_mode(self):
        self.rgb.set_theme("error")
        self.cooling.set_mode(SAFE_MODE)

    def journal(self, msg):
        print(f'CROM Server - {msg}')

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
        self.case.set_fixed_speed(FAN_CPU, cpu)
        self.case.set_fixed_speed(FAN_REAR, rear)
        self.case.set_fixed_speed(FAN_TOP, top)

class Rgb:

    first_run = True

    def __init__(self, aio, case) -> None:
        self.aio = aio
        self.case = case

    def set_mode(self, mode: int):
        if self.first_run:
            self.first_run = False
            self.set_theme("init")
            time.sleep(1)
            self.set_mode(mode)
        else:
            self.set_theme(PROFILE[mode][5])

    def set_theme(self, theme: str):
        if theme == "frost":
            self.ring("fading", "000033 0011ff 0000ff")
            self.logo("fading", "000066 000033")
            self.strip("fixed", "8888ff")
        elif theme == "cool":
            self.ring("fading", "ffffff 444444")
            self.logo("fading", "111111 333333")
            self.strip("super-fixed", "0000ff 00ff00 ff0000 0000ff 00ff00 ff0000 0000ff 00ff00 ff0000 0000ff")
        elif theme == "tepid":
            self.ring("fading", "440000 ff1100 ff0000")
            self.logo("fading", "660000 330000")
            self.strip("fading", "ffffff 0000ff 00ff00 ff0000", "slower")
        elif theme == "warm":
            self.ring("fading", "330000 ff2200 ff0000", "fastest")
            self.logo("fading", "880000 330000", "faster")
            self.strip("fading", "ffffff 0000ff 00ff00 ff0000")
        elif theme == "toasty":
            self.ring("tai-chi", "ff0000 ff2a00", "fastest")
            self.logo("fading", "880000 881100", "fastest")
            self.strip("fading", "ff0000 0000ff", "fastest")
        elif theme == "fusion":
            self.ring("wings", "0000ff")
            self.logo("spectrum-wave", None, "fastest")
            self.strip("spectrum-wave", None, "fastest")
        elif theme == "init":
            self.ring("fixed", "00ff00")
            self.logo("fixed", "00ff00")
            self.strip("fixed", "00ff00")
        else: # error feedback
            self.ring("fixed", "000000")
            self.logo("fading", "ff0000 000000", "fastest")
            self.strip("alternating-3", "ffffff ff0000", "fastest")

    def ring(self, mode, colors, speed = "normal"):
        self.aio.set_color("ring", mode, self.color_map(colors), speed=speed)

    def logo(self, mode, colors, speed = "normal"):
        self.aio.set_color("logo", mode, self.color_map(colors), speed=speed)

    def strip(self, mode, colors = None, speed = "normal"):
        self.case.set_color("led1", mode, self.color_map(colors), speed=speed)

    def color_map(self, colors: str):
        from liquidctl.util import color_from_str
        return map(color_from_str, colors.split(' ') if colors else [])
