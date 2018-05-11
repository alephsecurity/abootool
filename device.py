"""
Author: Roee Hay / Aleph Research / HCL Technologies
"""

import os
import re
from serializable import Serializable
from adb import fastboot,common,usb_exceptions,adb_commands, sign_pycryptodome
from log import *
from config import Config
from enum import Enum
import time
import usb1
import subprocess


class Device:

    def __init__(self, serial=None):
        self.connected = False
        self.fb = None
        self.data = DeviceData()
        self.usbdev = None
        self.last_output = None
        self.set_state(State.DISCONNECTED)
        self.serial = serial
        self.fb_error = None
        self.fb_error_timeout = False

    @staticmethod
    def get_fastboot_devices():
        return common.UsbHandle.FindDevices(fastboot.DeviceIsAvailable, timeout_ms=Config.timeout)

    @staticmethod
    def get_adb_devices():
        return common.UsbHandle.FindDevices(adb_commands.DeviceIsAvailable, timeout_ms=Config.timeout)

    def find_fastboot_device(self):
        return self.find_device(Device.get_fastboot_devices())

    def find_adb_device(self):
        return self.find_device(Device.get_adb_devices())

    def find_device(self, devices):

        i = 0
        for d in devices:
            i += 1
            if not self.serial or d.serial_number == self.serial:
                return d
        return

    """
    Reboots to bootloaders. First it tries to use python-adb, falling back to the adb binary.
    """
    def adb_reboot_bootloader(self):
        I("adb: rebooting to bootloader")
        try:
            self.adb().RebootBootloader()
            return
        except UnicodeDecodeError:
            # https://github.com/google/python-adb/issues/52
            D("python-adb bug, falling-back to adb bin")
        except usb_exceptions.WriteFailedError:
            # Happens when adb server is running
            D("adb server is running, cannot use python-adb, falling-back to adb bin")

        # fall-backs to adb binary
        if self.serial and re.match(r"\w+", self.serial()):
            adb_cmd = Config.adb_path + " -s %s reboot bootloader 2>/dev/null" % self.serial
        else:
            adb_cmd = Config.adb_path + " reboot bootloader 2>/dev/null"

        os.system(adb_cmd)
        time.sleep(5)
        self.set_state(State.DISCONNECTED)

    """
    Wait for the device to be connected in either fastboot or adb.
    """
    def wait_for_device(self):
        while State.DISCONNECTED == self.state:
            usbdev = self.find_fastboot_device()
            if None != usbdev:
                try:
                    usbdev.Open()
                    I("fastboot connected to %s", usbdev.serial_number)
                except usb1.USBError as e:
                    usbdev.Close()
                    time.sleep(5)
                    continue

                self.usbdev = usbdev
                self.set_state(State.CONNECTED_FB)
                continue

            usbdev = self.find_adb_device()
            if None != usbdev:
                try:
                    usbdev.Open()
                    I("adb: connected")
                    self.set_state(State.CONNECTED_ADB_DEVICE)

                except usb1.USBErrorBusy as e:
                    self.set_state(self.adb_get_state())
                    if State.CONNECTED_ADB_DEVICE == self.state:
                        I("adb: connected")

                except usb1.USBError:
                    usbdev.Close()
                    time.sleep(5)
                    continue

                self.usbdev = usbdev
                continue

            I("Waiting for device...")
            time.sleep(5)

    """
    Waits for the device to be in fastboot mode. If it's in adb, it will reboot it to bootloader
    """
    def wait_for_fastboot(self):

        while State.CONNECTED_FB != self.state:

            if State.CONNECTED_ADB_DEVICE == self.state:
                self.adb_reboot_bootloader()
                self.wait_for_device()

            if State.DISCONNECTED == self.state:
                self.wait_for_device()

    def adb(self):
        signer = sign_pycryptodome.PycryptodomeAuthSigner(os.path.expanduser(Config.adb_key_path))
        device = adb_commands.AdbCommands()
        return device.ConnectDevice(rsa_keys=[signer])

    def fastboot(self):
        cmds = fastboot.FastbootCommands()
        while True:
            try:
                dev = cmds.ConnectDevice()
                return dev
            except:
                print("Device offline, go back to bootloader!")
                time.sleep(3)

    def serial_number(self):
        self.wait_for_device()
        return self.usbdev.serial_number

    def get_last_fb_output(self):
        return self.last_output.get()


    """ 
    Conduct a single fastboot command
    """
    def do_fb_command(self, func, allow_timeout=False, *args, **kargs):
        self.wait_for_fastboot()
        self.last_output = CmdLogger()

        try:
            getattr(self.fastboot(), func)(info_cb=self.last_output, *args, **kargs)
            return self.last_output.get()

        except fastboot.FastbootRemoteFailure as e:
            r = self.get_last_fb_output()
            msg = e.args[1]
            raise FastbootRemoteFailure(msg)

        except fastboot.FastbootStateMismatch as e:
            W("fastboot state mistmatch")
            self.disconnect()
            raise FastbootUSBException("")

        except usb_exceptions.LibusbWrappingError as e:
            if "LIBUSB_ERROR_TIMEOUT" in str(e.usb_error):
                if allow_timeout:
                    D("Allowed timeout during FB command: %s, args = %s, kargs = %s", func, str(*args), str(**kargs))
                    raise FastbootTimeoutException()

                D("timeout during FB command: %s, args = %s, kargs = %s", func, str(*args), str(**kargs))

            self.disconnect()
            raise FastbootUSBException(e.usb_error)

    """
    Conduct a fastboot command until success (handles USB disconnections etc).
    It first resolves (if needed) the command not found error, by issuing a bogus command.
    """
    def wait_for_fb_command(self, func, allow_timeout = False, allow_usb_error = False, *args, **kargs):
        while True:
            try:
                self.resolve_fb_error()
                return self.do_fb_command(func, allow_timeout, *args, **kargs)
            except FastbootUSBException as e:
                if allow_usb_error:
                    raise e
                W("USB Error (%s) detected during command: %s, args = %s, kargs = %s", e.msg, func, str(*args),
                  str(**kargs))

    def set_state(self, state):
        self.state = state

    """
    Disconnect the device and clean-up everything.
    """
    def disconnect(self):
        self.clear_fb_error()
        self.set_state(State.DISCONNECTED)
        if None != self.usbdev:
            self.usbdev.Close()
            self.usbdev = None

    """
    Issue a fastboot oem command.
    """
    def oem(self, cmd, allow_timeout=False, allow_usb_error = False):
        try:
            r = self.wait_for_fb_command("Oem", allow_timeout, allow_usb_error, cmd)
            if self.is_fb_error(r, cmd):
                raise FastbootCommandNotFound()

            return r

        except FastbootTimeoutException:
            if self.fb_error_timeout:
                raise FastbootCommandNotFound()
            raise FastbootTimeoutException

        except FastbootRemoteFailure as e:
            r = self.get_last_fb_output()
            error = e.msg
            if self.is_fb_error(error+r, cmd):
                raise FastbootCommandNotFound()
            raise FastbootRemoteFailure(error)

    """
    Get a remote variable through fastboot
    """
    def getvar(self, k):
        try:
            return self.data[k]
        except KeyError:
            try:
                self.data[k] = self.wait_for_fb_command("Getvar", False, False, k)
            except fastboot.FastbootRemoteFailure:
                return ""

        return self.data[k]

    def product(self):
        return self.getvar("product")

    def unlocked(self):
        return self.getvar("unlocked")

    def oemprojectname(self):
        return self.getvar("oem_project_name")

    """
    Try to resolve the bootloader name according to hints from fastboot info
    """
    def bootloader_name(self):
        p = self.product()
        # OnePlus devices
        if p.startswith("msm") and self.oemprojectname():
            return self.oemprojectname()

        return p

    """
    Resolve the real device name
    """
    def device(self):
        try:
            return Config.bootloader_names[self.bootloader_name()]
        except KeyError:
            return self.bootloader_name()


    """
    Query the ADB state
    """
    def adb_get_state(self):
        try:
            output = subprocess.check_output([Config.adb_path, "get-state"], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            return State.DISCONNECTED

        if "device" in output:
            return State.CONNECTED_ADB_DEVICE

        return State.DISCONNECTED

    def clear_fb_error(self):
        self.fb_error_timeout = False
        self.fb_error = None

    """
    Resolve the fastboot command not found error by issuing a bogus command.
    Some devices do not return when issuing a non-existing command, we handle those too. 
    """
    def resolve_fb_error(self):
        if None != self.fb_error:
            return

        try:
            self.fb_error = self.do_fb_command("Oem", True, Config.oem_error_cmd)
        except FastbootRemoteFailure as e:
            self.fb_error = e.msg + self.get_last_fb_output()
        except FastbootTimeoutException as e:
            D("Error is indicated by USB timeout")
            self.fb_error_timeout = True
            return
        self.fb_error = self.normalize_fb_error(self.fb_error)
        D("Error str: " + self.fb_error)

    """
    Classifies whether a given response for a command indicates it's a non-existing one.
    """
    def is_fb_error(self, msg, cmd):
        cmd = self.normalize_fb_error(cmd)
        msg = self.normalize_fb_error(msg)

        if msg == self.fb_error:
            return True

        if self.normalize_fb_error(self.fb_error.replace(Config.oem_error_cmd, cmd)) == msg:
            return True

        if self.normalize_fb_error(self.fb_error.replace(Config.oem_error_cmd, re.split("\s", cmd)[0])) == msg:
            return True

        return False

    @staticmethod
    def normalize_fb_error(error):
        try:
            return error.replace("\n", "").lower()
        except UnicodeDecodeError:
            return error


class FastbootException(Exception): pass
class FastbootNotConnectedException(FastbootException):  pass
class FastbootTimeoutException(FastbootException):  pass
class FastbootCommandNotFound(FastbootException):   pass
class FastbootFatalError(FastbootException):  pass
class FastbootRemoteFailure(FastbootException):
    def __init__(self, msg):
        self.msg = msg

class FastbootUSBException(FastbootException):
    def __init__(self, msg):
        self.msg = msg


class DeviceData(Serializable):
    pass

class CmdLogger:

    def __init__(self):
        self.output = []

    def __call__(self, fbmsg):
        self.output.append(fbmsg.message)

    def get(self):
        return "\n".join(self.output)

class State(Enum):
    DISCONNECTED = 0,
    CONNECTED_FB = 1,
    CONNECTED_ADB_DEVICE = 2
