"""
Author: Roee Hay / Aleph Research / HCL Technologies
"""

import aboot
from device import *


class OEMTester:
    def __init__(self, device):
        self.device = device
        self.bootloaders = self.get_relevant_bootloaders(device)
        self.strings = OEMTester.get_strings(self.bootloaders)
        self.positives = set()
        self.restricted = set()
        self.usberror = set()
        self.timedout = set()

    def test(self, resume=0):
        self.positives.clear()
        self.restricted.clear()
        self.timedout.clear()
        self.usberror.clear()

        if Config.use_strings_generator:
            n = 0
        else:
            n = len(self.strings)

        self.resume(resume)

        Progress.start()

        for i, cmd, lprcmd in self.test_strings():
            T("fastboot oem %s", cmd)
            Progress.show(i+resume, n, len(self.positives), len(self.restricted), len(self.timedout), len(self.usberror), cmd, lprcmd)

        Progress.end()
        I("Done.")
        self.dump_commands(self.positives, "Positive")
        self.dump_commands(self.restricted, "Restricted")
        self.dump_commands(self.usberror, "USB Error")
        self.dump_commands(self.timedout, "Timed-out")


    """
    Retrieves the bootloaders for the connected device.
    """
    @staticmethod
    def get_relevant_bootloaders(device):
        if Config.device:
            return aboot.by_device(Config.device)

        if Config.oem:
            return aboot.by_oem(Config.oem)

        if "" == device.device():
            I("Cannot detect device identifier, considering all ABOOTs")
            return aboot.all()

        bootloaders = aboot.by_device(device.device())

        if len(bootloaders) == 0:
            I("Cannot find bootloader images for %s, trying to resolve its OEM", device.device())
            try:
                vendor = Config.oems[device.device()]
                I("Falling back for images of %s", vendor)
                return aboot.by_oem(vendor)

            except KeyError:
                I("Cannot resolve oem of %s, considering all ABOOTs", device.device())
                return aboot.all()

        return bootloaders


    """
    Pulls all strings from the generator
    """
    @staticmethod
    def get_strings(bootloaders):
        if Config.use_strings_generator:
            I("Using strings generator...")
            return OEMTester.gen_strings(bootloaders)

        I("Loading strings...")
        strings = []
        map(lambda x: strings.append(x), OEMTester.gen_strings(bootloaders))
        I("Loaded %d strings from %d ABOOTs", len(strings), len(bootloaders))
        return strings

    """
    Strings generator
    Sanitizes and validates strings before their retrieval.
    """
    @staticmethod
    def gen_strings(bootloaders):
        strings = set()

        for bl in bootloaders:
            for s in bl.strings:
                s = CommandFilter.sanitize(s)
                if s in strings:
                    continue

                if Config.substrings:
                    for x in OEMTester.get_substrings(s):
                        if x in strings:
                            continue

                        if CommandFilter.validate(x):
                            strings.add(x)
                            yield x
                    continue

                if Config.split_space:
                    l = re.split(r"\s", s)
                    if len(l) > 1:
                        x = l[0]
                        if x in strings:
                            continue
                        if CommandFilter.validate(x):
                            strings.add(x)
                            yield x
                if CommandFilter.validate(s):
                    strings.add(s)
                    yield s

    @staticmethod
    def get_substrings(s):
        out = set()
        for i in xrange(len(s)):
            for j in xrange(len(s)-i):
                out.add(s[j:j+i+1])
        return out


    def resume(self, resume):
        if resume == 0:
            return
        I("Resuming from %d", resume)
        if Config.use_strings_generator:
            for i, x in enumerate(self.strings):
                if i == resume:
                    break
        else:
            self.strings = self.strings[resume:]

    def test_strings(self):
        prev = ""
        r = ""
        msg = ""
        timeout = False
        usb_error = False
        lprcmd = ""

        for i, s in enumerate(self.strings):
            try:
                yield (i, s, lprcmd)
                failed = False

                try:
                    r = self.device.oem(s, not timeout, not usb_error)
                    timeout, usb_error = (False, False)

                except FastbootRemoteFailure, e:
                    r = self.device.get_last_fb_output()
                    msg = e.msg
                    failed = True
                    timeout, usb_error = (False, False)

                except FastbootTimeoutException:
                    timeout, usb_error = (True, False)

                except FastbootCommandNotFound:
                    timeout, usb_error = (False, False)
                    continue

                except FastbootUSBException:
                    timeout, usb_error = (False, True)

                status = '+'
                if failed:
                    status = '-'
                    o = Device.normalize_fb_error(msg+r)
                    if "lock" in o or "restricted" in o or "support" in o or "not allowed" in o or "permission denied" in o:
                        if Config.show_output:
                            I("(R) fastboot oem %s", s)

                        lprcmd = s
                        self.restricted.add((s, r))
                        continue

                if usb_error:
                    self.usberror.add((s, r))
                    status = 'E'
                elif timeout:
                    self.timedout.add((s,r))
                    status = 'T'
                else:
                    self.positives.add((s, r))

                lprcmd = s

                if Config.show_output:
                    I("(%s) fastboot oem %s", status, s)
                    I("Result =\n"+r)
                else:
                    D("(%s) fastboot oem %s", status, s)
                    D("Result =\n"+r)

            except FastbootFatalError, e:
                E("Failed with index=%d, string=\"%s\", prev=\"%s\". Consider adding them to the filter.", i, s, prev)
                break

            finally:
                prev = s

    @staticmethod
    def dump_commands(cmds, name):
        cmds = list(OEMTester.clean_redundant_cmds(cmds))
        cmds.sort()
        I("Found %d %s OEM commands", len(cmds), name)
        for i,(cmd,resp) in enumerate(cmds, 1):
            I("%2d. %s", i, cmd)
            D("Result =\n"+resp)

    """
    Removes commands with the same response which include others, e.g.:
    'oem helpfoo'
    'oem help'
    We only want to report the latter.
    Quick and dirty O(N^2) with additional O(N) mem (small expected cmd set)
    """
    @staticmethod
    def clean_redundant_cmds(cmds):
        out = set()
        out.update(cmds)
        for c1, r1 in cmds:
            for c2, r2 in cmds:
                pattern = r"%s\s*.*" % re.escape(c2)
                if c1 != c2 and re.match(pattern, c1):
                    try:
                        out.remove((c1,r2))
                    except KeyError:
                        pass
                    break

        return out

