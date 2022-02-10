#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import csv


def raw_output(directory, modules_name, results):
    with open("{}/{}.txt".format(directory, modules_name), "a+") as raw:
        raw.write(results+"\n")
