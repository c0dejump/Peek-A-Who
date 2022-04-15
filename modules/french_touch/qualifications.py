#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
import json
import datetime
from bs4 import BeautifulSoup

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump"]

from static.colors import info, match, p_match, no_match, error, separator

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

currentDateTime = datetime.datetime.now()
date = currentDateTime.date()
global actual_year
actual_year = date.year

found = False

def get_infos(diplomas_type, identity, url, candidate, city, keyword):
    #print(" {}\033[33m{}\033[0m {} diplomas found: {}".format(p_match, identity, diplomas_type, url))

    matching = False

    for c in candidate:
        citylabel = c["cityLabel"] if "cityLabel" in c else "None"
        academy = c["link"].split("/")[1] if "link" in c else "None"

        if city != None and city.lower() in citylabel.lower():
            citylabel = "\033[32m{}\033[0m".format(citylabel)
            matching = True
        if city != None and city.lower() in academy:
            academy = "\033[32m{}\033[0m".format(academy)
            matching = True 
        if keyword != None and keyword.lower() in citylabel:
            citylabel = "\033[32m{}\033[0m".format(citylabel)
            matching = True
        if keyword != None and keyword.lower() in academy:
            academy = "\033[32m{}\033[0m".format(academy)
            matching = True 

        if not matching:
            print(" {}\033[33m{}\033[0m {} diplomas found: {}".format(p_match, identity, diplomas_type, url))
        else:
            print(" {}\033[32m{}\033[0m {} diplomas found: {}".format(match, identity, diplomas_type, url))
        print("   \u251c Name: {}".format(c["name"]))
        print("   \u251c City: {}".format(citylabel))
        print("   \u251c Academy: {}".format(academy))
        if diplomas_type == "Bac":
            print("   \u251c Type: {}".format(c["diplomaSerieLabel"]))   
        print("")


def brevet(identity, city, keyword, s):
    diplomas_type = "Brevet"
    for year in range(2015,actual_year):
        url = "https://search-candidate.linternaute.com/brevet/{}/1?candidate-name={}".format(year, identity.replace("_","%20"))
        req = s.get(url, verify=False, timeout=15, headers={'User-agent': UserAgent().random})
        res = json.loads(req.text)
        candidate = res["candidates"]
        if candidate != []:
            get_infos(diplomas_type, identity, url, candidate, city, keyword)
            found = True

def bac(identity, city, keyword, s):
    diplomas_type = "Bac"
    for year in range(2015,actual_year):
        url = "https://search-candidate.linternaute.com/bac/{}/1?candidate-name={}".format(year, identity.replace("_","%20"))
        req = s.get(url, verify=False, timeout=15, headers={'User-agent': UserAgent().random})
        res = json.loads(req.text)
        candidate = res["candidates"]
        if candidate != []:
            get_infos(diplomas_type, identity, url, candidate, city, keyword)
            found = True


def qualifications_search(identity, city, keyword, birth_year):
    print("\033[36m Qualifications search \033[0m")
    print(separator)
    s = requests.session()
    brevet(identity, city, keyword, s)
    if not birth_year or birth_year > 16:
        bac(identity, city, keyword, s)
    if not found:
        print(" {}Not diplomas found".format(no_match))
    print(separator)


if __name__ == '__main__':
    identity = ""
    run_actions(identity)