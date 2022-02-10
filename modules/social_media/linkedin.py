#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback

from linkedin_api import Linkedin
from config import LINKEDIN_USERNAME, LINKEDIN_PASSWORD

#LINKEDIN_USERNAME = "codejumpdev@gmail.com"
#LINKEDIN_PASSWORD = "h1iEsLhiv8Zlcow8RlxU"

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def linkedin_scraping(url, username=False):

	linkedin_user = url.split("/")[4:5][0] if not username else url
	# Authenticate using any Linkedin account credentials
	location = []
	companies = []
	schools = []
	len_info = 0
	try:
		print(" [i] {}".format(linkedin_user))
		api = Linkedin(LINKEDIN_USERNAME,LINKEDIN_PASSWORD)

		profile = api.get_profile(linkedin_user) # GET a profile

		contact = api.get_profile_contact_info(linkedin_user) # Get information profile

		"""profil_posts = api.get_profile_updates(linkedin_user)
		#print(profil_posts)
		for p in profil_posts:
			if "CV" in p:
				print(p)
				break;"""

		try:
			#print(profile.items())
			for c in contact:
				if contact[c] != None and contact[c] != []:
					info_contact = contact[c] if type(contact[c]) != dict else "{}".format([contact[c][ic] for ic in contact[c]])
					print(" \u251c {}: {}".format(c, info_contact))
			for k, v in profile.items():
				if k == "geoLocationName":
					print(" \u251c Latest Locations: {}".format(profile[k]))
				if k == "experience":
					for e in profile[k]:
						if e.get('geoLocationName') != None and e.get('geoLocationName') not in location:
							location.append(e.get('geoLocationName'))
							print(" \u251c Other Location: {}".format(e.get('geoLocationName')))
						if e.get('companyName') != None and e.get('companyName') not in companies:
							print(" \u251c Company worked: {}".format(e.get('companyName')))
							companies.append(e.get('companyName'))
				if k == "education":
					for s in profile[k]:
						if s.get('schoolName') != None and s.get('schoolName') not in schools:
							print(" \u251c Schools: {}".format(s.get('schoolName')))
							schools.append(e.get('schoolName'))
		except:
			pass
	except:
		traceback.print_exc() #DEBUG
		print(" [i] This module need to login for search informations, please define it config.py")


"""if __name__ == '__main__':
	linkedin_scraping("https://www.linkedin.com/in/emna-rekik")"""