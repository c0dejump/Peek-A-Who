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

def get_ig_obfu_infos(s, pseudo):
    url_obfu = "https://i.instagram.com/api/v1/users/lookup/"
    headers = {'User-Agent': 'Instagram 101.0.0.15.120'}
    _data = '.{"login_attempt_count":"0","directly_sign_in":"true","source":"default","q":"'+pseudo+'","ig_sig_key_version":"4"}'
    datas = {
    'ig_sig_key_version': 4,
    'signed_body':'{}'.format(_data)
    }
    get_obfu = s.post(url_obfu, headers=headers, data=datas, verify=False)
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
        print("   {}[{}] obfuscated informations not available for the moment, please wait 1min...".format(error, get_obfu.status_code))


def get_ig_details(pseudo, s, city, keyword, picture):
    url = "https://www.anonigviewer.com/profile.php?u={}".format(pseudo)
    try:
        req_ig = s.get(url, verify=False, timeout=15, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
        if "user-img" in req_ig.text:
            soup = BeautifulSoup(req_ig.text, "html.parser")
            find_pic = soup.find('img', {'class': 'user-img'})
            find_name = soup.find('div', {'class': re.compile(r'user-name*')})
            find_desc = soup.find('p', {'class': re.compile(r'color-999*')})
            real_name = find_name.text.replace("\n","")
            desc = find_desc.text if find_desc else "None"
            # filters
            city = city.lower() if city else "N/A"
            keyword = keyword.lower() if keyword else "N/A"
            if city in desc.lower() or keyword in desc.lower():
                desc = "\033[32m{}\033[0m".format(desc)
                matching = True
            else:
                matching = False
            if city in real_name.lower() or keyword in real_name.lower():
                real_name = "\033[32m{}\033[0m".format(real_name)
                matching = True
            else:
                matching = False
            if not matching:
                print(" {}\033[33m{}\033[0m Username seems exist on https://www.instagram.com/{}:".format(p_match, pseudo, pseudo))
            else:
                print(" {}\033[32m{}\033[0m Username seems to match \033[34mhttps://www.instagram.com/{}:\033[0m".format(match, pseudo, pseudo))
            print("   \u251c Real name: {}".format(real_name))
            print("   \u251c Description: {}".format(desc))
            try:
                get_ig_obfu_infos(s, pseudo)
            except:
                traceback.print_exc()
            #time.sleep(1)
            if picture:
                img_data = requests.get(find_pic.text, verify=False).content
                with open("{}/{}.jpg".format(dir_name, account.split("/")[1]), 'wb') as handler:
                    handler.write(img_data)
                fid = face_identification(picture, "{}/{}.jpg".format(dir_name, account.split("/")[1]))
                if fid:
                    print("     \033[32m\u251c Facial recognition matching with the {} account !\033[0m".format(account))
    except:
        #traceback.print_exc()
        pass


def get_ig_pseudo(pseudo, s, city, keyword, picture):
    get_ig_details(pseudo, s, city, keyword, picture)

def get_ig_info(i, q, s, city, keyword, picture):
    global bar
    bar = 0

    global matching
    matching = False
    for d in range(len_datas):
        pseudo = q.get()
        get_ig_details(pseudo, s, city, keyword, picture)
        bar += 1
        sys.stdout.write(" {}/{} | https://www.instagram.com/{} \r".format(bar, len_datas, pseudo))
        q.task_done()



def instagram_search(identity, pseudo, city, keyword, picture, birth_year):
    print("\033[36m Instagram search\033[0m")
    print(separator)

    global len_datas
    len_datas = 0

    s = requests.session()

    if pseudo and not identity:
        get_ig_pseudo(pseudo, s, city, keyword, picture)
    else:
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for n in datas:
            len_datas += 1
        try:
            #print(emails_for_verification)
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(2):
                worker = Thread(target=get_ig_info, args=(i, enclosure_queue, s, city, keyword, picture))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            print(" {}Canceled by keyboard interrupt (Ctrl-C)".format(info))
            sys.exit()
        except Exception:
            traceback.print_exc()
            #pass
    sys.stdout.write("\033[K") 
    print(separator)


if __name__ == '__main__':
    firstname = None 
    lastname = None
    pseudo = 'natan_ubx'
    check_instagram(firstname, lastname, pseudo)