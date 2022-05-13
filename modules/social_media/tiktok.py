#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
import json
from bs4 import BeautifulSoup
import time
from progress.spinner import Spinner

from static.colors import info, match, p_match, no_match, error, separator
from output import raw_output
from modules.parsing import parsing_data
from modules.image_analysis.facial_recognition import face_identification

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump", "Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/30.0.1599.17 Safari/537.36"]

#Threading
import threading
from threading import Thread
try:
    from Queue import Queue
except:
    import queue as Queue

try:
    enclosure_queue = Queue()
except:
    enclosure_queue = Queue.Queue()

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

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


def get_tiktok(i, q, city, keyword, s, dir_name):
    global bar
    bar = 0 

    global results_found
    results_found = 0

    ua = UserAgent().random

    change_ua = 0

    while not q.empty():
        endpoint = q.get() if type(q) != str() else q
        url_tiktok = "https://www.tiktok.com/@{}".format(endpoint)

        headers = {
            'User-agent': ua,
            'X-Forwarded': '95.101.183.80, localhost',
            'Connection': 'keep-alive',
            'Host': 'www.tiktok.com'
        }

        change_ua += 1

        if change_ua == 20:
            ua = UserAgent().random
            change_ua = 0

        try:
            req_tiktok = s.get(url_tiktok, verify=False, headers=headers, timeout=13)

            matching = False

            if req_tiktok.status_code not in [404, 403, 401] and len(req_tiktok.content) > 1 and not "verifyConfig" in req_tiktok.text:
                results_found += 1

                soup = BeautifulSoup(req_tiktok.text, "html.parser")
                find_name = soup.find('h1', {'data-e2e': 'user-subtitle'})
                real_name = find_name.text if find_name else "None"
                description = soup.find('h2', {'data-e2e': 'user-bio'})
                site = soup.find('span', {'class': re.compile(r'tiktok-847r2g-SpanLink*')})
                desc = description.text.replace("\n", " ") if description else "N/A"

                if city:
                    if city.lower() in desc.lower():
                        desc = "\033[32m{}\033[0m".format(desc)
                        matching = True
                if keyword:
                    if [k.lower() for k in keyword if k.lower() in desc.lower()]:
                        desc = "\033[32m{}\033[0m".format(desc)
                        matching = True
                if not matching:
                    print(" {}\033[33m{}\033[0m TikTok seem exist on https://www.tiktok.com/@{} :".format(p_match, endpoint, endpoint))
                else:
                    print(" {}\033[32m{}\033[0m TikTok seem matching with: https://www.tiktok.com/@{} :".format(match, endpoint, endpoint))
                    results = "link: https://www.tiktok.com/@{}\nusername: {}\nreal_name: {}\ndesc: {}".format(endpoint, endpoint, find_name.text.replace("\033[32m","").replace("\033[0m",""), desc.replace("\033[32m","").replace("\033[0m",""))
                    raw_output(dir_name, "tiktok", results)
                print("   \u251c Real name: {}".format(real_name))
                print("   \u251c Description: {}".format(desc)) if "No bio yet" not in desc else None
                print("   \u251c Site: {}".format(site.text)) if site else None
            elif req_tiktok.status_code == 403:
                spinner = Spinner(" {}Tiktok returned {} satus code, please wait... ".format(error, req_tiktok.status_code))
                ua = UserAgent().random
                i = 30
                while i != 0:
                    i -= 1
                    spinner.next()
                    time.sleep(0.9)
                i = 30
            q.task_done()
            bar += 1
            sys.stdout.write(" {}/{} | https://www.tiktok.com/@{} \r".format(bar, len_datas, endpoint))
        except KeyboardInterrupt:
            q.task_done()
            break
        except:
            ua = UserAgent().random
            pass


def tiktok_search(dir_name, identity, pseudo, city, keyword, picture, birth_year):

    print("\033[36m TikTok search\033[0m")
    print(separator)
    
    s = requests.session()

    global len_datas
    len_datas = 0

    if pseudo and not identity:
        i = None
        get_tiktok(i, pseudo, city, keyword, s, dir_name)
    else:
        req_verif = requests.get("https://www.tiktok.com/", verify=False, timeout=15, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:99.0) Gecko/20100101 Firefox/99.0'})
        if req_verif.status_code != 403:
            datas = parsing_data(identity, pseudo, city, keyword, birth_year)
            for n in datas:
                len_datas += 1
            try:
                for endpoint in datas:
                    enclosure_queue.put(endpoint)
                for i in range(10):
                    worker = Thread(target=get_tiktok, args=(i, enclosure_queue, city, keyword, s, dir_name))
                    worker.setDaemon(True)
                    worker.start()
                enclosure_queue.join()
            except KeyboardInterrupt:
                results_found = 0
                enclosure_queue.queue.clear() #To clear the queue
                print(" {}Canceled by keyboard interrupt (Ctrl-C)  ".format(info))
                sys.stdout.write("\033[K")
            except Timeout:
                print(" {}Timeout with {} please check it manually".format(error, endpoint))
            except Exception:
                pass
        else:
            print(" {} Tiktok returned {} satus code, please verify if it's blocked...".format(error, req_verif.status_code))
            results_found = 0
    results = "Tiktok returned {} accounts".format(results_found)
    raw_output(dir_name, "results_number", results)
    print(separator)


if __name__ == '__main__':
    tiktok_username(identity=None, pseudo=None, city=None, picture=None)