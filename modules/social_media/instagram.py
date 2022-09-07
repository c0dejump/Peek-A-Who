#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re, os
import requests
from requests.exceptions import Timeout
import time
import traceback
import json
from bs4 import BeautifulSoup
import urllib.parse

from static.colors import info, match, p_match, no_match, error, separator
from output import raw_output
from modules.parsing import parsing_data
from modules.image_analysis.facial_recognition import face_identification
#from exif import Image

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


def get_ig_obfu_infos(s, endpoint, phone_n):

    url_obfu = "https://i.instagram.com/api/v1/users/lookup/"
    headers = {'User-Agent': 'Instagram 101.0.0.15.120'}
    _data = '.{"login_attempt_count":"0","directly_sign_in":"true","source":"default","q":"'+endpoint+'","ig_sig_key_version":"4"}'
    datas = {
    'ig_sig_key_version': 4,
    'signed_body':'{}'.format(_data)
    }
    get_obfu = s.post(url_obfu, headers=headers, data=datas, verify=False, timeout=20)
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
        sys.stdout.write("\033[K")
        print("   \u251c obfuscated phone: {}".format(obfu_phone))
        sys.stdout.write("\033[K")
        if obfu_phone and phone_n and phone_n[1:3] == obfu_phone[1:3] and phone_n[-2:] == obfu_phone[-2:]:
            print("   {}The 1st and last digit of the phone number seem to match: \033[32m+{}\033[0m * ** ** ** \033[32m{}\033[0m".format(match, obfu_phone[1:3], obfu_phone[-2:]))
        sys.stdout.write("\033[K")
        return True
    elif get_obfu.status_code == 429:
        print("   {}[{}] obfuscated informations not available for the moment".format(error, get_obfu.status_code))


class parse_ig:

    #TODO: if profile is public check on InstaLocTrack: https://github.com/bernsteining/instaloctrack

    def get_ig_details(self, endpoint, s, city, keyword, pseudo, picture, dir_name, phone_n):

        endpoint = endpoint if endpoint else pseudo
        url = "https://privatephotoviewer.com/usr/{}".format(endpoint)
        matching = False
        req_ig = s.get(url, verify=False, timeout=20, headers={'User-agent': UserAgent().random})
        #print(req_ig.text)
        soup = BeautifulSoup(req_ig.text, "html.parser")
        following = soup.find('span', {'class': 'profile-following'})
        if req_ig.status_code == 200 and "error" not in req_ig.text and following != " ":
            find_pic = soup.find('img', {'style': ''})
            find_pic = find_pic.get("src")
            find_name = soup.find('h1', {'class': 'profile-name'})
            find_desc = soup.find('span', {'class': 'profile-desc'})
            real_name = find_name.text.strip() if find_name else "None"
            desc = find_desc.text.strip() if find_desc else "None"
            # filters
            city = city.lower() if city else "N/A"
            keyword = [k.lower() for k in keyword] if keyword else "N/A"
            pseudo = pseudo.lower() if pseudo else "N/A"
            if city in desc.lower() or [k for k in keyword if keyword != "N/A" and k in desc.lower()]:
                desc = "\033[32m{}\033[0m".format(desc)
                matching = True
            if city in real_name.lower() or [k for k in keyword if keyword != "N/A" and k in real_name.lower()]:
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
            if real_name != "N/A":
                print("   \u251c Real name: {}".format(real_name))
            if desc != "N/A":
                print("   \u251c Description: {}".format(" ".join(desc.splitlines())))
            if matching:
                results = "link: https://www.instagram.com/{}\nusername: {}\nreal_name: {}\ndesc: {}".format(endpoint, endpoint, real_name.replace("\033[32m","").replace("\033[0m",""), " ".join(desc.splitlines()).replace("\033[32m","").replace("\033[0m",""))
                raw_output(dir_name, "instagram", results)
            try:
                get_ig_obfu_infos(s, endpoint, phone_n)
                time.sleep(1)
            except:
                pass
                #traceback.print_exc() #DEBUG
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
            """
            https://pypi.org/project/exif/
            with open("{}/{}.jpg", 'rb') as image_file:
                my_image = Image(image_file)
            if my_image.has_exif:
                print("   \u251c Exif: True") Really need ?
            """
            return True


    def get_ig_pseudo(self, endpoint, s, city, keyword, pseudo, picture, dir_name, phone_n):
        global results_found
        results_found = 0

        gid = self.get_ig_details(endpoint, s, city, keyword, pseudo, picture, dir_name, phone_n)
        if gid:
            results_found += 1


    def get_ig_info(self, i, q, s, city, keyword, pseudo, picture, dir_name, phone_n):
        global bar
        bar = 0

        global results_found
        results_found = 0

        while not q.empty():
            endpoint = q.get()
            try:
                #print(threading.active_count())
                gid = self.get_ig_details(endpoint, s, city, keyword, pseudo, picture, dir_name, phone_n)
                if gid:
                    results_found += 1
                bar += 1
                sys.stdout.write(" {}/{} | {} \r".format(bar, len_datas, endpoint))
            except Timeout:
                pass
                #print(" {}Timeout with {} please check it manually".format(error, endpoint))
            except Exception:
                #traceback.print_exc()
                pass
            q.task_done()
            


def deleted_image(dir_name):
    for f in os.listdir(dir_name):
        os.remove(os.path.join(dir_name, f))


def instagram_search(dir_name, identity, pseudo, city, keyword, picture, birth_year, phone_n):
    print("\033[36m Instagram search\033[0m")
    print(separator)
    sys.stdout.write("\033[K")

    global len_datas
    len_datas = 0

    s = requests.session()

    parsing_ig = parse_ig()

    if pseudo and not identity:
        endpoint = None
        parsing_ig.get_ig_pseudo(endpoint, s, city, keyword, pseudo, picture, dir_name, phone_n)
    else:
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for n in datas:
            len_datas += 1
        try:
            #print(emails_for_verification)
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(5):
                #5 threads for obfuscation informations and appli used
                worker = Thread(target=parsing_ig.get_ig_info, args=(i, enclosure_queue, s, city, keyword, pseudo, picture, dir_name, phone_n))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            enclosure_queue.queue.clear()
            print(" {}Canceled by keyboard interrupt (Ctrl-C)  ".format(info))
            sys.stdout.write("\033[K")
            #sys.exit()
        except Exception:
            #traceback.print_exc()
            pass
    #deleted_image(dir_name)
    results = "Instagram returned {} accounts".format(results_found)
    raw_output(dir_name, "results_number", results)
    print(separator)


if __name__ == '__main__':
    firstname = None 
    lastname = None
    pseudo = 'natan_ubx'
    check_instagram(firstname, lastname, pseudo)