class CommandFilter:
    @classmethod
    def sanitize(cls, s):
        if Config.strip_whitespace:
            s = s.strip()

        if Config.remove_breaks:
            s = s.replace("\n", "").replace("\r", "").replace("\f", "").replace("\v", "")

        return s.replace("oem ", "")

    @classmethod
    def validate(cls, s):
        if len(s) == 0:
            return False

        if Config.oem_only and not s.startswith("oem "):
            return False

        if Config.ignore_re and re.match(Config.ignore_re, s):
            T("Ignoring %s (matches pattern)", s)
            return False

        if Config.max_len > 0 and len(s) > Config.max_len:
            T("Ignoring %s (%d > %d)", s, len(s), Config.max_len)
            return False

        if Config.alphanum_only and not re.match("^([0-9a-zA-Z_-]|\s)+$", s):
            T("Ignoring %s (not alphanum)" % s)
            return False

        return True


class Progress:

    @staticmethod
    def start():
        pass

    @staticmethod
    def show(i, n, npos, nres, ntim, nerr,  cmd, last_pos):
        cmd = cmd.replace("\t","    ")
        last_pos = last_pos.replace("\t", "    ")
        sys.stdout.write("\r\033[1m")

        if Config.use_strings_generator:
            sys.stdout.write("[%06d/+%02d/R%02d/T%02d/E%02d] [CMD: %13.13s] [LAST: %13.13s]" % (i+1, npos, nres, ntim, nerr, cmd, last_pos))
        else:
            sys.stdout.write("[%s] [%06d/%06d/+%02d/R%02d/T%02d/E%02d] [CMD: %8.8s] [LAST: %8.8s]" % (Progress.bar(i+1, n), i+1, n, npos, nres, ntim, nerr, cmd, last_pos))
        sys.stdout.write("\033[0m")
        sys.stdout.flush()

    @staticmethod
    def end():
        sys.stdout.write("\n")
        sys.stdout.flush()

    @staticmethod
    def bar(i, n):
        t = int((i / float(n))*10)
        return "#" * t + "."*(10-t)

