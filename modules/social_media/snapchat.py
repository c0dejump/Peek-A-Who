#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import argparse
import requests
import time
import traceback
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator
from output import raw_output
from modules.parsing import parsing_data

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

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

#https://www.snapchat.com/add/natan-f
#https://feelinsonice.appspot.com/web/deeplink/snapcode?username=natan-f&size=400&type=SVG

def get_snapchat(i, q, s):
    global bar
    bar = 0 

    global results_found
    results_found = 0

    for d in range(len_datas):
        endpoint = q.get() if type(q) != str() else q
        url_snapchat = "https://www.snapchat.com/add/{}".format(endpoint)
        req_snapchat = s.get(url_snapchat, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
        if req_snapchat.status_code not in [404, 403, 401]:
            soup = BeautifulSoup(req_snapchat.text, "html.parser")
            try:
                find_name = soup.find('span', {'class': re.compile(r'UserDetailsCard_title*')})
                if find_name.text:
                    print(" {}\033[33m{}\033[0m Username seems exist with real name {} on https://www.snapchat.com/add/{}".format(p_match, endpoint, "\033[33m{}\033[0m".format(find_name.text), endpoint))
                    results_found += 1
                else:
                    pass
            except AttributeError:
                pass
                #print(" \033[32m\u251c {}\033[0m snapchat seem exit with real name \033[31mNone\033[0m".format(endpoint))
        bar += 1
        q.task_done()
        sys.stdout.write(" {}/{} | https://www.snapchat.com/add/{} \r".format(bar, len_datas, endpoint))



def snapchat_search(dir_name, identity, pseudo, city, keyword, birth_year):

    print("\033[36m Snapchat search\033[0m")
    print(separator)
    
    s = requests.session()

    global len_datas
    len_datas = 0

    if pseudo and not identity:
        i = None
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for d in datas:
            get_snapchat(i, d, s)
    else:
        datas = parsing_data(identity, pseudo, city, keyword, birth_year)
        for n in datas:
            len_datas += 1
        try:
            for endpoint in datas:
                enclosure_queue.put(endpoint)
            for i in range(10):
                worker = Thread(target=get_snapchat, args=(i, enclosure_queue, s))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            print(" {}Canceled by keyboard interrupt (Ctrl-C)".format(info))
    sys.stdout.write("\033[K")
    results = "Snapchat return {} accounts".format(results_found)
    raw_output(dir_name, "results_number", results)
    print(separator)



if __name__ == '__main__':
    #arguments
    parser = argparse.ArgumentParser(add_help = True)
    parser = argparse.ArgumentParser(description='\033[32mcontact: https://twitter.com/c0dejump\033[0m')

    group = parser.add_argument_group('\033[34m> General\033[0m')
    group.add_argument("-i", help="Identity, exemple: -i john_doe", dest='identity', required=False)
    group.add_argument("-p", help="Pseudo, exemple: -p codejump", dest='pseudo', required=False)

    group = parser.add_argument_group('\033[34m> Assistance\033[0m')
    group.add_argument("-c", help="City adress, exemple: -c Paris", dest='city', required=False)
    group.add_argument("-k", help="Keyword, the script will be based on this, exemple: -k security; -k pro", dest='keyword', required=False)

    results = parser.parse_args()

    if len(sys.argv) < 2:
        print("\nOption missing\n")
        parser.print_help()
        sys.exit()

    identity = results.identity
    pseudo = results.pseudo
    city = results.city
    keyword = results.keyword

    parse_snapchat_username(identity, pseudo, city, keyword)