#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
from bs4 import BeautifulSoup
from config import FB_USERNAME, FB_PASSWORD
from output import raw_output

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def facebook_search(dir_name, firstname, lastname, pseudo):

    if FB_USERNAME == "" and FB_PASSWORD == "":

        print("\033[36m Facebook search without account\033[0m")

        if firstname and lastname:
            count_result = 0

            account = ""

            exclude_word = ["photo", "cursor", "login"]

            url = "https://m.facebook.com/public/{}-{}".format(firstname, lastname)
            req = requests.get(url, verify=False, timeout=15)
            soup = BeautifulSoup(req.text, "html.parser")
            find_link = soup.find_all('a')
            for s in find_link:
                if firstname.lower() in s.get('href') and "login" not in s.get('href') and "cursor" not in s.get('href') and "login" not in s.get('href') and "next" not in s.get('href'):
                    account = s.get('href')
                    print(" [+] Potential account found: {}".format(s.get('href')))
                    count_result += 1
            if count_result > 0:
                print(" + {} account found\n".format(count_result))
            else:
                print(" No account found\n".format(count_result))
        else:
            url = "https://www.facebook.com/{}".format(pseudo)
            req = requests.get(url, verify=False, timeout=15)
            if req.status_code == 200:
                print(" [+] Potential account found: https://m.facebook.com/{}\n".format(pseudo))
            else:
                print(" [-] No account found with this pseudo\n")
    else:
        print("\033[36m Facebook search with account \033[0m")
