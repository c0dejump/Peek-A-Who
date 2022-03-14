#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re, os
import requests
import time
import traceback
from bs4 import BeautifulSoup

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


def get_ig_info(i, q, s, city, keyword, picture):
    global bar
    bar = 0

    matching = False
    for d in range(len_datas):
        pseudo = q.get() if i != None else q
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
                city = city.lower() if city else "n/a"
                keyword = keyword.lower() if keyword else "n/a"

                if city in desc.lower() or keyword in desc.lower():
                    desc = "\033[32m{}\033[0m".format(desc)
                    matching = True
                if city in real_name.lower() or keyword in real_name.lower():
                    real_name = "\033[32m{}\033[0m".format(real_name)
                    matching = True

                if not matching:
                    print(" {}\033[33m{}\033[0m Instagram seem exist on https://www.instagram.com/{}:".format(p_match, pseudo, pseudo))
                else:
                    print(" {}\033[32m{}\033[0m Instagram seem exist on \033[34mhttps://www.instagram.com/{}:\033[0m".format(match, pseudo, pseudo))
                print("   \u251c Real name: {}".format(real_name))
                print("   \u251c Description: {}".format(desc))

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
        bar += 1
        sys.stdout.write(" {}/{} | https://www.instagram.com/{} \r".format(bar, len_datas, pseudo))
        q.task_done()



def check_instagram(identity, pseudo, city, keyword, picture):
    print("\033[36m Instagram search\033[0m")
    print(separator)

    global len_datas
    len_datas = 0

    s = requests.session()

    if pseudo:
        i = None
        get_ig_info(i, pseudo, s, city, keyword, picture)
        len_datas = 1
    else:
        datas = parsing_data(identity, pseudo, city, keyword)
        for n in datas:
            len_datas += 1
        try:
            #print(emails_for_verification)
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(10):
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