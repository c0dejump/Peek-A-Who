#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup
from config import FB_USERNAME, FB_PASSWORD
from output import raw_output
from modules.image_analysis.facial_recognition import face_identification

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

#TODO fuckfacebook

def check_facial_reco(dir_name, account, picture):
    get_profile = requests.get("https://www.facebook.com{}".format(account), verify=False)
    soup = BeautifulSoup(get_profile.text, "html.parser")
    #print(soup)
    profile_image = soup.find('meta', {'property': 'og:image'})
    link_image = profile_image.get("content")
    img_data = requests.get(link_image, verify=False).content
    with open("{}/{}.jpg".format(dir_name, account.split("/")[1]), 'wb') as handler:
        handler.write(img_data)
    fid = face_identification(picture, "{}/{}.jpg".format(dir_name, account.split("/")[1]))
    if fid:
        print("     \033[32m\u251c Facial recognition matching with the {} account !\033[0m".format(account))


def get_facebook_id(account):
    facebook_id_url = "https://lookup-id.com/"
    account = "https://www.facebook.com/{}".format(account)
    datas = {
            "fburl": "{}".format(account),
            "check": "Lookup"
            }
    get_id = requests.post(facebook_id_url, data=datas, verify=False)
    soup = BeautifulSoup(get_id.text, "html.parser")
    find_id = soup.find('span', {'id': 'code'})
    return(find_id.text)


def facebook_search(dir_name, firstname, lastname, pseudo, city, picture):

    if FB_USERNAME == "" and FB_PASSWORD == "":

        print("\033[36m Unauthentification Facebook search\033[0m")
        print("\033[36m-\033[0m"*30)

        if firstname and lastname:
            count_result = 0

            account_found = []

            url = "https://m.facebook.com/public/{}-{}".format(firstname, lastname)
            req = requests.get(url, verify=False, timeout=15)
            soup = BeautifulSoup(req.text, "html.parser")
            find_link = soup.find_all('a')
            for s in find_link:
                try:
                    if firstname.lower() in s.get('href') and "login" not in s.get('href') and "cursor" not in s.get('href') and \
                     "login" not in s.get('href') and "next" not in s.get('href'):
                        account = s.get('href')
                        facebook_id = get_facebook_id(account)
                        if account not in account_found:
                            print(" \u251c Potential account found: {} with id: {}".format(account, facebook_id))
                            #fuckfacebook
                            account_found.append(account)
                            count_result += 1
                            if picture:
                                check_facial_reco(dir_name, account, picture)
                except:
                    pass
                    """
                    #TODO
                    get city:
                    find_city = soup.find("div", class_="_59k _2rgt _1j-f _2rgt") => quelque chose comme ça mais ne fonctionne pas :/
                    <div class="_59k _2rgt _1j-f _2rgt" style="font-size: 14px;font-weight: 400;text-align: left;color: #050505;display: -webkit-box;-webkit-line-clamp: 2;-webkit-box-orient: vertical;overflow: hidden;text-overflow: ellipsis" id="u_0_60_bB" data-nt="FB:TEXT4">Habite à Rotterdam</div>
                    elif account not in account_found and city:
                        if find_city.text == city:
                            print(" [+] Potential account found: {} with id: {} and the same city: {}".format(account, facebook_id, find_city))
                    """
            if count_result > 0:
                print(" + {} account found\n".format(count_result))
            else:
                print(" No account found\n".format(count_result))
        else:
            url = "https://www.facebook.com/{}".format(pseudo)
            req = requests.get(url, verify=False, timeout=15)
            if req.status_code == 200:
                try:
                    facebook_id = get_facebook_id(pseudo)
                    print(" [+] Potential account found: https://m.facebook.com/{} with id: {}\n".format(pseudo, facebook_id))
                    if picture:
                        account = "/{}".format(pseudo)
                        check_facial_reco(dir_name, account, picture)
                except:
                    print(" [-] No account found with this pseudo\n")
            else:
                print(" [-] No account found with this pseudo\n")
        print("\033[36m-\033[0m"*30)
    else:
        print("\033[36m Facebook search with account #TODO\033[0m")
