#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re, os
import requests
import time
import traceback
from bs4 import BeautifulSoup
import json

from geopy.geocoders import Nominatim
from static.colors import info, match, p_match, no_match, error, separator
from config import FB_USERNAME, FB_PASSWORD
from output import raw_output
from modules.image_analysis.facial_recognition import face_identification

from tools.FuckFacebook.main import main as fuckfb
from tools.FuckFacebook.token_config import URL_TOKEN

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump"]

#TODO fuckfacebook

def get_marketplace(dir_name, account, s, city, keyword, facebook_id, url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:99.0) Gecko/20100101 Firefox/99.0',
        'Origin': 'https://www.facebook.com',
        'Connection': 'keep-alive',
        'Sec-Fetch-Site': 'same-origin',
    }

    data = {
        'variables': '{"canViewCustomizedProfile":true,"count":8,"isCOBMOB":false,"scale":1,"sellerId":"'+facebook_id+'"}',
        'doc_id': '4872548596176106',
    }

    response = s.post('https://www.facebook.com/api/graphql/', headers=headers, data=data)
    res = json.loads(response.text)

    article = ""
    city = ""
    group = ""

    marketplace_count = res["data"]["user"]["group_commerce_inventory"]["count"]
    if marketplace_count > 0:
        print("   \u251c Marketplace: True")
        print("     \u251c Article number: {}".format(res["data"]["user"]["group_commerce_inventory"]["count"]))
        edges = res["data"]["user"]["group_commerce_inventory"]["edges"]
        matching = False
        for e in edges:
            if e.get("node")["origin_group"] != None:
                group = "     \u251c Marketing Group: https://www.facebook.com/{} with Name: {}".format(e.get("node")["origin_group"]["id"], e.get("node")["origin_group"]["name"])
                article = "     \u251c Article Exemple: https://www.facebook.com/{}".format(e.get("node")["id"])
                city = "     \u251c Marketing City: https://www.facebook.com/{}".format(e.get("node")["location"]["reverse_geocode"]["city"])
        print(article)
        print(city)
        print(group)
        print("     \u251c Marketing UserID: https://www.facebook.com/{}".format(res["data"]["user"]["marketplace_user_profile"]["id"]))
    else:
        print("   \u251c Marketplace: None")


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


def get_facebook_info(dir_name, account, s, city, keyword, facebook_id, url):
    """
    TODO:
    if m.facebook.com dosn't work check on wwww.facebook.com:
    University/employee: <div class="tu1s4ah4">

    """
    matching = False
    url_m = "https://m.facebook.com{}".format(account)
    url_f = "https://www.facebook.com{}".format(account)
    req_info_m = s.get(url_m, verify=False, allow_redirects=False, headers={'User-agent': UserAgent().random})
    if req_info_m.status_code != 302:
        soup_info = BeautifulSoup(req_info_m.text, "html.parser")
        find_exp = soup_info.find('div', {'class': 'experience'})
        find_city = soup_info.find('h4')
        if find_exp:
            fe = find_exp.find("span")
            if city and city.lower() in fe.text.lower():
                experience = "   {}Experience: {}".format(match, fe.text)
                matching = True
            if keyword and [k.lower() for k in keyword if k.lower() in fe.text.lower()]:
                experience = "   {}Experience: {}".format(match, fe.text)
                matching = True
            else:
                experience = "   \u251c Experience: {}".format(fe.text)
        else:
            experience = "   \u251c Experience: N/A"
        if find_city:
            locator = Nominatim(user_agent="myGeocoder")
            location = locator.geocode(city)

            if city and city.lower() in find_city.text.lower():
                get_city = "   {}City: {}".format(match, find_city.text)
                matching = True
            elif "," in find_city.text:
                for fc in find_city.text.split(","):
                    if fc in location.address:
                        get_city = "   {}City: {}".format(match, find_city.text)
                        matching = True 
            else:
                get_city = "   \u251c City: {}".format(find_city.text)
        else:
            get_city = "   \u251c City: N/A"
        #TODO (city, school etc...)
    else:
        #req_info_m = s.get(url_f, verify=False, headers={'User-agent': UserAgent().random}, allow_redirects=False)
        experience = "   \u251c Experience: N/A"
        get_city = "   \u251c City: N/A"
        pass
        """
        #TODO
        req_info_f = requests.get(url_f, verify=False, headers={'User-agent': UserAgent().random})
        soup_info = BeautifulSoup(req_info_f.text, "html.parser")
        print(soup_info)
        test = soup_info.find('div', {'class': 'tu1s4ah4'})
        print(test)
        """
    if matching:
        print(" \033[32m\u251c Account seems matching: {} with id: {}\033[0m".format(url_m if not "www" in url else url_f, facebook_id))
        results = "link: https://www.facebook.com/{}\nusername: {}\nexperience: {}\ncity: {}".format(account.replace("/",""), account.replace("/",""), experience.replace("\033[32m","").replace("\033[0m","").replace("\u251c","").strip(), get_city.replace("\033[32m","").replace("\033[0m","").replace("\u251c","").strip())
        raw_output(dir_name, "facebook", results)
    else:
        print(" {}Potential account found: {} with id: {}".format(p_match, url_m if not "www" in url else url_f, facebook_id))
    print(experience)
    print(get_city)


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

