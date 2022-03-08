#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup
from modules.parsing import parsing_data
from modules.facial_recognition import face_identification

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def get_ig_info(pseudo, s, picture):
    url = "https://www.anonigviewer.com/profile.php?u={}".format(pseudo)
    req_ig = s.get(url, verify=False, timeout=15)
    if "Followers" in req_ig.text:
        soup = BeautifulSoup(req_ig.text, "html.parser")
        find_pic = soup.find('img', {'class': 'user-img'})
        find_name = soup.find('div', {'class': re.compile(r'user-name*')})
        find_desc = soup.find('p', {'class': re.compile(r'color-999*')})
        print(""" \033[32m\u251c {}\033[0m Instagram username seem exit with on https://www.instagram.com/{}:
    \u251c Real name: {}
    \u251c Description: {}
                """.format(pseudo, pseudo, find_name.text.replace("\n",""), find_desc.text if find_desc else "None"))
        if picture:
            img_data = requests.get(find_pic.text, verify=False).content
            with open("{}/{}.jpg".format(dir_name, account.split("/")[1]), 'wb') as handler:
                handler.write(img_data)
            fid = face_identification(picture, "{}/{}.jpg".format(dir_name, account.split("/")[1]))
            if fid:
                print("   \033[32m\u251c Facial recognition matching with the {} account !\033[0m".format(account))

def check_instagram(identity, pseudo, city, keyword, picture):
    print("\033[36m Instagram search\033[0m")
    print("\033[36m-\033[0m"*30)

    s = requests.session()

    if pseudo:
        get_ig_info(pseudo, s, picture)
    else:
        datas = parsing_data(identity, pseudo, city, keyword)
        for endpoint in datas:
            get_ig_info(endpoint, s, picture)
    print("\033[36m-\033[0m"*30)


if __name__ == '__main__':
    firstname = None 
    lastname = None
    pseudo = 'natan_ubx'
    check_instagram(firstname, lastname, pseudo)