#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
from googlesearch import search 
from config import max_search, stop_search

from modules.social_media.linkedin import linkedin_scraping

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


WARNING = "[!] "

def google_s(identity, phone_n, mail, pseudo, city):
    """
    google_s: function to search on google
    """
    args = locals()
    print("\033[36m Google search \033[0m")
    queries = []

    for k, v in args.items():
        if v != None and k != "city":
            queries.append("{}".format(v))
            queries.append("intext:{} site:pastebin.com".format(v))
    try:
        for q in queries:
            print(" [i] Google search {}".format(q))
            for j in search(q, tld="com", num=max_search, stop=stop_search, pause=2.6):
                #num: Number of results we want.
                #stop: The last result to retrieve. Use None to keep searching forever.
                try:
                    req_url_found = requests.get(j, verify=False, timeout=4)
                    if req_url_found.status_code not in [404, 408, 503, 405, 428, 412, 429, 403, 401]:
                        print(" \033[32m[{}]\033[0m {}".format(req_url_found.status_code, j))
                        if "linkedin" in j:
                            print("\033[36m Linkedin search \033[0m")
                            linkedin_scraping(j)
                        """try:
                            with open(directory+"/site/{}/google_dorks.txt".format(directory), "a+") as raw:
                                raw.write("{}\n".format(j))
                        except:
                            pass"""
                            #traceback.print_exc() #DEBUG
                    elif req_url_found.status_code in [403, 401]:
                        print(" \033[31m[{}]\033[0m {}".format(req_url_found.status_code, j))
                    else:
                        print(" \033[31m[{}]\033[0m {}".format(req_url_found.status_code, j))
                except:
                    #traceback.print_exc() #DEBUG
                    print("  {}Error with URL {}".format(WARNING, j))
            print("")
    except:
        print("  {} Google captcha seem to be activated, try it later...\n".format(WARNING))