#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
import json
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator
from output import raw_output
from modules.parsing import parsing_data
from modules.image_analysis.facial_recognition import face_identification

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

try:
    from Queue import Queue
except:
    import queue as Queue
import threading
from threading import Thread

try:
    enclosure_queue = Queue()
except:
    enclosure_queue = Queue.Queue()

#TODO: put threading


"""
if website structur tiktok change (work 1x/2):

url_tiktok = "https://www.tiktok.com/node/share/user/@{}".format(endpoint)
    print(url_tiktok)
    req_tiktok = s.get(url_tiktok, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"}, timeout=15)
    print(req_tiktok.text)
    res = json.loads(req_tiktok.text)
    userinfo = res["userInfo"]
    print(userinfo)
    if userinfo != {}:
        name = userinfo["user"]["nickname"]
        description = userinfo["user"]["signature"]
        try:
            site = userinfo["user"]["bioLink"]["link"]
        except:
            site = None
        pic = userinfo["user"]["avatarMedium"]
        print(\033[32m\u251c {}\033[0m TikTok username seem exit with on https://www.tiktok.com/@{}:
    \u251c Real name: {}
    \u251c Description: {}
    \u251c Site: {}
            .format(endpoint, endpoint, "\033[32m{}\033[0m".format(name), description.replace("\n", " "), site if site else "None"))
"""

def get_tiktok(i, q, city, keyword, s):
    global bar
    bar = 0 
    for d in range(len_datas):
        endpoint = q.get()
        url_tiktok = "https://www.tiktok.com/@{}".format(endpoint)
        req_tiktok = s.get(url_tiktok, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})

        matching = False

        if req_tiktok.status_code not in [404, 403, 401]:
            soup = BeautifulSoup(req_tiktok.text, "html.parser")
            find_name = soup.find('h1', {'data-e2e': 'user-subtitle'})
            description = soup.find('h2', {'data-e2e': 'user-bio'})
            site = soup.find('span', {'class': re.compile(r'tiktok-847r2g-SpanLink*')})
            desc = description.text.replace("\n", " ")

            if city:
                if city.lower() in desc.lower():
                    desc = "\033[32m{}\033[0m".format(desc)
                    matching = True
            if keyword:
                if keyword.lower() in desc.lower():
                    desc = "\033[32m{}\033[0m".format(desc)
                    matching = True
            if not matching:
                print(" {}\033[33m{}\033[0m TikTok seem exist with on https://www.tiktok.com/@{}:".format(p_match, endpoint, endpoint))
            else:
                print(" {}\033[32m{}\033[0m TikTok seem exist with on https://www.tiktok.com/@{}:".format(match, endpoint, endpoint))
            print("   \u251c Real name: {}".format(find_name.text if find_name.text else "\033[31mNone\033[0m"))
            print("   \u251c Description: {}".format(desc)) if "No bio yet" not in desc else None
            print("   \u251c Site: {}".format(site.text)) if site else None
        q.task_done()
        bar += 1
        sys.stdout.write(" {}/{} | https://www.tiktok.com/@{} \r".format(bar, len_datas, endpoint))


def tiktok_search(identity, pseudo, city, keyword, picture, birth_year):

    print("\033[36m TikTok search\033[0m")
    print(separator)
    
    s = requests.session()

    global len_datas
    len_datas = 0

    if pseudo:
        get_tiktok(pseudo, city, keyword, s)
    else:
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for n in datas:
            len_datas += 1
        try:
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(10):
                worker = Thread(target=get_tiktok, args=(i, enclosure_queue, city, keyword, s))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            print(" {}Canceled by keyboard interrupt (Ctrl-C)".format(info))
    sys.stdout.write("\033[K")
    print(separator)


if __name__ == '__main__':
    tiktok_username(identity=None, pseudo=None, city=None, picture=None)