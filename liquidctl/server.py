import signal
import time
from dataclasses import dataclass
from typing import List, Optional

# Control the pump duty, fans duty, and RGB
# of a Kraken pump and Smart Device V2.
# Also controls power and fans of a RX 580 GPU.
# -----------------------------------------
#
# This code is only intended to work for my
# very specific build. Don't try it on yours!
#
# Goals:
# - silent during low CPU load
# - rapid ramp up during high load
# - avoid mode flickering
# - ensure positive pressure
# - safety by setting high cooling on stop or error
# - instant boost on high cpu or gpu temp
#
# Cooling mostly depends on the AIO water temperature,
# because that is what the radiator is cooling.
# However the CPU temperature is monitored as well
# and can trigger a cooling boost if necessary.
#
# Reads from /run/crom/cpu-monitor and /run/crom/gpu-monitor
# Writes to  /run/crom/aio-monitor and /run/crom/case-monitor
#
# Disabling RGB is done by creating /run/crom/rgb-off.
# echo 1 > /run/crom/rgb-off
#
# Changing turbo value is done by writing to /run/crom/turbo

FAN_CPU1 = "fan1" # push/pull
FAN_CPU2 = "fan2" # push
FAN_CASE = "fan3"
RUN_DIR = "/run/crom"

# quietest - 0 - 1 - 2 - 3 - 4 - coolest
turbos = [0, 1, 2, 3, 4, 5]

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
    cpu_fan1: CoolerStatus
    cpu_fan2: CoolerStatus
    case_fan: CoolerStatus

@dataclass
class CromStatus:
    aio: AioStatus
    case: CaseStatus
    cpu_temp: int
    gpu_temp: int

class Server:

    keep_running = True

    def __init__(self, aio, case):
        self.aio = Aio(aio)
        self.case = Case(case)
        self.rgb = Rgb(aio, case)
        self.gpu = Gpu()

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

            status = CromStatus(self.aio.status(), self.case.status(), self.read_cpu_temp(), self.gpu.read_temp())

            self.gpu.tick(status.gpu_temp)

            self.aio.tick(status)

            new_rgb_theme = self.case.tick(status)

            if self.rgb.read_off() != self.rgb.off:
                self.journal("Toggle RGB")
                self.rgb.off = not self.rgb.off
                new_rgb_theme = self.case.rgb_theme()

            self.rgb.set_theme(new_rgb_theme)

            time.sleep(1)

    def read_cpu_temp(self):
        try:
            return int(open(f'{RUN_DIR}/cpu-monitor').read().split(' ')[1])
        except Exception as e:
            self.journal(e)
            return 99 # assume the worst

    def exit_gracefully(self, signum, frame):
        self.journal("Stop")
        self.keep_running = False

    def safe_mode(self):
        self.rgb.set_theme("error")
        self.aio.set_safe_mode()
        self.case.set_safe_mode()
        self.gpu.set_safe_mode()

    def journal(self, msg):
        print(f'CROM Server - {msg}')

class Aio:

    mode = -1
    cpu_temp_hist : List[int] = []

    profile = [
        # CPU       aio
        # tempº     pump%
        (0,         30),
        (60,        50),
        (64,        70),
        (68,        80),
        (72,        100)
    ]

    def __init__(self, aio):
        self.aio = aio

    def status(self):
        ks = self.aio.get_status()
        water_temp = float(ks[0][1])
        if not water_temp or water_temp < 15:
            print(f'ERROR bad water temperature: {water_temp}')
            water_temp = 28
        return AioStatus(
            water_temp,
            CoolerStatus(int(ks[2][1]), int(ks[1][1]))
        )

    def tick(self, status: CromStatus):
        open(f'{RUN_DIR}/aio-monitor', "w").write(
            str(f'{status.aio.water_temp} {status.aio.pump.duty} {status.aio.pump.rpm}\n'))
        self.cpu_temp_hist.append(status.cpu_temp)
        self.cpu_temp_hist = self.cpu_temp_hist[-20:]
        max_cpu_temp = max(self.cpu_temp_hist)
        mode = self.mode_from_cpu_temp(max_cpu_temp)
        if mode != self.mode:
            self.journal(f'Mode: {self.mode} -> {mode} {self.profile[mode]} cpu: {status.cpu_temp}º max: {max_cpu_temp}º')
            self.mode = mode
            self.set_mode(mode)

    def mode_from_cpu_temp(self, temp: float):
        mode = len(self.profile) - 1
        for m, c in enumerate(self.profile):
            if temp < c[0]:
                break
            mode = m
        return mode

    def set_mode(self, mode: int):
        self.aio.set_fixed_speed("pump", self.profile[mode][1])

    def set_safe_mode(self):
        self.set_mode(3)

    def journal(self, msg):
        print(f'CROM Aio  - {msg}')

