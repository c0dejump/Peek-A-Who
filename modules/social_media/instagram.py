#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re, os
import requests
import time
import traceback
import json
from bs4 import BeautifulSoup
import urllib.parse

from static.colors import info, match, p_match, no_match, error, separator
from output import raw_output
from modules.parsing import parsing_data
from modules.image_analysis.facial_recognition import face_identification

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump"]

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

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def get_ig_obfu_infos(s, endpoint):
    url_obfu = "https://i.instagram.com/api/v1/users/lookup/"
    headers = {'User-Agent': 'Instagram 101.0.0.15.120'}
    _data = '.{"login_attempt_count":"0","directly_sign_in":"true","source":"default","q":"'+endpoint+'","ig_sig_key_version":"4"}'
    datas = {
    'ig_sig_key_version': 4,
    'signed_body':'{}'.format(_data)
    }
    get_obfu = s.post(url_obfu, headers=headers, data=datas, verify=False, timeout=15)
    if get_obfu.status_code == 200:
        res = json.loads(get_obfu.text)
        #print(res)
        try:
            obfu_email = res["obfuscated_email"]
        except:
            obfu_email = "N/A"
        try:
            obfu_phone = res["obfuscated_phone"]
            #https://www.indicatifs-pays.net/262
        except:
            obfu_phone = "N/A"
        print("   \u251c obfuscated email: {}".format(obfu_email))
        print("   \u251c obfuscated phone: {}".format(obfu_phone))
        return True
    elif get_obfu.status_code == 429:
        print("   {}[{}] obfuscated informations not available for the moment".format(error, get_obfu.status_code))


class parse_ig:

    #TODO: if profile is public check on InstaLocTrack: https://github.com/bernsteining/instaloctrack

    def get_ig_details(self, endpoint, s, city, keyword, pseudo, picture, dir_name):
        endpoint = endpoint if endpoint else pseudo
        url = "https://privatephotoviewer.com/usr/{}".format(endpoint)
        matching = False
        req_ig = s.get(url, verify=False, timeout=10, headers={'User-agent': UserAgent().random})
        if req_ig.status_code == 200 and "error" not in req_ig.text:
            soup = BeautifulSoup(req_ig.text, "html.parser")
            find_pic = soup.find('img', {'style': ''})
            find_pic = find_pic.get("src")
            find_name = soup.find('h1', {'id': 'userfullname'})
            find_desc = soup.find('p', {'id': 'biofull'})
            real_name = find_name.text.strip() if find_name else "None"
            desc = find_desc.text.strip()  if find_desc else "None"
            # filters
            city = city.lower() if city else "N/A"
            keyword = keyword.lower() if keyword else "N/A"
            pseudo = pseudo.lower() if pseudo else "N/A"
            if city in desc.lower() or keyword in desc.lower():
                desc = "\033[32m{}\033[0m".format(desc)
                matching = True
            if city in real_name.lower() or keyword in real_name.lower():
                real_name = "\033[32m{}\033[0m".format(real_name)
                matching = True
            if pseudo in real_name.lower():
                real_name = "\033[32m{}\033[0m".format(real_name)
                matching = True
            if pseudo in desc.lower():
                desc = "\033[32m{}\033[0m".format(desc)
                #print(desc)
                #desc = " ".join(desc)
                matching = True
            if not matching:
                print(" {}\033[33m{}\033[0m Username seems exist on https://www.instagram.com/{} :".format(p_match, endpoint, endpoint))
            else:
                print(" {}\033[32m{}\033[0m Username seems matching \033[34mhttps://www.instagram.com/{} :\033[0m".format(match, endpoint, endpoint))
            print("   \u251c Real name: {}".format(real_name))
            print("   \u251c Description: {}".format(" ".join(desc.splitlines())))
            if matching:
                results = "username: {}\nreal_name: {}\ndesc: {}".format(endpoint, real_name.replace("\033[32m","").replace("\033[0m",""), " ".join(desc.splitlines()).replace("\033[32m","").replace("\033[0m",""))
                raw_output(dir_name, "instagram", results)
            try:
                get_ig_obfu_infos(s, endpoint)
            except:
                #pass
                traceback.print_exc() #DEBUG
            #time.sleep(1)
            if picture:
                try:
                    img_data = requests.get(find_pic, verify=False).content
                    with open("{}/{}.jpg".format(dir_name, pseudo), 'wb') as handler:
                        handler.write(img_data)
                except:
                    pass
                    #traceback.print_exc() #DEBUG
                fid = face_identification(picture, "{}/{}.jpg".format(dir_name, pseudo))
                if fid:
                    print("   \033[32m\u251c Facial recognition matching with the https://www.instagram.com/{} account !\033[0m".format(pseudo))


    def get_ig_pseudo(self, endpoint, s, city, keyword, pseudo, picture, dir_name):
        self.get_ig_details(endpoint, s, city, keyword, pseudo, picture, dir_name)


    def get_ig_info(self, i, q, s, city, keyword, pseudo, picture, dir_name):
        global bar
        bar = 0 

        while not q.empty():
            endpoint = q.get()
            try:
                #print(threading.active_count())
                self.get_ig_details(endpoint, s, city, keyword, pseudo, picture, dir_name)
                bar += 1
                sys.stdout.write(" {}/{} | https://www.instagram.com/{} \r".format(bar, len_datas, endpoint))
            except Exception:
                #traceback.print_exc()
                pass
            q.task_done()
            


def deleted_image(dir_name):
    for f in os.listdir(dir_name):
        os.remove(os.path.join(dir_name, f))


def instagram_search(dir_name, identity, pseudo, city, keyword, picture, birth_year):
    print("\033[36m Instagram search\033[0m")
    print(separator)

    global len_datas
    len_datas = 0

    s = requests.session()

    parsing_ig = parse_ig()

    if pseudo and not identity:
        endpoint = None
        parsing_ig.get_ig_pseudo(endpoint, s, city, keyword, pseudo, picture, dir_name)
    else:
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for n in datas:
            len_datas += 1
        try:
            #print(emails_for_verification)
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(5):
                #2 threads for obfu information, else 429 response srry...
                worker = Thread(target=parsing_ig.get_ig_info, args=(i, enclosure_queue, s, city, keyword, pseudo, picture, dir_name))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            print(" {}Canceled by keyboard interrupt (Ctrl-C)".format(info))
            enclosure_queue.queue.clear()
            time.sleep(1)
            #sys.exit()
        except Exception:
            #traceback.print_exc()
            pass
    sys.stdout.write("\033[K")
    #deleted_image(dir_name)
    print(separator)


if __name__ == '__main__':
    firstname = None 
    lastname = None
    pseudo = 'natan_ubx'
    check_instagram(firstname, lastname, pseudo)