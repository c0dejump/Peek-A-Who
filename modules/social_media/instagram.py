#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
import json

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def get_ig_info(req_ig):
	print(req_ig.text)


def check_instagram(firstname, lastname, pseudo):
	url = "https://www.instagram.com/{}/?__a=1".format(pseudo) #Connected mode
	req_ig = requests.get(url, verify=False)
	if req_ig.status_code == 200:
		print(" + {} seem exist")
		get_ig_info(req_ig)

	else:
		print(" - {} seem not exist")


if __name__ == '__main__':
	firstname = None 
	lastname = None
	pseudo = 'natan_ubx'
	check_instagram(firstname, lastname, pseudo)