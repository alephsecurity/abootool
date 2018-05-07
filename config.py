"""
Author: Roee Hay / Aleph Research / HCL Technologies
"""

from serializable import *
import json
import ConfigParser
DATA_PATH = "./data.json"
USER_CONFIG_PATH = "./abootool.cfg"
import io

config = None

class MetaConfig(type):

    def __getattr__(cls, name):
        return cls.get_config().__getattr__(name)

    def __setattr__(cls, name, val):
        return cls.get_config().__setattr__(name, val)

    def __repr__(cls):
        return cls.get_config().__repr__()


class Config(Serializable):
    __metaclass__ = MetaConfig

    config = None

    @classmethod
    def overlay(cls, data):
        dest = {}
        for t in data:
            if data[t]:
                dest[t] = data[t]
        cls.get_config().set_data(dest)

    @classmethod
    def get_config(cls):
        global config
        if not config:
            config = Config()
            config.set_data(json.load(file(DATA_PATH, "rb")))

            data = "[root]\n"+file(USER_CONFIG_PATH, "rb").read()
            fp = io.BytesIO(data)
            parser = ConfigParser.RawConfigParser()
            parser.readfp(fp)

            cfg = {}
            for k in parser.options("root"):
                try:
                    cfg[k] = parser.getboolean("root", k)
                    continue
                except ValueError:
                    pass

                try:
                    cfg[k] = parser.getint("root", k)
                    continue
                except ValueError:
                    pass

                try:
                    cfg[k] = parser.getfloat("root", k)
                    continue
                except ValueError:
                    pass

                cfg[k] = parser.get("root", k)

            config.set_data(cfg)

        return config

Config.get_config()
