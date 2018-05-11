"""
Roee Hay / Aleph Research / HCL Technologies
"""

import os
import zipfile
import io
import tempfile
import shutil
import subprocess
import aboot
from log import *
import re


def add(path):

    if os.path.isfile(path):
        T(path)
        if Config.treat_as_blob:
            add_blob_file(path)
        add_image(path)
    else:
        if Config.treat_as_blob:
            E("Specified path must be a blob")
            return

        for root,dirs,files in os.walk(path):
            for f in files:
                T(f)
                if add_image(os.path.join(root, f)):
                    print("Added: {}".format(f))
                else:
                    print("Skipped: {}".format(f))


def add_image(path):
    return add_ota_file(path) or add_factory_file(path) or add_moto_file(path) or add_sony_file(path)


def add_blob_file(path):
    return add_any_image(BlobArchive, path, Config.oem, Config.device, Config.build)


def add_ota_file(path):
    return add_any_image(OTA, path)


def add_factory_file(path):
    return add_any_image(Factory, path)


def add_moto_file(path):
    return add_any_image(MotoArchive, path)


def add_sony_file(path):
    return add_any_image(SonyArchive, path)


def add_any_image(cls, *kargs):
    try:
        img = cls(*kargs)
        if not img.get_aboot_image():
            return
        return add_aboot(img)

    except (zipfile.BadZipfile, IOError, ImageArchiveParseException):
        pass


def add_aboot(archive):
    name, fp = archive.get_aboot_image()
    bl = aboot.ABOOT.create_from_bootloader_image(fp=fp, oem=archive.get_oem(),
                                                  device=archive.get_device(), build=archive.get_build(),
                                                  src=os.path.basename(archive.get_path()),
                                                  name=name,
                                                  strprefix=Config.string_prefix)

    skipped = "(SKIPPED)"
    if bl.save('%s/%s-%s-%s.json' % (Config.data_path, bl.oem, bl.device, bl.build)):
        skipped = ""

    I("%s (%d) %s SAVING" % (bl, len(bl.strings), skipped))
    return bl


class ImageArchiveParseException(Exception):
    pass


class FactoryParseException(ImageArchiveParseException):
    pass


class OTAParseException(ImageArchiveParseException):
    pass


class MotoParseException(ImageArchiveParseException):
    pass

class SonyParseException(ImageArchiveParseException):
    pass

class BlobArchiveParseException(ImageArchiveParseException):
    pass


class ImageArchive(object):


    def __init__(self, path):
        self.path = path
        self.oems = None
        self.parse()

    def get_path(self):
        return self.path

    def parse(self):
        raise NotImplementedError()

    def get_device(self):
        raise NotImplementedError()

    def get_aboot_image(self):
        raise NotImplementedError()

    def get_build(self):
        raise NotImplementedError()

    def get_timestamp(self):
        raise NotImplementedError()

    def get_oem(self):
        raise NotImplementedError()

    def __getitem__(self, k):
        return self.__dict__[k]


class OTA(ImageArchive):

    def parse(self):
        self.zip =  zipfile.ZipFile(self.path)
        self.metadata = None
        self.fingerprint = None

    def get_metadata(self):
        if self.metadata:
            return self.__dict__

        try:
            self.metadata = self.zip.read("META-INF/com/android/metadata")
            D("metadata = %s", self.metadata)
        except KeyError:
            raise OTAParseException()

        for line in self.metadata.split("\n"):

            s = line.split('=')
            if len(s) < 2:
                continue
            k,v = s
            self.__dict__[k] = v

        return self.__dict__

    def get_device(self):
        self.get_metadata()
        return self.get_buildfingerprint().split(':')[0].split('/')[2]

    def get_buildfingerprint(self):
        # e.g. google/volantis/flounder:7.1.1/N4F27B/3853226:user/release-keys

        if None != self.fingerprint:
            return self.fingerprint

        try:
            self.fingerprint = self.get_metadata()["post-build"]
            return self.fingerprint
        except KeyError:
            pass

        try:
            otaid = self.get_metadata()["ota-id"]
            vendor = None
            device = None
            if "ONELOxygen" in otaid:
                vendor = 'oneplus'
                device = 'oneplus1'
            elif "OnePlus" in otaid:
                vendor = 'oneplus'
                if "OnePlus3T" in otaid:
                    device = 'oneplus3t'
                elif "OnePlus3" in otaid:
                    device = 'oneplus3'
                elif "OnePlus2" in otaid:
                    device = 'oneplus2'
                elif "OnePlusX" in otaid:
                    device = 'oneplusx'

            if vendor and device:
                self.fingerprint = '%s/%s/%s:?/%s/?:?' % (vendor, device, device, otaid)
                return self.fingerprint
        except KeyError:
            pass

        raise OTAParseException()

    def get_timestamp(self):
        self.get_metadata()
        try:
            ts = self.get_metadata()["post-timestamp"]
            return ts
        except KeyError:
            return None

    def get_vendor(self):
        return self.get_buildfingerprint().split(':')[0].split('/')[0].lower()

    def get_oem(self):
        d = self.get_device()
        try:
            return OEMS.dev2oem(d)
        except KeyError:
            return self.get_vendor()

    def get_aospver(self):
        return self.get_buildfingerprint().split(':')[0].split('/')[0]

    def get_build(self):
        return self.get_buildfingerprint().split(':')[1].split('/')[1].lower()

    def get_keys(self):
        return self.get_buildfingerprint().split(':')[2]



    def get_aboot_image(self):
        d = self.get_device()

        for path in Config.ota_prevalent_aboot_paths:
            try:
                return (os.path.basename(path), self.zip.open(path))
            except KeyError:
                pass

        if 'flounder' in d:
            data = self.zip.read('bootloader.img')[256:]
            fp = io.BytesIO(data)
            return ('hboot.img', zipfile.ZipFile(fp).open('hboot.img'))

        if 'fugu' == d:
            tmpdir = tempfile.mkdtemp()
            tmpfile = tempfile.NamedTemporaryFile()
            self.zip.extract('droidboot.img', tmpdir)
            curdir = shutil.abspath(".")
            os.chdir(tmpdir)
            try:
                subprocess.check_output([Config.ota_umkbootimg_path, "droidboot.img"], stderr=subprocess.STDOUT)
                subprocess.check_output([Config.ota_unpack_ramdisk_path, "initramfs.cpio.gz"],stderr=subprocess.STDOUT)
            except OSError as e:
                E("Cannot execute umkbootimg/unpack_ramdisk while handling %s. " % self.path)
                E("ota_umkbootimg_path = %s" % Config.ota_umkbootimg_path)
                E("ota_unpack_ramdisk_path = %s" % Config.ota_unpack_ramdisk_path)
                raise OTAParseException()

            data = file("./ramdisk/system/bin/droidboot", "rb").read()
            tmpfile.write(data)
            tmpfile.seek(0)
            os.chdir(curdir)
            shutil.rmtree(tmpdir)
            return ('droidboot',tmpfile)


