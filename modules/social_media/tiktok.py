#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
import json
from bs4 import BeautifulSoup
from modules.parsing import parsing_data
from modules.facial_recognition import face_identification

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def get_tiktok(endpoint, s, picture):
    url_tiktok = "https://www.tiktok.com/node/share/user/@{}".format(endpoint)
    req_tiktok = s.get(url_tiktok, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
    res = json.loads(req_tiktok.text)
    userinfo = res["userInfo"]
    if userinfo != {}:
        name = userinfo["user"]["nickname"]
        description = userinfo["user"]["signature"]
        try:
            site = userinfo["user"]["bioLink"]["link"]
        except:
            site = None
        pic = userinfo["user"]["avatarMedium"]
        print(""" \033[32m\u251c {}\033[0m TikTok username seem exit with on https://www.tiktok.com/@{}:
    \u251c Real name: {}
    \u251c Description: {}
    \u251c Site: {}
            """.format(endpoint, endpoint, "\033[32m{}\033[0m".format(name), description.replace("\n", " "), site if site else "None"))


def tiktok_username(identity, pseudo, city, keyword, picture):

    print("\033[36m TikTok search\033[0m")
    print("\033[36m-\033[0m"*30)
    
    s = requests.session()

    if pseudo:
        get_tiktok(pseudo, s, picture)
    else:
        datas = parsing_data(identity, pseudo, city, keyword)
        for endpoint in datas:
            get_tiktok(endpoint, s, picture)
    print("\033[36m-\033[0m"*30)


if __name__ == '__main__':
    tiktok_username(identity=None, pseudo=None, city=None, picture=None)