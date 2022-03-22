#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def get_informations(identity, soup, t, city, keyword):
        block = soup.find('div', {'id': "{}".format(t)})
        numbers = block.find('span', {'class': re.compile(r'nombre*')})
        name = block.find('p', {'class': "deno"})
        details = block.find_all('p', {'class': "txt"})

        if "societe" in t:
            result = "{} Society found:".format(numbers.text) 
        elif "dir"in t:
            result = "{} Director found:".format(numbers.text)
        elif "doc" in t:
            result = "{} Documents found:".format(numbers.text)
        print(" {}{}".format(p_match, result.strip().replace("  ", "").replace("\n", "")))
        print("   \u251c {}".format(name.text.strip().replace("  ", "").replace("\n", "")))
        for d in details:
            print("   \u251c {}".format(d.text.strip().replace("  ", "").replace("\n", "").replace("\t", "")))
        if "doc" in t:
            print("   {} See all documents: https://www.societe.com/cgi-bin/liste-doc?champs={}&ori=doc".format(info, identity))


def search_societe(dir_name, identity, city, keyword):
    identity = identity.replace("_","+")
    print("\033[36m Society search\033[0m")
    print(separator)
    url = "https://www.societe.com/cgi-bin/search?champs={}".format(identity)
    req = requests.get(url, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
    if "Aucun résultat" in req.text:
        print(" {} Not found".format(no_match, identity))
    else:
        tags = ["result_dirsoc_societe", "result_rs_societe", "result_dir", "result_doc"]
        soup = BeautifulSoup(req.text, "html.parser")
        for t in tags:
            if soup.find('div', {'id': "{}".format(t)}):
                get_informations(identity, soup, t, city, keyword)
    print(separator)



if __name__ == '__main__':
    identity = ""
    search_societe(identity)