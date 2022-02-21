#! /usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
from bs4 import BeautifulSoup
from output import raw_output

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def whitepage_search(dir_name, firstname, lastname, city):
    print("\033[36m Whitepage search \033[0m")
    print("\033[36m-\033[0m"*30)

    city = city if city else ""
    url = "https://www.pages-annuaire.net/res/search?q={}+{}&w={}".format(firstname, lastname, city)
    found = False
    req = requests.get(url, verify=False, timeout=15)
    soup = BeautifulSoup(req.text, "html.parser")

    completed_addr = []

    try:
        results_number = soup.find_all("span")
        for rn in results_number:
            if firstname in rn.text and lastname in rn.text:
                number = rn.text
                print(" [+] {}\n".format(number.replace("résultats pour","results for").replace("à","") if not city else number))
                found = True
        if not found:
            print(" No found, proximity results:\n")
        else:
            name = soup.find_all("h3")
            addr = soup.find_all("div", attrs={"class": "container-adress"})
            for n in name:
                for a in addr:
                    if a.text not in completed_addr:
                        completed_addr.append(a.text)
                        results = "{}\t{}".format(n.text.replace("   ","").replace("\n",""), a.text.replace("   ","").replace("\n","").lower())
                        print(" \u251c {}".format(results))
                        raw_output(dir_name, "whitepage_search", results)
    except:
        traceback.print_exc() #DEBUG
    print("\n [i] you can check too here: https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={}+{}&ou={}".format(firstname, lastname, city))