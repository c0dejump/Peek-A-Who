#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator
from config import FB_USERNAME, FB_PASSWORD
from output import raw_output
from modules.image_analysis.facial_recognition import face_identification

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump"]

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
        print("   \033[32m\u251c Facial recognition matching with the {} account !\033[0m".format(account))

def get_facebook_info(account, s, city, keyword):
    """
    TODO:
    if m.facebook.com dosn't work check on wwww.facebook.com:
    University/employee: <div class="tu1s4ah4">

    """
    url_m = "https://m.facebook.com/{}".format(account)
    url_f = "https://www.facebook.com/{}".format(account)
    req_info_m = s.get(url_m, verify=False, headers={'User-agent': UserAgent().random}, allow_redirects=False)
    if req_info_m.status_code != 302:
        soup_info = BeautifulSoup(req_info_m.text, "html.parser")
        find_exp = soup_info.find('div', {'class': 'experience'})
        find_city = soup_info.find('h4')
        if find_exp:
            fe = find_exp.find("span")
            if city.lower() in fe.text.lower() or keyword.lower() in fe.text.lower():
                print("   {}Experience: {}".format(match, fe.text))
            else:
                print("   \u251c Experience: {}".format(fe.text))
        if find_city:
            if city.lower() in find_city.text.lower() or keyword.lower() in find_city.text.lower():
                print("   {}City: {}".format(match, find_city.text))
            else:
                print("   \u251c City: {}".format(find_city.text))
        #TODO (city, school etc...)
    else:
        pass
        """
        #TODO
        req_info_f = requests.get(url_f, verify=False, headers={'User-agent': UserAgent().random})
        soup_info = BeautifulSoup(req_info_f.text, "html.parser")
        print(soup_info)
        test = soup_info.find('div', {'class': 'tu1s4ah4'})
        print(test)
        """


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
    if find_id:
        return(find_id.text)


def facebook_search(dir_name, firstname, lastname, pseudo, city, picture, keyword):

    s = requests.session()

    if FB_USERNAME == "" and FB_PASSWORD == "":

        print("\033[36m Unauthenticated Facebook search\033[0m")
        print(separator)

        if firstname and lastname:
            count_result = 0

            account_found = []

            url = "https://m.facebook.com/public/{}-{}".format(firstname, lastname)
            req = s.get(url, verify=False, timeout=15)
            soup = BeautifulSoup(req.text, "html.parser")
            find_link = soup.find_all('a')
            for fl in find_link:
                try:
                    if firstname.lower() in fl.get('href') and "login" not in fl.get('href') and "cursor" not in fl.get('href') and \
                     "login" not in fl.get('href') and "next" not in fl.get('href'):
                        account = fl.get('href')
                        facebook_id = get_facebook_id(account)
                        facebook_id = facebook_id if facebook_id else "N/A"
                        if account not in account_found:
                            print(" {}Potential account found: https://m.facebook.com{} with id: {}".format(p_match, account, facebook_id))
                            get_facebook_info(account, s, city, keyword)
                            #fuckfacebook
                            account_found.append(account)
                            count_result += 1
                            if picture:
                                check_facial_reco(dir_name, account, picture)
                except:
                    traceback.print_exc() #DEBUG
                    pass
            if count_result > 0:
                print(" + {} account found\n".format(count_result))
            else:
                print(" {}No account found\n".format(no_match, count_result))
        else:
            url = "https://www.facebook.com/{}".format(pseudo)
            req = requests.get(url, verify=False, timeout=15)
            if req.status_code == 200:
                try:
                    facebook_id = get_facebook_id(pseudo)
                    print(" {}Potential account found: https://www.facebook.com/{} with id: {}\n".format(p_match, pseudo, facebook_id))
                    if picture:
                        account = "/{}".format(pseudo)
                        check_facial_reco(dir_name, account, picture)
                except:
                    #traceback.print_exc() #DEBUG
                    print(" {}No account found with this pseudo\n".format(no_match))
            else:
                print(" {}No account found with this pseudo\n".format(no_match))
        print(separator)
    else:
        print("\033[36m Facebook search with account #TODO\033[0m")