def basic_search(dir_name, firstname, lastname, pseudo, city, picture, keyword, s):
    basic_names = [f"{firstname}-{lastname}", f"{lastname}-{firstname}"]
    if pseudo:
        basic_names.extend([f"{pseudo}-{firstname}", f"{pseudo}-{lastname}", f"{firstname}-{pseudo}", f"{lastname}-{pseudo}", ])
    if keyword:
        for k in keyword:
            basic_names.extend([f"{k}-{firstname}", f"{k}-{lastname}", f"{firstname}-{k}", f"{lastname}-{k}"])
    if pseudo and keyword:
        for k in keyword:
            basic_names.extend([f"{pseudo}-{k}", f"{pseudo}-{k}", f"{k}-{pseudo}", f"{k}-{pseudo}"])
    #print(basic_names)
    for bn in basic_names:
        url = "https://m.facebook.com/{}".format(bn.lower())
        req = s.get(url, verify=False, timeout=15, allow_redirects=False, headers={'User-agent': UserAgent().random})
        if req.status_code == 200:
            bn = "/" + bn
            facebook_id = get_facebook_id(bn)
            facebook_id = facebook_id if facebook_id else "N/A"
            get_facebook_info(dir_name, bn, s, city, keyword, facebook_id, url)
        elif req.status_code in [301, 302]:
            url = "https://www.facebook.com/{}".format(bn.lower())
            req = s.get(url, verify=False, timeout=15, allow_redirects=False, headers={'User-agent': UserAgent().random})
            if req.status_code == 200:
                bn = "/" + bn
                facebook_id = get_facebook_id(bn)
                facebook_id = facebook_id if facebook_id else "N/A"
                get_facebook_info(dir_name, bn, s, city, keyword, facebook_id, url)
        elif req.status_code == 403:
            pass



def facebook_search(dir_name, firstname, lastname, pseudo, city, picture, keyword, phone_n):

    s = requests.session()

    if FB_USERNAME == "" and FB_PASSWORD == "":

        print("\033[36m Unauthenticated Facebook search\033[0m")
        print(separator)

        if firstname and lastname:

            count_result = 0

            account_found = []

            basic_search(dir_name, firstname, lastname, pseudo, city, picture, keyword, s)

            url = "https://m.facebook.com/public/{}-{}".format(firstname, lastname)
            req = s.get(url, verify=False, timeout=15, allow_redirects=False, headers={'User-agent': UserAgent().random})
            if req.status_code == 302:
                url = "https://www.facebook.com/public/{}-{}".format(firstname, lastname)
                req = s.get(url, verify=False, timeout=15, headers={'User-agent': UserAgent().random})
            soup = BeautifulSoup(req.text, "html.parser")
            find_link = soup.find_all('a')
            for fl in find_link:
                try:
                    if firstname.lower() in fl.get('href') and "login" not in fl.get('href') and "cursor" not in fl.get('href') and \
                     "login" not in fl.get('href') and "next" not in fl.get('href'):
                        account = fl.get('href').split("?")[0]
                        facebook_id = get_facebook_id(account)
                        facebook_id = facebook_id if facebook_id else "N/A"
                        if account not in account_found:
                            get_facebook_info(dir_name, account, s, city, keyword, facebook_id, url)
                            get_marketplace(dir_name, account, s, city, keyword, facebook_id, url)
                            #fuckfacebook
                            account_found.append(account)
                            count_result += 1
                            if picture:
                                check_facial_reco(dir_name, account, picture)
                except:
                    #traceback.print_exc() #DEBUG
                    pass     
            if count_result > 0:
                print(" + {} account found\n".format(count_result))
            results = "Facebook returned {} accounts".format(count_result)
            raw_output(dir_name, "results_number", results)
        elif pseudo and not firstname:
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
    ## FuckFacebook
    params = {
        'f': firstname if firstname else '',
        'l': lastname if lastname else '',
    }
    print("\033[36m FuckFacebook search\033[0m")
    print(separator)
    filters = [pseudo, city, picture, keyword, phone_n]
    fuckfb(URL_TOKEN, params, filters)
    print(separator)