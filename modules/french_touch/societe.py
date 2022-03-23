#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup

from static.colors import info, match, p_match, no_match, error, separator

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


# hxxps://www.pappers.fr/recherche-dirigeants?q=Laurent+TUPIN&date_de_naissance_dirigeant_min=12-03-1975&date_de_naissance_dirigeant_max=12-03-1975


def get_informations(identity, soup, t, city, keyword, birth_year):
    matching = False
    detail = []

    if birth_year and "-" in birth_year:
        range_birth = range(int(birth_year.split("-")[0]), int(birth_year.split("-")[1]))
    else:
        range_birth = False

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
    for d in details:
        d = d.text.strip().replace("  ", "").replace("\n", "").replace("\t", "")
        if len(d) < 70 and "doc" not in t:
            if city != None and city.lower() in d.lower():
                detail.append("   {}\033[32m{}\033[0m".format(match, d))
                matching = True
            elif keyword != None and keyword.lower() in d.lower():
                detail.append("   {}\033[32m{}\033[0m".format(match, d))
                matching = True
            elif birth_year != None and not range_birth and birth_year in d.lower():
                detail.append("   {}\033[32m{}\033[0m".format(match, d))
                matching = True
            elif range_birth and [rb for rb in range_birth if str(rb) in d.lower()]:
                detail.append("   {}\033[32m{}\033[0m".format(match, d))
                matching = True
            else:
                detail.append("   \u251c {}".format(d))

    print(" {}{}".format(p_match if not matching else match, result.strip().replace("  ", "").replace("\n", "")))
    print("   {}{}".format("\u251c " if not matching else match, name.text.strip().replace("  ", "").replace("\n", "")))
    for d in detail:
        print(d)


def search_societe(dir_name, identity, city, keyword, birth_year):
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
                get_informations(identity, soup, t, city, keyword, birth_year)
        print(" {} See here for more informations: https://www.pappers.fr/recherche-dirigeants?q={}".format(info, identity))
    print(separator)



if __name__ == '__main__':
    identity = ""
    search_societe(identity)