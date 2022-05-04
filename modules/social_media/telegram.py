#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

#https://t.me/schr0dinger

def telegram_search(pseudo, city, keyword, picture):
    print("\033[36m Telegram search\033[0m")
    print(separator)

    url = "https://t.me/{}".format(pseudo)
    req = requests.get(url, verify=False)

    matching = False

    soup = BeautifulSoup(req.text, "html.parser")
    description = soup.find('div', {'class': 'tgme_page_description'})
    description = description.text.strip().replace("\t", " ").replace("  ", " ") if description else "N/A"
    if not "If you have" in description:
        if city and city in description.lower() or keyword and [k.lower() for k in keyword if k.lower() in description.lower()]:
            desc = "\033[32m{}\033[0m".format(description)
            matching = True
        print(" {}Telegram seems exist on: https://t.me/{}".format(p_match if not matching else match, pseudo))
        if not matching:
            print("   \u251c Description : {}".format(description))
        else:
            print("   {}{}".format(match, desc))
    else:
        print(" {}Telegram user not found".format(no_match))
    print(separator)

if __name__ == '__main__':
    telegram_search("codejump")