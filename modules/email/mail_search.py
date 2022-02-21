#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests

def mail_site(mail_adress, dir_name):
    os.system("holehe {} --only-used --no-color --no-clear >> {}/site_use_by_mail.txt".format(mail_adress, dir_name))
    with open("{}/site_use_by_mail.txt".format(dir_name), "r") as sites:
        for site in sites.read().splitlines():
            if "[+]" in site and not "[-]" in site:
                print(site)



def mail_breach(mail, dir_name):
    check = requests.get("https://haveibeenpwned.com/unifiedsearch/{}".format(mail), verify=False, timeout=15)
    if check.status_code == 404: # The address has not been breached.
        print(" [+] {} has not been breached.".format(mail))
    elif check.status_code == 200: # The address has been breached!
        print(" [!] {} has been breached!".format(mail))
        for r in check.text:
            print(r)
    elif check.status_code == 403:
        print(" [X] Rate limit activated")


def skypli(mail_adress, dir_name):
    print("Searching Skype users")
    print("\033[36m-\033[0m"*30)
    
    url = "https://www.skypli.com/search/{}".format(mail_adress) 
    print(url)
    page = s.get(url, verify=False)
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
                            # find account using same e-mail username as someone else in skype (only look for underscore followed by last 1 or 2 chars being digits)
                            # then add them also to the pool (original string is also added before reduced in size)
                            if test_text[-1].isdigit() == True and test_text[-2] == "_":
                                structure.append(test_text[5:-2])
                            if test_text[-1].isdigit() == True and test_text[-2].isdigit() == True and test_text[-3] == "_":
                                structure.append(test_text[5:-3])
                    else:
                        structure.append(test_text)
        else:
            print("No results on Skype for this name")


def mail_actions(mail_adress, dir_name):

    mail_breach(mail_adress, dir_name)
    mail_site(mail_adress, dir_name)
    skypli(mail_adress, dir_name)