class Case:

    turbo = -1
    mode = -1

    base = 20
    profile = [
        # water     cpu1    cpu2    case    RGB
        # tempº     duty%   duty%   duty%   theme
        (0,         20,     25,     20,     "frost"),
        (base + 8,  30,     35,     30,     "cool"),
        (base + 9,  40,     45,     40,     "tepid"),
        (base + 10, 55,     55,     50,     "warmish"),
        (base + 11, 65,     65,     60,     "warm"),
        (base + 12, 75,     75,     70,     "toasty"),
        (base + 13, 85,     85,     85,     "burning"),
        (base + 14, 100,    100,    100,    "fusion")
    ]

    def __init__(self, case):
        self.case = case
        self.read_turbo()

    def status(self):
        cs = self.case.get_status()
        def fan_value(fan_id: int, name: str):
            return int(next((f[1] for f in cs if f[0] == f'Fan {fan_id} {name}'), 0))
        return CaseStatus(
            CoolerStatus(fan_value(1, "duty"), fan_value(1, "speed")),
            CoolerStatus(fan_value(2, "duty"), fan_value(2, "speed")),
            CoolerStatus(fan_value(3, "duty"), fan_value(3, "speed"))
        )

    def tick(self, status: CromStatus):
        self.read_turbo()
        open(f'{RUN_DIR}/case-monitor', "w").write(
            str(f'{status.case.cpu_fan1.duty} {status.case.cpu_fan2.duty} {status.case.case_fan.duty} {self.turbo}\n'))
        mode = self.mode_from_water_temp(status.aio.water_temp)
        if mode != self.mode:
            self.journal(f'Mode: {self.mode} -> {mode} {self.profile[mode]} cpu: {status.cpu_temp}º water: {status.aio.water_temp}º, turbo: {self.turbo}')
            self.mode = mode
            self.set_mode(mode)
            return self.rgb_theme()
        return None

    def mode_from_water_temp(self, temp: float):
        mode = len(self.profile) - 1
        temp = temp + self.turbo
        for m, c in enumerate(self.profile):
            # wait for a 0.5º reduction to avoid switching modes too often
            if (temp < c[0] and temp > c[0] - 0.5) and m == self.mode:
                mode = m
                break
            if temp < c[0]:
                break
            mode = m
        return mode

    def set_mode(self, mode: int):
        _, cpu1, cpu2, case, *_ = self.profile[mode]
        self.case.set_fixed_speed(FAN_CPU1, cpu1)
        self.case.set_fixed_speed(FAN_CPU2, cpu2)
        self.case.set_fixed_speed(FAN_CASE, case)

    def set_safe_mode(self):
        self.set_mode(4)

    def rgb_theme(self):
        return self.profile[self.mode][4]

    def read_turbo(self):
        self.turbo = 1
        try:
            self.turbo = int(open(f'{RUN_DIR}/turbo').read())
        except:
            pass

    def journal(self, msg):
        print(f'CROM Case - {msg}')

