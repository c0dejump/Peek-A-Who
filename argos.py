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
from PIL import Image


#external modules
from static.banner import banner
from static.colors import info, match, error
from modules import google_search, phone_number
from modules.french_touch import whitepage, qualifications
from modules.social_media import facebook, linkedin, snapchat, tiktok, instagram
from modules.email import mail_search, email_guesser



def run_modules():
    """
    run_modules: run all module
    """
    #google_search.google_s(identity, phone_n, mail, pseudo, city)
    if identity:
        #facebook.facebook_search(dir_name, firstname=firstname, lastname=lastname, pseudo=pseudo, city=city, picture=picture)
        qualifications.qualifications_actions(identity, city, keyword)
        snapchat.parse_snapchat_username(identity, pseudo, city, keyword)
        tiktok.tiktok_username(identity, pseudo, city, keyword, picture)
        instagram.check_instagram(identity, pseudo, city, keyword, picture)
        whitepage.whitepage_search(dir_name, firstname=firstname, lastname=lastname, city=city)
        linkedin.linkedin_parsing(firstname, lastname, dir_name, picture=picture)
        email_guesser.emails_guess(firstname=firstname, lastname=lastname, pseudo=pseudo, birth_year=birth_year, keyword=keyword)
    if pseudo:
        facebook.facebook_search(dir_name, firstname=firstname, lastname=lastname, pseudo=pseudo, city=city, picture=picture)
        snapchat.parse_snapchat_username(identity, pseudo, city, keyword)
        tiktok.tiktok_username(identity, pseudo, city, keyword, picture)
        instagram.check_instagram(identity, pseudo, city, keyword, picture)
        email_guesser.emails_guess(firstname=firstname, lastname=lastname, pseudo=pseudo, birth_year=birth_year, keyword=keyword)
        print("\033[36m Pseudo search \033[0m")
        print("\033[36m-\033[0m"*30)
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
    if phone_n:
        phone_number.phone_number_actions(phone_n, dir_name)
        



def resume():
    """
    resume: Just resume arguments
    """
    print("""
 \033[36m Pseudo:           \033[0m {}       
 \033[36m Identity:         \033[0m {} {}
 \033[36m Mail adress:      \033[0m {}
 \033[36m Phone number:     \033[0m {}
 \033[36m Birth year:       \033[0m {}
 \033[36m City adress:      \033[0m {}
 \033[36m Keyword:          \033[0m {}

\033[35m____________________________________________\033[0m
    """.format("\033[32m{}\033[0m".format(pseudo) if pseudo else "N/A", "\033[32m{}\033[0m".format(firstname) if firstname else "N/A", "\033[32m{}\033[0m".format(lastname) if lastname else "", "\033[32m{}\033[0m".format(mail) if mail else "N/A","\033[32m{}\033[0m".format(phone_n) if phone_n else "N/A", "\033[32m{}\033[0m".format(birth_year) if birth_year else "N/A", "\033[32m{}\033[0m".format(city) if city else "N/A", "\033[32m{}\033[0m".format(keyword) if keyword else "N/A"))


if __name__ == '__main__':
    #arguments
    parser = argparse.ArgumentParser(add_help = True)
    parser = argparse.ArgumentParser(description='\033[32mVersion ß | contact: https://twitter.com/c0dejump\033[0m')

    group = parser.add_argument_group('\033[34m> General\033[0m')
    group.add_argument("-i", help="Identity, exemple: -i john_doe", dest='identity', required=False)
    group.add_argument("-n", help="Phone number, exemple: -n +337000000", dest='phone_number', required=False)
    group.add_argument("-m", help="Mail adress, exemple: -m toto@gmail.com", dest='mail', required=False)
    group.add_argument("-p", help="Pseudo, exemple: -p codejump", dest='pseudo', required=False)

    group = parser.add_argument_group('\033[34m> Assistance\033[0m')
    group.add_argument("-c", help="City adress, exemple: -c Paris", dest='city', required=False)
    group.add_argument("-b", help="birth year, exemple: -b 1999 (yeah my birth year)", dest='birth_year', required=False)
    group.add_argument("-k", help="Keyword, the script will be based on this, exemple: -k security", dest='keyword', required=False)
    group.add_argument("--pic", help="Picture, if you have a picture, it will allow you to compare it with the ones found during the scan: --pic image.png, --pic http://image.png", dest='picture', required=False)

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
    keyword = results.keyword
    picture = results.picture

    if identity and not "_" in identity:
        print("Please put a _ under firstname and lastname.")
        sys.exit()

    if picture:
        if not os.path.isfile(picture):
            print(" {}The image seem not exist".format(error))
            sys.exit()
        image_size = Image.open(picture)
        width, height = image_size.size
        if width <= 200 or height <= 200:
            print(" {}The size of the image is too small: width: {} / height: {}".format(error, width, height))
            sys.exit()

    firstname = identity.split("_")[0] if identity else None
    lastname = identity.split("_")[1] if identity else None

    dir_name = "reports/results/"+sys.argv[2]

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