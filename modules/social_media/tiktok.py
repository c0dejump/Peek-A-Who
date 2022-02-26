#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
import requests
from bs4 import BeautifulSoup
from modules.parsing import parsing_data

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def get_tiktok(endpoint, s):
    url_tiktok = "https://www.tiktok.com/@{}".format(endpoint)
    req_tiktok = s.get(url_tiktok, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
    if req_tiktok.status_code not in [404, 403, 401]:
        soup = BeautifulSoup(req_tiktok.text, "html.parser")
        find_name = soup.find('h1', {'data-e2e': 'user-subtitle'})
        description = soup.find('h2', {'data-e2e': 'user-bio'})
        site = soup.find('span', {'class': re.compile(r'tiktok-847r2g-SpanLink*')})
        print(site)
        print(""" \033[32m\u251c {}\033[0m TikTok username seem exit with on https://www.tiktok.com/@{}:
    \u251c Real name: {}
    \u251c Description: {}
    \u251c Site: {}
            """.format(endpoint, endpoint, "\033[32m{}\033[0m".format(find_name.text if find_name.text else "\033[31mNone\033[0m"), description.text.replace("\n", " "), site.text if site else "None"))


def tiktok_username(identity, pseudo, city, keyword, picture):

    print("\033[36m TikTok search\033[0m")
    print("\033[36m-\033[0m"*30)
    
    s = requests.session()

    if pseudo:
        get_tiktok(pseudo, s)
    else:
        datas = parsing_data(identity, pseudo, city, keyword)
        for endpoint in datas:
            get_tiktok(endpoint, s)
    print("\033[36m-\033[0m"*30)


if __name__ == '__main__':
    tiktok_username(identity=None, pseudo=None, city=None, picture=None)