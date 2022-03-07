#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import argparse
import requests
import time
import traceback
from bs4 import BeautifulSoup

from modules.parsing import parsing_data


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

#https://www.snapchat.com/add/natan-f
#https://feelinsonice.appspot.com/web/deeplink/snapcode?username=natan-f&size=400&type=SVG

def get_snapchat(endpoint, s):
    url_snapchat = "https://www.snapchat.com/add/{}".format(endpoint)
    req_snapchat = s.get(url_snapchat, verify=False)
    if req_snapchat.status_code not in [404, 403, 401]:
        soup = BeautifulSoup(req_snapchat.text, "html.parser")
        try:
            find_name = soup.find('span', {'class': re.compile(r'UserDetailsCard_title*')})
            print(" \033[32m\u251c {}\033[0m snapchat username seem exit with real name {} on https://www.snapchat.com/add/{}".format(endpoint, "\033[32m{}\033[0m".format(find_name.text if find_name.text else "\033[31mNone\033[0m"), endpoint))
        except AttributeError:
            print(" \033[32m\u251c {}\033[0m snapchat seem exit with real name \033[31mNone\033[0m".format(endpoint))


def parse_snapchat_username(identity, pseudo, city, keyword):

    print("\033[36m Snapchat search\033[0m")
    print("\033[36m-\033[0m"*30)
    
    s = requests.session()

    endpoints = []

    if pseudo and not identity and not city and not keyword:
        get_snapchat(pseudo, s)
    else:
        datas = parsing_data(identity, pseudo, city, keyword)
        for endpoint in datas:
            get_snapchat(endpoint, s)
    print("\033[36m-\033[0m"*30)



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