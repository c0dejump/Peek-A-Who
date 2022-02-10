#! /usr/bin/env python3
# -*- coding: utf-8 -*-

#modules in standard library
import requests
import sys, os, re
import time
from datetime import datetime
from time import strftime
import argparse
import json
import traceback


#external modules
from static.banner import banner
from modules import google_search, whitepage,
from modules.social_media import facebook, linkedin
from module.email import mail_search


def linkedin_parsing(firstname, lastname):
    print("\033[36m Linkedin search \033[0m")
    list_user = [
    "{}{}".format(firstname, lastname), "{}-{}".format(firstname, lastname), "{}.{}".format(firstname, lastname),
    "{}{}".format(lastname, firstname), "{}-{}".format(lastname, firstname), "{}.{}".format(lastname, firstname)
    ]
    for u in list_user:
        linkedin.linkedin_scraping(u, True)


def run_modules():
    """
    run_modules: run all module
    """
    google_search.google_s(identity, phone_n, mail, pseudo, city)
    if identity:
        facebook.facebook_search(dir_name, firstname=firstname, lastname=lastname, pseudo=pseudo)
        whitepage.whitepage_search(dir_name, firstname=firstname, lastname=lastname, city=city)
        linkedin_parsing(firstname, lastname)
    if pseudo:
        facebook.facebook_search(dir_name, firstname=firstname, lastname=lastname, pseudo=pseudo)
        print("\033[36m Pseudo search \033[0m")
        try:
            os.system("python3 tools/sherlock/sherlock/sherlock.py {} -o tools/sherlock/results/{}.txt >/dev/null 2>&1".format(pseudo, pseudo))
            with open("tools/sherlock/results/{}.txt".format(pseudo), "r") as result:
                for r in result.read().splitlines():
                    req = requests.get(r, verify=False, timeout=15)
                    if req.status_code not in [404, 403, 401, 500, 429]:
                        print(" [+] {}".format(r))
        except Exception:
            #pass
            traceback.print_exc()
    if mail:
        mail_search.mail_actions(mail, dir_name)


def resume():
    """
    resume: Just resume arguments
    """
    print("""
 \033[36m Pseudo:           \033[0m {}       
 \033[36m Identity:         \033[0m {} {}
 \033[36m Phone number:     \033[0m {}
 \033[36m Mail adress:      \033[0m {}
 \033[36m City adress:      \033[0m {}
 \033[36m Birth year:       \033[0m {}

\033[31m____________________________________________\033[0m
    """.format(pseudo if pseudo else "N/A", firstname if firstname else "N/A", lastname if lastname else "N/A", phone_n if phone_n else "N/A", 
        mail if mail else "N/A", city if city else "N/A", birth_year if birth_year else "N/A"))


if __name__ == '__main__':
    #arguments
    parser = argparse.ArgumentParser(add_help = True)
    parser = argparse.ArgumentParser(description='\033[32mVersion ß | contact: https://twitter.com/c0dejump\033[0m')

    group = parser.add_argument_group('\033[34m> General\033[0m')
    group.add_argument("-i", help="Identity, exemple: -i john_doe", dest='identity', required=False)
    group.add_argument("-n", help="Phone number, exemple: -p +337000000", dest='phone_number', required=False)
    group.add_argument("-m", help="Mail adress, exemple: -m toto@gmail.com", dest='mail', required=False)
    group.add_argument("-p", help="Pseudo, exemple: -p codejump", dest='pseudo', required=False)

    group = parser.add_argument_group('\033[34m> Assistance\033[0m')
    group.add_argument("-c", help="City adress, exemple: -c Paris", dest='city', required=False)
    group.add_argument("-b", help="birth year, exemple: -b 1999 (yeah my birth year)", dest='birth_year', required=False)
    group.add_argument("-k", help="Keyword, the script will be based on this, exemple: -k security", dest='city', required=False)

    results = parser.parse_args()

    if len(sys.argv) < 2:
        print("\nOption missing\n")
        parser.print_help()
        sys.exit()

    banner()

    identity = results.identity
    phone_n = results.phone_number
    mail = results.mail
    city = results.city
    pseudo = results.pseudo
    birth_year = results.birth_year

    if identity and not "_" in identity:
        print("Please put a _ under firstname and lastname.")
        sys.exit()

    firstname = identity.split("_")[0] if identity else None
    lastname = identity.split("_")[1] if identity else None

    dir_name = "reports/"+sys.argv[2]

    resume()
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
        run_modules()
    else:
        finish_sorting = input("Have you finished sorting the information ? [y/n] ")
        if finish_sorting == "Y" or finish_sorting == "y":
            print("ok")
            run_modules()
            #re-running scan with the known informations
        else:
            print("Ok no problem")
            run_modules()