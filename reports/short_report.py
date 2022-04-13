#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#modules in standard library
import sys, os, re
from static.colors import info, match, p_match, no_match, error, separator


def short_text_report():
	print("\033[34m Short text report:\033[0m")
	print(" #TODO")