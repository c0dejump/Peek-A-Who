#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback

from static.colors import info, match, p_match, no_match, error, separator
from linkedin_api import Linkedin
from config import LINKEDIN_USERNAME, LINKEDIN_PASSWORD
from modules.image_analysis.facial_recognition import face_identification
from output import raw_output


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def get_linkedin_picture(profile, picture, dir_name, linkedin_user):
    url_image = "{}{}".format(profile["displayPictureUrl"],profile["img_400_400"])
    img_data = requests.get(url_image, verify=False).content
    with open("{}/{}.jpg".format(dir_name, linkedin_user), 'wb') as handler:
        handler.write(img_data)
    fid = face_identification(picture, "{}/{}.jpg".format(dir_name, linkedin_user))
    if fid:
        return True


def linkedin_scraping(url, picture, dir_name, username=False):

    linkedin_user = url.split("/")[4:5][0] if not username else url
    # Authenticate using any Linkedin account credentials
    location = []
    companies = []
    schools = []
    len_info = 0
    try:
        print(" {}{}".format(p_match, linkedin_user))
        api = Linkedin(LINKEDIN_USERNAME, LINKEDIN_PASSWORD)

        profile = api.get_profile(linkedin_user) # GET a profile
        contact = api.get_profile_contact_info(linkedin_user) # Get information profile

        """profil_posts = api.get_profile_updates(linkedin_user)
        print(profil_posts)
        for p in profil_posts:
            if "CV" in p:
                print(p)
                break;"""

        try:
            if profile:
                #print(profile.items())
                results_found += 1
                for c in contact:
                    if contact[c] != None and contact[c] != []:
                        info_contact = contact[c] if type(contact[c]) != dict else "{}".format([contact[c][ic] for ic in contact[c]])
                        print("   \u251c {}: {}".format(c, info_contact))
                for k, v in profile.items():
                    if k == "geoLocationName":
                        print("   \u251c Latest Locations: {}".format(profile[k]))
                    if k == "experience":
                        for e in profile[k]:
                            if e.get('geoLocationName') != None and e.get('geoLocationName') not in location:
                                location.append(e.get('geoLocationName'))
                                print("   \u251c Other Location: {}".format(e.get('geoLocationName')))
                            if e.get('companyName') != None and e.get('companyName') not in companies:
                                print("   \u251c Company worked: {}".format(e.get('companyName')))
                                companies.append(e.get('companyName'))
                    if k == "education":
                        for s in profile[k]:
                            if s.get('schoolName') != None and s.get('schoolName') not in schools:
                                print("   \u251c Schools: {}".format(s.get('schoolName')))
                                schools.append(e.get('schoolName'))
                if picture:
                    glp = get_linkedin_picture(profile, picture, dir_name, linkedin_user)
                    if glp:
                        print("     \033[32m\u251c Facial recognition matching with the {} account !\033[0m".format(linkedin_user))
            else:
                pass
        except:
            #traceback.print_exc()
            pass
    except:
        traceback.print_exc() #DEBUG
        print(" {}This module need to login for search informations, please define it config.py".format(info))


def linkedin_search(firstname, lastname, dir_name, picture):

    global results_found
    results_found = 0

    print("\033[36m Linkedin search \033[0m")
    print(separator)
    list_user = [
    "{}{}".format(firstname, lastname), "{}-{}".format(firstname, lastname), "{}.{}".format(firstname, lastname),
    "{}{}".format(lastname, firstname), "{}-{}".format(lastname, firstname), "{}.{}".format(lastname, firstname)
    ]
    for u in list_user:
        linkedin_scraping(u, picture, dir_name, True)

    results = "Linkedin returned {} accounts".format(results_found)
    raw_output(dir_name, "results_number", results)
    print(separator)


if __name__ == '__main__':
    linkedin_scraping("https://www.linkedin.com/in/emna-rekik", None, "reports/results/emna_rekik/") #"/mnt/c/Users/NathanFAILLENOT/OneDrive - Constellation/Images/OSINT_image/test_linkedin.jpg")