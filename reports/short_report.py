#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#modules in standard library
import sys, os, re
from static.colors import info, match, p_match, no_match, error, separator


def short_text_report(dir_name):
	matching_tags = ["facebook", "instagram", "tiktok", "linkedin"]
	print("\033[34mShort text report:\033[0m")
	#TODO
	#Doing link and category
	all_files = os.listdir(dir_name)
	for al in all_files:
		with open(dir_name + "/" + al, "r") as get_results:
			if al.split(".")[0] in matching_tags:
				print("{} Potential {} account found:".format(match, al.split(".")[0]))
				for gr in get_results:
					print(" - {}".format(gr.strip()))
			for gr in get_results:
				print(gr.strip())
