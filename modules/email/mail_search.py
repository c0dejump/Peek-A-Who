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


def mail_actions(mail_adress, dir_name):

    mail_breach(mail_adress, dir_name)
    mail_site(mail_adress, dir_name)