class Rgb:

    first_run = True
    off = False

    def __init__(self, aio, case) -> None:
        self.aio = aio
        self.case = case

    def set_theme(self, theme: Optional[str]):
        if theme is None:
            return
        if self.first_run:
            self.first_run = False
            self._set_theme("init")
            time.sleep(1)
            self._set_theme(theme)
        else:
            self._set_theme(theme)

    def _set_theme(self, theme: str):
        if self.off and theme != "error":
            self.ring("off", None)
            self.logo("fixed", "100060")
            self.strip("off", None)
        elif theme == "frost":
            self.ring("fading", "000033 0011ff 0000ff")
            self.logo("fading", "000066 000033")
            self.strip("fixed", "8888ff")
        elif theme == "cool":
            self.ring("fading", "ffffff 444444")
            self.logo("fading", "111111 333333")
            self.strip("super-fixed", "0000ff 00ff00 ff0000 0000ff 00ff00 ff0000 0000ff 00ff00 ff0000 0000ff")
        elif theme == "tepid" or theme == "warmish":
            self.ring("fading", "440000 ff1100 ff0000")
            self.logo("fading", "660000 330000")
            self.strip("fading", "ffffff 0000ff 00ff00 ff0000", "slower")
        elif theme == "warm" or theme == "toasty":
            self.ring("fading", "330000 ff2200 ff0000", "faster")
            self.logo("fading", "880000 330000", "faster")
            self.strip("fading", "ffffff 0000ff 00ff00 ff0000")
        elif theme == "burning":
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
            self.ring("off", None)
            self.logo("fading", "ff0000 000000", "fastest")
            self.strip("off", None)

    def ring(self, mode, colors, speed = "normal"):
        self.aio.set_color("ring", mode, self.color_map(colors), speed=speed)

    def logo(self, mode, colors, speed = "normal"):
        self.aio.set_color("logo", mode, self.color_map(colors), speed=speed)

    def strip(self, mode, colors = None, speed = "normal"):
        self.case.set_color("led1", mode, self.color_map(colors), speed=speed)

    def color_map(self, colors: str):
        from liquidctl.util import color_from_str
        return map(color_from_str, colors.split(' ') if colors else [])

    def read_off(self):
        try:
            return open(f'{RUN_DIR}/rgb-off').read().startswith("1")
        except:
            return False

# https://dri.freedesktop.org/docs/drm/gpu/amdgpu.html
class Gpu:
    profile = [
        # tempº     fan%
        [0,         37],
        [58,        37],
        [62,        46],
        [66,        60],
        [74,        100]
    ]
    mode = -1
    last_set = time.time()
    sysfs_dir = '/sys/class/drm/card0/device'
    hwmon_dir = f'{sysfs_dir}/hwmon/hwmon4'

    def __init__(self) -> None:
        self.write_manual_pwm()
        self.write_manual_power_profile()

    def tick(self, temp: int):
        mode = self.mode_from_temp(temp)
        if mode != self.mode:
            self.journal(f'Mode: {self.mode} -> {mode} fan: {self.profile[mode][1]}% temp: {temp}º')
            self.write_mode(mode)
            self.mode = mode
        elif time.time() > self.last_set + 600:
            self.journal("Periodically set manual PWM and mode")
            self.write_manual_pwm()
            self.write_mode(mode)

    def set_safe_mode(self):
        self.write_mode(2)

    def write_mode(self, mode: int):
        try:
            percent = self.profile[mode][1]
            pwm = int(percent / 100 * 255)
            open(f'{self.hwmon_dir}/pwm1', "w").write(str(pwm))
            self.last_set = time.time()
        except Exception as e:
            self.journal(e)

    def write_manual_pwm(self):
        try:
            open(f'{self.hwmon_dir}/pwm1_enable', "w").write("1")
        except Exception as e:
            self.journal(e)

    def write_manual_power_profile(self):
        try:
            open(f'{self.sysfs_dir}/power_dpm_force_performance_level', "w").write("manual")
            open(f'{self.sysfs_dir}/pp_power_profile_mode', "w").write("2")
        except Exception as e:
            self.journal(e)

    def mode_from_temp(self, temp: int):
        mode = len(self.profile) - 1
        for m, c in enumerate(self.profile):
            # wait for a 10º reduction to avoid switching modes too often
            if (temp < c[0] and temp > c[0] - 10) and m == self.mode:
                mode = m
                break
            if temp < c[0]:
                break
            mode = m
        return mode

    def read_temp(self):
        try:
            return int(open(f'{RUN_DIR}/gpu-monitor').read().split(' ')[1])
        except Exception as e:
            self.journal(e)
            return 99 # assume the worst

    def journal(self, msg):
        print(f'CROM GPU  - {msg}')
