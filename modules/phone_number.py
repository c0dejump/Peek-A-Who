#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests

from static.colors import info, match, p_match, no_match, error, separator
from bs4 import BeautifulSoup

def skypli(phone_number, dir_name):
    print("Searching Skype users")
    print(separator)
    
    url = "https://www.skypli.com/search/{}".format(phone_number) 
    print(url)
    page = requests.get(url, verify=False)
    soup = BeautifulSoup(page.content, "html.parser")
    results = soup.find(class_="search-results__title")
    if page.status_code != 500:
        if results.text.strip() != "0 results for":
            print(results.text.strip() + ". Autocompleting list of e-mail usernames...")
            results = soup.find_all(class_="search-results__block-info-username")
            for n in results:
                test_text = n.text.strip()
                if test_text.find(".cid.") == -1:
                    if test_text.find("live:") != -1:
                        if len(test_text) != 21:
                            structure.append(test_text[5:])
                            if test_text[-1].isdigit() == True and test_text[-2] == "_":
                                structure.append(test_text[5:-2])
                            if test_text[-1].isdigit() == True and test_text[-2].isdigit() == True and test_text[-3] == "_":
                                structure.append(test_text[5:-3])
                    else:
                        structure.append(test_text)
        else:
            print("No results on Skype for this name")



def phone_number_actions(phone_n, dir_name):
    pn_ignorant = phone_n.replace("+", "")
    os.system("ignorant {} {}".format(pn_ignorant[0:2], pn_ignorant.lstrip(pn_ignorant[0:2])))
    #fuckfacebook
    skypli(pn_ignorant, dir_name)
