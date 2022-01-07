#!/usr/bin/python

"""
Author: Roee Hay / Aleph Research / HCL Technologies
"""

import device
from oemtester import OEMTester
import argparse
from config import Config
import log
from log import *
import aboot
import image


def main():

    adjustLevels()
    parser = argparse.ArgumentParser("ABOOTOOL")
    parser.add_argument('-e','--oem', dest='oem', help='Specify OEM to load ABOOT strings of, otherwise try to autodetect')
    parser.add_argument('-d','--device', dest='device', help='Specify device to load ABOOT strings of, otherwise try to autodetect')
    parser.add_argument('-b','--build', dest='build', help='Specify build to load ABOOT strings of, otherwise try to autodetect')
    parser.add_argument('-r', '--resume', type=int, default=0, dest='index', help='Resume from specified string index')
    parser.add_argument('-i', '--ignore', dest='ignore_re', help='Ignore pattern (regexp)')
    parser.add_argument('-g', '--use-strings-generator', action='store_true', default=False, dest='use_strings_generator', help='Use strings generator instead of loading everything a priori (fast but degrades progress)')
    parser.add_argument('-o', '--output', action='store_true', dest='show_output', help="Show output of succeeded fastboot commands. Verbose logging overrides this")

    parser.add_argument('-l','--aboots-list', action='store_true', dest='aboots', help="List available ABOOTs")
    parser.add_argument('-a','--images-add', dest='images_path', help="Add ABOOT strings from OTA/Factory images. Either a file or a directory.")
    parser.add_argument('-B','--blob', action='store_true', default=False, dest='treat_as_blob', help="Treat specified path as ABOOT blob")
    parser.add_argument('-S','--string-prefix', default="", dest='string_prefix', help="When inserting new images, only treat strings with specified prefix")

    parser.add_argument('-s','--device-serial', dest='serial', help="Specify device fastboot SN")
    parser.add_argument('-v', '--verbose', action='store_true', dest='verbose', help='Enable verbose logging')
    parser.add_argument('-vv', '--moreverbose', action='store_true', dest='moreverbose', help='Even more logging')
    parser.add_argument('-t', '--timeout', type=int, default=5000, dest='timeout', help='USB I/O timeout (ms)')

    args = parser.parse_args()
    if args.verbose:
        log.setVerbose()

    if args.moreverbose:
        log.setVerbose(True)

    I("Welcome to abootool by Aleph Research, HCL technologies")

    Config.overlay(args.__dict__)
    T("Config = %s", Config)

    if args.treat_as_blob:
        if not args.oem or not args.device or not args.build:
            E("Missing OEM/Device/Build specifiers")
            return 1

    if args.aboots:
        I("BY OEM:")
        I("-------")
        dump_data(aboot.by_oem())
        I("")
        I("BY DEVICE:")
        I("----------")
        dump_data(aboot.by_device())

        return 0

    if args.images_path:
        image.add(args.images_path)
        return 0

    dev = device.Device(args.serial)

    name = dev.device()
    adjustLevels()
    if name:
        I("Device reported name = %s", name)

    OEMTester(dev).test(args.index)

    return 0


def dump_data(data):
    keys = list(data.keys())
    keys.sort()
    nkeys = len(keys)
    for i in range(0, nkeys - 1, 2):
        I("%17s: %3d    %17s: %3d", keys[i], len(data[keys[i]]), keys[i + 1], len(data[keys[i + 1]]))

    if 1 == nkeys % 2:
        I("%17s: %3d", keys[nkeys - 1], len(data[keys[nkeys - 1]]))


if __name__ == "__main__":
    sys.exit(main())

