"""
Author: Roee Hay / Aleph Research / HCL Technologies
"""

import json
import os.path

class Serializable(object):

    def __init__(self):
        self.__dict__ = {}

    def __getattr__(self, item):
        return self.__dict__[item]

    def __getitem__(self, item):
        return self.__getattr__(item)

    def __setattr__(self, item, val):
        if item == "__dict__":
            return
        self.__dict__[item] = val

    def __setitem__(self, item, val):
        self.__setattr__(item, val)

    def __repr__(self):
        return self.dump()

    def dump(self):
        return json.dumps(self.__dict__, indent=4, separators=(',', ': '))

    def set_data(self, data):
        self.__dict__.update(data)
        return self

    def save(self,path):
        if os.path.isfile(path):
            return False
        open(path, "wb").write(self.dump())
        return True