class Factory(ImageArchive):

    def parse(self):
        self.zip =  zipfile.ZipFile(self.path)
        self._device = None
        self._build = None
        self._image = None

        root = len(self.zip.namelist()) > 1 and self.zip.namelist()[0] or None
        if not root:
            raise FactoryParseException()

        try:
            self._device, self._build = root[:-1].split("-")
        except ValueError:
            raise FactoryParseException()

        for n in self.zip.namelist():
            if "/image-" in n:
                self._image = n
                return

        raise FactoryParseException()

    def get_image_path(self):
        return self._image

    def get_device(self):
        return self._device

    def get_oem(self):
        d = self.get_device()
        try:
            return OEMS.dev2oem(d)
        except KeyError:
            return "unknown"

    def get_build(self):
        return self._build.lower();

    def get_aboot_image(self):
        D("Factory detected device = %s " % self.get_device())
        if self.get_device() == "marlin" or self.get_device() == "sailfish":
            if not self.get_image_path():
                raise FactoryParseException()

            data = self.zip.read(self.get_image_path())
            fp = io.BytesIO(data)
            return ('aboot.img',zipfile.ZipFile(fp).open("aboot.img"))

        # ryu is still unsupported

        if "ryu" == self.get_device():
            raise FactoryParseException()

        # unsupported, use OTA
        if "volantis" in self.get_device() or "fugu" in self.get_device():
            raise FactoryParseException()

        # for the rest we fallback to bootloader-*.img which is supposed to contain aboot.
        # Not very robust as data may be compressed, encoded, whatever.

        if Config.factory_fallback_bootloader:
            for n in self.zip.namelist():
                if "bootloader-" in n:
                    D("Found bootloader: %s" % n)
                    name = os.path.basename(n)
                    data = self.zip.read(n)
                    return (n, io.BytesIO(data))

        raise FactoryParseException()


"""
For Moto we over-approximate and return all of the bootloader strings (not just ABOOT)
"""
class MotoArchive(ImageArchive):

    def get_oem(self):
        return "motorola"

    def parse(self):
        self.zip =  zipfile.ZipFile(self.path)
        self.device = None
        self.build = None

        try:
            data = self.zip.open("flashfile.xml").read()
            self.device = re.search(r"phone_model model=\"(.*?)\"", data).group(1)
            self.build = re.search(r"software_version version=\"(.*?)\"", data).group(1).split()[2]
            D("model = %s", self.device)
            D("version = %s", self.build)
        except (IOError, KeyError):
            raise MotoParseException()

    def get_device(self):
        return self.device

    def get_aboot_image(self):
        try:
            return ("bootloader.img",self.zip.open("bootloader.img"))
        except KeyError:
            raise MotoParseException()

    def get_build(self):
        return self.build


class BlobArchive(ImageArchive):

    def __init__(self, path, oem, device, build):
        self.oem = oem
        self.device = device
        self.build = build
        super(BlobArchive, self).__init__(path)

    def parse(self):
        pass

    def get_device(self):
        return self.device

    def get_aboot_image(self):
        try:
            return (os.path.basename(self.path), open(self.path))
        except IOError:
            raise BlobArchiveParseException()

    def get_build(self):
        return self.build

    def get_oem(self):
        return self.oem

class SonyArchive(ImageArchive):

    def get_oem(self):
        return "sony"

    def parse(self):
        self.zip =  zipfile.ZipFile(self.path)
        self.device = None
        self.build = None

        try:
            data = self.zip.read("META-INF/MANIFEST.MF")
            for line in data.split("\r\n"):
                s = re.split(r"[:]\s+", line)
                if len(s) != 2:
                    continue

                k,v = s
                if k == "device":
                    self.device = v.lower()

                if k == "version":
                    self.build = v

        except (IOError, KeyError):
            raise SonyParseException()

    def get_device(self):
        return self.device

    def get_aboot_image(self):
        names = []
        for n in self.zip.namelist():
            if "emmc_appsboot" in n:
                names.append(os.path.basename(n))
                data = self.zip.read(n)

        if len(names) == 0:
            raise SonyParseException()

        return ("/".join(names), io.BytesIO(data))

    def get_build(self):
        return self.build


class OEMS:

    _oems = None

    @classmethod
    def load(cls):
        cls._oems = {}
        for o in Config.oems:
            for d in Config.oems[o]:
                cls._oems[d] = o

    @classmethod
    def dev2oem(cls, dev):
        if None != cls._oems:
            return cls._oems[dev]

        cls.load()
        return cls._oems[dev]
